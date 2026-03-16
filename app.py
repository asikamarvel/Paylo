"""Paylo - Modern Payroll System."""

import os
from pathlib import Path
from datetime import datetime
from decimal import Decimal
from typing import Dict
from flask import Flask, render_template, request, jsonify, send_file, session
import pandas as pd
import yaml

import sys
sys.path.insert(0, str(Path(__file__).parent))

from src.calculator_v2 import PayrollCalculator, StaffMember, PayrollBreakdown
from src.currency import get_currency_converter
from src.report import PayrollReport

app = Flask(__name__, template_folder='templates', static_folder='static')
app.secret_key = os.urandom(24)

UPLOAD_FOLDER = Path(__file__).parent / 'uploads'
OUTPUT_FOLDER = Path(__file__).parent / 'output'
CONFIG_DIR = Path(__file__).parent / 'config'

UPLOAD_FOLDER.mkdir(exist_ok=True)
OUTPUT_FOLDER.mkdir(exist_ok=True)

app.config['UPLOAD_FOLDER'] = str(UPLOAD_FOLDER)
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024

calculator = PayrollCalculator(config_dir=str(CONFIG_DIR))
currency_converter = get_currency_converter(use_mock=False, config_dir=str(CONFIG_DIR))


def load_staff_registry() -> Dict[str, StaffMember]:
    staff_file = CONFIG_DIR / 'staff.yaml'
    staff_dict = {}
    
    if staff_file.exists():
        with open(staff_file, 'r') as f:
            staff_data = yaml.safe_load(f)
        
        for entry in staff_data.get('staff', []):
            name = entry.get('name', '')
            normalized_name = ' '.join(name.lower().split())
            staff_dict[normalized_name] = StaffMember(
                name=name,
                cadre=entry.get('cadre', 'analyst'),
                contractor_type=entry.get('contractor_type', 'local'),
                contract_structure=entry.get('contract_structure', 'fixed_base'),
                hmo_deduction=entry.get('hmo_deduction', 0.0),
                fixed_amount=entry.get('fixed_amount', 0.0)
            )
    
    return staff_dict


def lookup_staff(staff_registry: Dict[str, StaffMember], name: str) -> StaffMember:
    normalized_name = ' '.join(name.lower().split())
    return staff_registry.get(normalized_name)


def parse_harvest_excel(filepath: str) -> dict:
    try:
        df = pd.read_excel(filepath, header=1)
        first_col = str(df.columns[0]).strip().lower()
        if first_col not in ['names', 'name', 'row labels', 'staff']:
            df = pd.read_excel(filepath)
    except:
        df = pd.read_excel(filepath)
    
    name_col = df.columns[0]
    
    project_cols = []
    for col in df.columns[1:]:
        col_str = str(col).strip().lower()
        if col_str not in ['grand total', 'total', 'unnamed']:
            project_cols.append(col)
    
    users_data = {}
    
    for idx, row in df.iterrows():
        staff_name = str(row[name_col]).strip()
        
        if not staff_name or staff_name.lower() in ['grand total', 'total', '', 'nan', 'names', 'name']:
            continue
        
        hours_by_project = {}
        for project in project_cols:
            hours = row.get(project, 0)
            if pd.notna(hours) and hours != '' and hours != 0:
                try:
                    hours_val = float(hours)
                    if hours_val > 0:
                        project_name = str(project).strip()
                        hours_by_project[project_name] = hours_val
                except (ValueError, TypeError):
                    pass
        
        if hours_by_project:
            users_data[staff_name] = hours_by_project
    
    return users_data


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/exchange-rate')
def get_exchange_rate():
    """Fetch current exchange rate."""
    rate = currency_converter.get_exchange_rate("NGN", "USD")
    is_manual = currency_converter.is_manual_mode()
    return jsonify({
        'rate': rate,
        'from': 'USD',
        'to': 'NGN',
        'mode': 'manual' if is_manual else 'auto',
        'timestamp': datetime.now().isoformat()
    })


@app.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return jsonify({'error': 'No file uploaded'}), 400
    
    file = request.files['file']
    
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400
    
    if not file.filename.endswith(('.xlsx', '.xls', '.csv')):
        return jsonify({'error': 'Please upload an Excel or CSV file'}), 400
    
    try:
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"harvest_upload_{timestamp}.xlsx"
        filepath = UPLOAD_FOLDER / filename
        file.save(str(filepath))
        
        users_hours = parse_harvest_excel(str(filepath))
        staff_registry = load_staff_registry()
        usd_rate = currency_converter.get_exchange_rate("NGN", "USD")
        
        results = []
        period = datetime.now().strftime('%B %Y')
        all_billable_projects = set()

        for name, hours_by_project in users_hours.items():
            staff = lookup_staff(staff_registry, name)

            if staff is None:
                staff = StaffMember(name=name, cadre="analyst", contractor_type="local")

            payroll = calculator.calculate_payroll(staff=staff, hours_by_project=hours_by_project, period=period)

            # Build project breakdown
            billable_projects = []
            non_billable_projects = []
            for project_name, project_hours in hours_by_project.items():
                proj_class = calculator.get_project_classification(project_name)
                proj_info = {
                    'name': project_name,
                    'hours': float(project_hours),
                    'geography': proj_class.get('geography', 'local')
                }
                if proj_class.get("billable_type") == "billable":
                    billable_projects.append(proj_info)
                    all_billable_projects.add(project_name)
                else:
                    non_billable_projects.append(proj_info)

            total_hours = payroll.hours.total_hours
            total_billable = payroll.hours.local_billable_hours + payroll.hours.regional_billable_hours

            # Calculate extra fees breakdown
            extra_local_fees = float(payroll.local_hourly_rate) * float(payroll.hours.extra_local_billable_hours)
            extra_regional_fees = float(payroll.regional_hourly_rate) * float(payroll.hours.extra_regional_billable_hours)
            total_extra_fees = float(payroll.local_billable_fees) + float(payroll.regional_billable_fees)

            results.append({
                'name': staff.name,
                'contract_structure': staff.contract_structure.replace('_', ' ').title(),
                'cadre': staff.cadre.replace('_', ' ').title(),
                'cadre_key': staff.cadre,
                'contractor_type': staff.contractor_type.title(),
                'currency': payroll.currency,
                # Hours
                'total_hours': float(total_hours),
                'billable_hours': float(total_billable),
                'non_billable_hours': float(payroll.hours.non_billable_hours),
                'local_billable_hours': float(payroll.hours.local_billable_hours),
                'regional_billable_hours': float(payroll.hours.regional_billable_hours),
                # Thresholds
                'base_billable_hours': float(payroll.hours.base_billable_hours),
                'base_non_billable_hours': float(payroll.hours.base_non_billable_hours),
                'total_base_hours': float(payroll.hours.total_base_hours),
                # Extra hours
                'extra_billable_hours': float(payroll.hours.extra_billable_hours),
                'extra_local_billable': float(payroll.hours.extra_local_billable_hours),
                'extra_regional_billable': float(payroll.hours.extra_regional_billable_hours),
                # Rates
                'local_hourly_rate': float(payroll.local_hourly_rate),
                'regional_hourly_rate': float(payroll.regional_hourly_rate),
                # Extra fees breakdown
                'extra_local_fees': extra_local_fees,
                'extra_regional_fees': extra_regional_fees,
                'total_extra_fees': total_extra_fees,
                # Projects breakdown
                'billable_projects': billable_projects,
                'non_billable_projects': non_billable_projects,
                # Compensation
                'base_payment': float(payroll.base_payment),
                'basic_compensation': float(payroll.basic_compensation),
                'gross_pay': float(payroll.gross_compensation),
                # Deductions
                'withholding_tax': float(payroll.withholding_tax),
                'hmo_deduction': float(payroll.hmo_deduction),
                'total_deductions': float(payroll.total_deductions),
                'net_pay': float(payroll.net_compensation),
                'notes': payroll.calculation_notes
            })
        
        session['last_results'] = results
        session['last_period'] = period
        
        totals = {
            'total_hours': sum(r['total_hours'] for r in results),
            'billable_hours': sum(r['billable_hours'] for r in results),
            'non_billable_hours': sum(r['non_billable_hours'] for r in results),
            'extra_billable_hours': sum(r['extra_billable_hours'] for r in results),
            'gross_pay': sum(r['gross_pay'] for r in results),
            'total_deductions': sum(r['total_deductions'] for r in results),
            'net_pay': sum(r['net_pay'] for r in results),
            'delivering_projects': len(all_billable_projects)
        }
        
        return jsonify({
            'success': True,
            'period': period,
            'exchange_rate': usd_rate,
            'staff_count': len(results),
            'results': results,
            'totals': totals
        })
        
    except Exception as e:
        import traceback
        return jsonify({'error': str(e), 'trace': traceback.format_exc()}), 500


@app.route('/staff')
def staff_management():
    staff_registry = load_staff_registry()
    staff_list = [
        {
            'id': idx,
            'name': s.name,
            'cadre': s.cadre,
            'contractor_type': s.contractor_type,
            'contract_structure': s.contract_structure,
            'hmo_deduction': s.hmo_deduction,
            'fixed_amount': s.fixed_amount
        }
        for idx, (name, s) in enumerate(staff_registry.items())
    ]

    cadres = calculator.get_all_cadres()
    return render_template('staff.html', staff=staff_list, cadres=cadres)


@app.route('/staff/update', methods=['POST'])
def update_staff():
    """Legacy endpoint - redirects to new API."""
    data = request.json
    staff_name = data.get('name')

    try:
        staff_file = CONFIG_DIR / 'staff.yaml'
        with open(staff_file, 'r') as f:
            staff_data = yaml.safe_load(f)

        for entry in staff_data.get('staff', []):
            if entry.get('name', '').lower() == staff_name.lower():
                entry['cadre'] = data.get('cadre', entry.get('cadre'))
                entry['contractor_type'] = data.get('contractor_type', entry.get('contractor_type'))
                if 'contract_structure' in data:
                    entry['contract_structure'] = data['contract_structure']
                if 'hmo_deduction' in data:
                    entry['hmo_deduction'] = float(data['hmo_deduction'])
                if 'fixed_amount' in data:
                    entry['fixed_amount'] = float(data['fixed_amount'])
                break

        with open(staff_file, 'w') as f:
            yaml.dump(staff_data, f, default_flow_style=False, allow_unicode=True)

        return jsonify({'success': True})

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/download')
def download_report():
    results = session.get('last_results')
    period = session.get('last_period', 'Payroll')
    
    if not results:
        return "No payroll data. Upload a file first.", 400
    
    try:
        from src.calculator_v2 import PayrollBreakdown, HoursBreakdown
        
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"payroll_{period.replace(' ', '_')}_{timestamp}.xlsx"
        filepath = OUTPUT_FOLDER / filename
        
        export_data = []
        for r in results:
            export_data.append({
                'Staff Name': r['name'],
                'Cadre': r['cadre'],
                'Contractor Type': r['contractor_type'],
                'Total Hours': r['total_hours'],
                'Billable Hours': r['billable_hours'],
                'Non-Billable Hours': r['non_billable_hours'],
                'Base Payment': r.get('base_payment', 0),
                'Local Billable Fees': r.get('local_billable_fees', 0),
                'Regional Billable Fees': r.get('regional_billable_fees', 0),
                'Gross Pay': r['gross_pay'],
                'WHT': r['withholding_tax'],
                'HMO': r.get('hmo_deduction', 0),
                'Total Deductions': r['total_deductions'],
                'Net Pay': r['net_pay'],
                'Currency': r['currency']
            })
        
        df = pd.DataFrame(export_data)
        df.to_excel(str(filepath), index=False)
        
        return send_file(str(filepath), as_attachment=True, download_name=filename)
        
    except Exception as e:
        import traceback
        return f"Error: {str(e)}\n{traceback.format_exc()}", 500


@app.route('/config')
def view_config():
    cadres = calculator.cadres_config.get('cadres', {})
    contracts = calculator.contracts_config
    deductions = calculator.deductions_config

    # Load projects config
    projects_file = CONFIG_DIR / 'projects.yaml'
    projects = {}
    if projects_file.exists():
        with open(projects_file, 'r') as f:
            projects = yaml.safe_load(f) or {}

    # Get current exchange rate
    current_rate = currency_converter.get_exchange_rate("NGN", "USD")

    return render_template('config.html',
                          cadres=cadres,
                          contracts=contracts,
                          deductions=deductions,
                          projects=projects.get('projects', {}),
                          exchange_rate=current_rate)


# ==================== CADRES API ====================

@app.route('/api/cadres', methods=['GET'])
def get_cadres():
    """Get all cadres configuration."""
    return jsonify(calculator.cadres_config.get('cadres', {}))


@app.route('/api/cadres/<cadre_key>', methods=['PUT'])
def update_cadre(cadre_key):
    """Update a specific cadre's configuration."""
    data = request.json

    try:
        cadres_file = CONFIG_DIR / 'cadres.yaml'
        with open(cadres_file, 'r') as f:
            cadres_config = yaml.safe_load(f)

        if cadre_key not in cadres_config.get('cadres', {}):
            return jsonify({'error': f'Cadre {cadre_key} not found'}), 404

        # Update the cadre configuration
        cadre = cadres_config['cadres'][cadre_key]

        # Update fields that are provided
        if 'display_name' in data:
            cadre['display_name'] = data['display_name']
        if 'base_payment_ngn' in data:
            cadre['base_payment_ngn'] = float(data['base_payment_ngn'])
        if 'base_payment_usd' in data:
            cadre['base_payment_usd'] = float(data['base_payment_usd'])
        if 'local_hourly_rate' in data:
            cadre['local_hourly_rate'] = float(data['local_hourly_rate'])
        if 'regional_hourly_rate' in data:
            cadre['regional_hourly_rate'] = float(data['regional_hourly_rate'])
        if 'regional_hourly_rate_usd' in data:
            cadre['regional_hourly_rate_usd'] = float(data['regional_hourly_rate_usd'])
        if 'base_billable_hours' in data:
            cadre['base_billable_hours'] = int(data['base_billable_hours'])
        if 'base_non_billable_hours' in data:
            cadre['base_non_billable_hours'] = int(data['base_non_billable_hours'])
        if 'total_base_hours' in data:
            cadre['total_base_hours'] = int(data['total_base_hours'])

        with open(cadres_file, 'w') as f:
            yaml.dump(cadres_config, f, default_flow_style=False, allow_unicode=True)

        # Reload calculator config
        calculator.cadres_config = cadres_config

        return jsonify({'success': True, 'cadre': cadre})

    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ==================== PROJECTS API ====================

@app.route('/api/projects', methods=['GET'])
def get_projects():
    """Get all projects configuration."""
    projects_file = CONFIG_DIR / 'projects.yaml'
    if projects_file.exists():
        with open(projects_file, 'r') as f:
            projects = yaml.safe_load(f)
        return jsonify(projects.get('projects', {}))
    return jsonify({})


@app.route('/api/projects', methods=['POST'])
def add_project():
    """Add a new project."""
    data = request.json

    try:
        projects_file = CONFIG_DIR / 'projects.yaml'
        with open(projects_file, 'r') as f:
            projects_config = yaml.safe_load(f) or {'projects': {}, 'default': {'billable_type': 'non_billable', 'geography': 'local'}}

        project_name = data.get('name')
        if not project_name:
            return jsonify({'error': 'Project name is required'}), 400

        projects_config['projects'][project_name] = {
            'billable_type': data.get('billable_type', 'non_billable'),
            'geography': data.get('geography', 'local')
        }

        with open(projects_file, 'w') as f:
            yaml.dump(projects_config, f, default_flow_style=False, allow_unicode=True)

        # Reload calculator config
        calculator.projects_config = projects_config

        return jsonify({'success': True})

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/projects/<path:project_name>', methods=['PUT'])
def update_project(project_name):
    """Update a project's classification."""
    data = request.json

    try:
        projects_file = CONFIG_DIR / 'projects.yaml'
        with open(projects_file, 'r') as f:
            projects_config = yaml.safe_load(f)

        if project_name not in projects_config.get('projects', {}):
            return jsonify({'error': f'Project {project_name} not found'}), 404

        projects_config['projects'][project_name] = {
            'billable_type': data.get('billable_type', 'non_billable'),
            'geography': data.get('geography', 'local')
        }

        with open(projects_file, 'w') as f:
            yaml.dump(projects_config, f, default_flow_style=False, allow_unicode=True)

        calculator.projects_config = projects_config

        return jsonify({'success': True})

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/projects/<path:project_name>', methods=['DELETE'])
def delete_project(project_name):
    """Delete a project."""
    try:
        projects_file = CONFIG_DIR / 'projects.yaml'
        with open(projects_file, 'r') as f:
            projects_config = yaml.safe_load(f)

        if project_name in projects_config.get('projects', {}):
            del projects_config['projects'][project_name]

        with open(projects_file, 'w') as f:
            yaml.dump(projects_config, f, default_flow_style=False, allow_unicode=True)

        calculator.projects_config = projects_config

        return jsonify({'success': True})

    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ==================== STAFF API ====================

@app.route('/api/staff', methods=['GET'])
def get_all_staff():
    """Get all staff."""
    staff_registry = load_staff_registry()
    staff_list = [
        {
            'name': s.name,
            'cadre': s.cadre,
            'contractor_type': s.contractor_type,
            'contract_structure': s.contract_structure,
            'hmo_deduction': s.hmo_deduction,
            'fixed_amount': s.fixed_amount
        }
        for name, s in staff_registry.items()
    ]
    return jsonify(staff_list)


@app.route('/api/staff', methods=['POST'])
def add_staff():
    """Add a new staff member."""
    data = request.json

    try:
        staff_file = CONFIG_DIR / 'staff.yaml'
        with open(staff_file, 'r') as f:
            staff_data = yaml.safe_load(f) or {'staff': []}

        staff_name = data.get('name')
        if not staff_name:
            return jsonify({'error': 'Staff name is required'}), 400

        # Check if staff already exists
        for entry in staff_data.get('staff', []):
            if entry.get('name', '').lower() == staff_name.lower():
                return jsonify({'error': 'Staff member already exists'}), 400

        new_staff = {
            'name': staff_name,
            'cadre': data.get('cadre', 'analyst'),
            'contractor_type': data.get('contractor_type', 'local'),
            'contract_structure': data.get('contract_structure', 'fixed_base'),
            'hmo_deduction': float(data.get('hmo_deduction', 0)),
        }

        if data.get('fixed_amount'):
            new_staff['fixed_amount'] = float(data.get('fixed_amount', 0))

        staff_data['staff'].append(new_staff)

        with open(staff_file, 'w') as f:
            yaml.dump(staff_data, f, default_flow_style=False, allow_unicode=True)

        return jsonify({'success': True, 'staff': new_staff})

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/staff/<path:staff_name>', methods=['PUT'])
def update_staff_member(staff_name):
    """Update a staff member."""
    data = request.json

    try:
        staff_file = CONFIG_DIR / 'staff.yaml'
        with open(staff_file, 'r') as f:
            staff_data = yaml.safe_load(f)

        found = False
        for entry in staff_data.get('staff', []):
            if entry.get('name', '').lower() == staff_name.lower():
                found = True
                if 'cadre' in data:
                    entry['cadre'] = data['cadre']
                if 'contractor_type' in data:
                    entry['contractor_type'] = data['contractor_type']
                if 'contract_structure' in data:
                    entry['contract_structure'] = data['contract_structure']
                if 'hmo_deduction' in data:
                    entry['hmo_deduction'] = float(data['hmo_deduction'])
                if 'fixed_amount' in data:
                    entry['fixed_amount'] = float(data['fixed_amount'])
                break

        if not found:
            return jsonify({'error': f'Staff {staff_name} not found'}), 404

        with open(staff_file, 'w') as f:
            yaml.dump(staff_data, f, default_flow_style=False, allow_unicode=True)

        return jsonify({'success': True})

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/staff/<path:staff_name>', methods=['DELETE'])
def delete_staff_member(staff_name):
    """Delete a staff member."""
    try:
        staff_file = CONFIG_DIR / 'staff.yaml'
        with open(staff_file, 'r') as f:
            staff_data = yaml.safe_load(f)

        staff_data['staff'] = [
            entry for entry in staff_data.get('staff', [])
            if entry.get('name', '').lower() != staff_name.lower()
        ]

        with open(staff_file, 'w') as f:
            yaml.dump(staff_data, f, default_flow_style=False, allow_unicode=True)

        return jsonify({'success': True})

    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ==================== EXCHANGE RATE API ====================

@app.route('/api/exchange-rate', methods=['PUT'])
def set_manual_exchange_rate():
    """Set a manual exchange rate override."""
    data = request.json

    try:
        rate = float(data.get('rate'))
        if rate <= 0:
            return jsonify({'error': 'Rate must be positive'}), 400

        # Store in a config file
        settings_file = CONFIG_DIR / 'settings.yaml'
        settings = {}
        if settings_file.exists():
            with open(settings_file, 'r') as f:
                settings = yaml.safe_load(f) or {}

        settings['manual_exchange_rate'] = rate
        settings['exchange_rate_mode'] = 'manual'

        with open(settings_file, 'w') as f:
            yaml.dump(settings, f, default_flow_style=False)

        # Update the currency converter
        currency_converter.set_manual_rate(rate)

        return jsonify({'success': True, 'rate': rate})

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/exchange-rate/auto', methods=['POST'])
def enable_auto_exchange_rate():
    """Enable automatic exchange rate fetching."""
    try:
        settings_file = CONFIG_DIR / 'settings.yaml'
        settings = {}
        if settings_file.exists():
            with open(settings_file, 'r') as f:
                settings = yaml.safe_load(f) or {}

        settings['exchange_rate_mode'] = 'auto'
        if 'manual_exchange_rate' in settings:
            del settings['manual_exchange_rate']

        with open(settings_file, 'w') as f:
            yaml.dump(settings, f, default_flow_style=False)

        # Clear manual rate in converter
        currency_converter.clear_manual_rate()

        # Fetch fresh rate
        rate = currency_converter.get_exchange_rate("NGN", "USD")

        return jsonify({'success': True, 'rate': rate, 'mode': 'auto'})

    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ==================== CONTRACTS/DEDUCTIONS API ====================

@app.route('/api/contractor-types/<type_key>', methods=['PUT'])
def update_contractor_type(type_key):
    """Update contractor type settings (e.g., WHT rate)."""
    data = request.json

    try:
        contracts_file = CONFIG_DIR / 'contracts.yaml'
        with open(contracts_file, 'r') as f:
            contracts_config = yaml.safe_load(f)

        if type_key not in contracts_config.get('contractor_types', {}):
            return jsonify({'error': f'Contractor type {type_key} not found'}), 404

        ct = contracts_config['contractor_types'][type_key]

        if 'withholding_tax_rate' in data:
            ct['withholding_tax_rate'] = float(data['withholding_tax_rate'])
        if 'display_name' in data:
            ct['display_name'] = data['display_name']
        if 'currency' in data:
            ct['currency'] = data['currency']

        with open(contracts_file, 'w') as f:
            yaml.dump(contracts_config, f, default_flow_style=False, allow_unicode=True)

        calculator.contracts_config = contracts_config

        return jsonify({'success': True})

    except Exception as e:
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    print("\n" + "="*50)
    print("PAYLO")
    print("="*50)
    print("\nServer: http://localhost:5000")
    print("Press Ctrl+C to stop")
    print("="*50 + "\n")

    app.run(debug=True, host='0.0.0.0', port=5000)
