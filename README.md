# Paylo

Modern payroll calculation system with Harvest time tracking integration. Designed for consulting firms with complex billing structures.

## Features

- Process Harvest time exports to calculate staff payroll
- Support for multiple cadre levels with different rate cards
- Local (NGN) and Regional (USD) contractor types
- Flexible contract structures (Fixed-Base, Flexible, Fixed Pay)
- Real-time exchange rate integration
- Configurable billing thresholds and hourly rates
- Detailed payroll breakdown with project-level analysis
- Full admin interface for configuration management

## Quick Start

```bash
pip install -r requirements.txt
python app.py
```

Open http://localhost:5000

## Usage

1. Export time data from Harvest as Excel pivot table
2. Upload the file in the web interface
3. Review calculated payroll with detailed breakdown
4. Download Excel report

## Administration

### Staff Management (`/staff`)
- Add, edit, and remove staff members
- Change cadre levels (promotions/demotions)
- Configure contractor type and contract structure
- Set HMO deductions and fixed amounts

### Configuration (`/config`)
- **Cadres & Rates**: Edit base salaries, hourly rates, and thresholds
- **Projects**: Classify projects as billable/non-billable and local/regional
- **Exchange Rate**: Set manual rate or use live API
- **Contractor Types**: Configure WHT rates and currencies

## Configuration Files

Edit YAML files in `config/` folder:
- `cadres.yaml` - Rate cards by cadre level
- `staff.yaml` - Staff registry with contract details
- `contracts.yaml` - Contract types and tax rates
- `projects.yaml` - Project billing classification

## Contract Types

- **Fixed-Base**: Monthly base salary + extra pay for billable hours beyond threshold
- **Flexible**: Pay per billable hour only (no base salary)
- **Fixed Pay**: Fixed monthly amount for contractors/advisors

## Tax Rates

- Local Contractors (NGN): 5% Withholding Tax
- Regional Contractors (USD): 10% Withholding Tax

## License

Copyright (c) 2024-2026 OmaxilTech. All rights reserved.
See LICENSE file for details.

---

**OmaxilTech** | [tech.omaxil.com](https://tech.omaxil.com)
