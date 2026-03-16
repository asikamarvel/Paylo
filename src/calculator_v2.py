"""Payroll calculator."""

import yaml
from pathlib import Path
from dataclasses import dataclass, field
from typing import Dict
from decimal import Decimal, ROUND_HALF_UP


@dataclass
class StaffMember:
    name: str
    cadre: str = "analyst"
    contractor_type: str = "local"
    contract_structure: str = "fixed_base"
    hmo_deduction: float = 0.0
    fixed_amount: float = 0.0


@dataclass
class HoursBreakdown:
    total_hours: float = 0.0
    local_billable_hours: float = 0.0
    regional_billable_hours: float = 0.0
    total_billable_hours: float = 0.0
    non_billable_hours: float = 0.0
    base_billable_hours: float = 0.0
    base_non_billable_hours: float = 0.0
    total_base_hours: float = 0.0
    extra_local_billable_hours: float = 0.0
    extra_regional_billable_hours: float = 0.0
    extra_billable_hours: float = 0.0


@dataclass
class PayrollBreakdown:
    staff: StaffMember
    hours: HoursBreakdown
    base_payment: Decimal = Decimal("0")
    local_billable_fees: Decimal = Decimal("0")
    regional_billable_fees: Decimal = Decimal("0")
    basic_compensation: Decimal = Decimal("0")
    gross_compensation: Decimal = Decimal("0")
    withholding_tax: Decimal = Decimal("0")
    hmo_deduction: Decimal = Decimal("0")
    total_deductions: Decimal = Decimal("0")
    net_compensation: Decimal = Decimal("0")
    local_hourly_rate: Decimal = Decimal("0")
    regional_hourly_rate: Decimal = Decimal("0")
    currency: str = "NGN"
    period: str = ""
    calculation_notes: list = field(default_factory=list)


class PayrollCalculator:
    
    def __init__(self, config_dir: str = None):
        if config_dir is None:
            config_dir = Path(__file__).parent.parent / "config"
        else:
            config_dir = Path(config_dir)
        
        self.config_dir = config_dir
        self._load_configurations()
    
    def _load_configurations(self):
        with open(self.config_dir / "cadres.yaml", "r") as f:
            self.cadres_config = yaml.safe_load(f)
        
        with open(self.config_dir / "contracts.yaml", "r") as f:
            self.contracts_config = yaml.safe_load(f)
        
        with open(self.config_dir / "deductions.yaml", "r") as f:
            self.deductions_config = yaml.safe_load(f)
        
        projects_file = self.config_dir / "projects.yaml"
        if projects_file.exists():
            with open(projects_file, "r") as f:
                self.projects_config = yaml.safe_load(f)
        else:
            self.projects_config = {"projects": {}, "default": {"billable_type": "non_billable", "geography": "local"}}
    
    def get_cadre_config(self, cadre: str) -> dict:
        return self.cadres_config.get("cadres", {}).get(cadre, {})
    
    def get_project_classification(self, project_name: str) -> dict:
        projects = self.projects_config.get("projects", {})
        
        if project_name in projects:
            return projects[project_name]
        
        for proj_name, proj_config in projects.items():
            if proj_name.lower() in project_name.lower() or project_name.lower() in proj_name.lower():
                return proj_config
        
        return self.projects_config.get("default", {"billable_type": "non_billable", "geography": "local"})
    
    def calculate_hours_breakdown(self, staff: StaffMember, hours_by_project: Dict[str, float]) -> HoursBreakdown:
        cadre_config = self.get_cadre_config(staff.cadre)

        hours = HoursBreakdown()
        hours.base_billable_hours = cadre_config.get("base_billable_hours", 20)
        hours.base_non_billable_hours = cadre_config.get("base_non_billable_hours", 60)
        hours.total_base_hours = cadre_config.get("total_base_hours", 80)

        for project_name, project_hours in hours_by_project.items():
            classification = self.get_project_classification(project_name)
            billable_type = classification.get("billable_type", "non_billable")
            geography = classification.get("geography", "local")

            hours.total_hours += project_hours

            if billable_type == "billable":
                if geography == "regional":
                    hours.regional_billable_hours += project_hours
                else:
                    hours.local_billable_hours += project_hours
            else:
                hours.non_billable_hours += project_hours

        hours.total_billable_hours = hours.local_billable_hours + hours.regional_billable_hours

        # Calculate extra billable hours (hours above threshold that get paid)
        if hours.total_billable_hours > hours.base_billable_hours:
            hours.extra_billable_hours = hours.total_billable_hours - hours.base_billable_hours

            # Distribute extra hours between local and regional (prioritize regional rate)
            if hours.regional_billable_hours > 0:
                hours.extra_regional_billable_hours = min(hours.extra_billable_hours, hours.regional_billable_hours)
                remaining_extra = hours.extra_billable_hours - hours.extra_regional_billable_hours
                if remaining_extra > 0:
                    hours.extra_local_billable_hours = remaining_extra
            else:
                hours.extra_local_billable_hours = hours.extra_billable_hours

        return hours
    
    def calculate_payroll(self, staff: StaffMember, hours_by_project: Dict[str, float], period: str = "") -> PayrollBreakdown:
        cadre_config = self.get_cadre_config(staff.cadre)
        contractor_config = self.contracts_config.get("contractor_types", {}).get(staff.contractor_type, {})
        
        hours = self.calculate_hours_breakdown(staff, hours_by_project)
        currency = contractor_config.get("currency", "NGN")
        
        if staff.contractor_type == "regional":
            local_rate = Decimal(str(cadre_config.get("regional_hourly_rate_usd", 0)))
            regional_rate = Decimal(str(cadre_config.get("regional_hourly_rate_usd", 0)))
            base_payment_amount = Decimal(str(cadre_config.get("base_payment_usd", 0)))
        else:
            local_rate = Decimal(str(cadre_config.get("local_hourly_rate", 0)))
            regional_rate = Decimal(str(cadre_config.get("regional_hourly_rate", 0)))
            base_payment_amount = Decimal(str(cadre_config.get("base_payment_ngn", 0)))
        
        payroll = PayrollBreakdown(
            staff=staff,
            hours=hours,
            period=period,
            currency=currency,
            local_hourly_rate=local_rate,
            regional_hourly_rate=regional_rate
        )
        
        if staff.contract_structure == "fixed_base":
            payroll.base_payment = base_payment_amount
            payroll.calculation_notes.append(f"Base: {payroll.base_payment} {currency}")

            # Principals: ALL billable hours count (base + extra), not just extra
            if staff.cadre == "principal":
                if hours.local_billable_hours > 0:
                    payroll.local_billable_fees = local_rate * Decimal(str(hours.local_billable_hours))

                if hours.regional_billable_hours > 0:
                    payroll.regional_billable_fees = regional_rate * Decimal(str(hours.regional_billable_hours))

                payroll.calculation_notes.append("Principal: All billable hours paid")
            else:
                # Other cadres: only extra hours above base threshold
                if hours.extra_local_billable_hours > 0:
                    payroll.local_billable_fees = local_rate * Decimal(str(hours.extra_local_billable_hours))

                if hours.extra_regional_billable_hours > 0:
                    payroll.regional_billable_fees = regional_rate * Decimal(str(hours.extra_regional_billable_hours))
        
        elif staff.contract_structure == "flexible":
            payroll.base_payment = Decimal("0")
            
            if hours.local_billable_hours > 0:
                payroll.local_billable_fees = local_rate * Decimal(str(hours.local_billable_hours))
            
            if hours.regional_billable_hours > 0:
                payroll.regional_billable_fees = regional_rate * Decimal(str(hours.regional_billable_hours))
        
        elif staff.contract_structure == "fixed":
            fixed_amt = Decimal(str(staff.fixed_amount)) if staff.fixed_amount else base_payment_amount
            payroll.base_payment = fixed_amt
        
        payroll.basic_compensation = payroll.base_payment + payroll.local_billable_fees + payroll.regional_billable_fees
        payroll.gross_compensation = payroll.basic_compensation
        
        wht_rate = Decimal(str(contractor_config.get("withholding_tax_rate", 0.05)))
        payroll.withholding_tax = (payroll.gross_compensation * wht_rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        
        payroll.hmo_deduction = Decimal(str(staff.hmo_deduction)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        payroll.total_deductions = payroll.withholding_tax + payroll.hmo_deduction
        payroll.net_compensation = payroll.gross_compensation - payroll.total_deductions
        
        return payroll
    
    def get_all_cadres(self) -> list:
        return list(self.cadres_config.get("cadres", {}).keys())
    
    def get_cadre_display_name(self, cadre: str) -> str:
        cadre_config = self.get_cadre_config(cadre)
        return cadre_config.get("display_name", cadre.replace("_", " ").title())
