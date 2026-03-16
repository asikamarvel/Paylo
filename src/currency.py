"""Currency conversion utilities."""

import requests
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
import yaml
from pathlib import Path


class CurrencyConverter:

    def __init__(self, config_dir: str = None, cache_duration_hours: int = 24):
        self.cache_duration = timedelta(hours=cache_duration_hours)
        self._rate_cache = {}
        self._cache_timestamp = None
        self.fallback_rate = 1550.00
        self._manual_rate = None
        self.config_dir = config_dir

        if config_dir:
            self._load_fallback_rate(config_dir)
            self._load_manual_rate(config_dir)

    def _load_manual_rate(self, config_dir: str):
        """Load manual rate from settings if configured."""
        try:
            config_path = Path(config_dir) / "settings.yaml"
            if config_path.exists():
                with open(config_path, "r") as f:
                    settings = yaml.safe_load(f) or {}
                if settings.get("exchange_rate_mode") == "manual":
                    self._manual_rate = settings.get("manual_exchange_rate")
        except Exception:
            pass

    def set_manual_rate(self, rate: float):
        """Set a manual exchange rate override."""
        self._manual_rate = rate

    def clear_manual_rate(self):
        """Clear manual rate and use auto-fetch."""
        self._manual_rate = None
        self._rate_cache = {}
        self._cache_timestamp = None

    def _load_fallback_rate(self, config_dir: str):
        try:
            config_path = Path(config_dir) / "deductions.yaml"
            with open(config_path, "r") as f:
                config = yaml.safe_load(f)
            self.fallback_rate = config.get("currency", {}).get("fallback_rate", 1550.00)
        except Exception:
            pass

    def _is_cache_valid(self) -> bool:
        if not self._cache_timestamp:
            return False
        return datetime.now() - self._cache_timestamp < self.cache_duration

    def get_exchange_rate(self, from_currency: str = "NGN", to_currency: str = "USD") -> float:
        # If manual rate is set, use it
        if self._manual_rate is not None:
            return self._manual_rate

        cache_key = f"{from_currency}_{to_currency}"

        if self._is_cache_valid() and cache_key in self._rate_cache:
            return self._rate_cache[cache_key]

        try:
            rate = self._fetch_free_rate(from_currency, to_currency)
            self._rate_cache[cache_key] = rate
            self._cache_timestamp = datetime.now()
            return rate
        except Exception:
            pass

        return self.fallback_rate

    def is_manual_mode(self) -> bool:
        """Check if using manual exchange rate."""
        return self._manual_rate is not None

    def _fetch_free_rate(self, from_currency: str, to_currency: str) -> float:
        """Try multiple free exchange rate APIs."""
        # Try exchangerate-api.com (free tier)
        try:
            url = f"https://api.exchangerate-api.com/v4/latest/{to_currency}"
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            data = response.json()
            if "rates" in data and from_currency in data["rates"]:
                return float(data["rates"][from_currency])
        except Exception:
            pass

        # Try frankfurter.app (free, no key needed)
        try:
            url = f"https://api.frankfurter.app/latest?from={to_currency}&to={from_currency}"
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            data = response.json()
            if "rates" in data and from_currency in data["rates"]:
                return float(data["rates"][from_currency])
        except Exception:
            pass

        raise ValueError("All free APIs failed")
    
    def convert(self, amount: Decimal, from_currency: str = "NGN", to_currency: str = "USD", rate: float = None) -> Decimal:
        if rate is None:
            rate = self.get_exchange_rate(from_currency, to_currency)
        
        converted = amount / Decimal(str(rate))
        return converted.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    
    def format_currency(self, amount: Decimal, currency: str, include_symbol: bool = True) -> str:
        symbols = {"NGN": "₦", "USD": "$", "EUR": "€", "GBP": "£"}
        symbol = symbols.get(currency, currency + " ")
        formatted = f"{amount:,.2f}"
        return f"{symbol}{formatted}" if include_symbol else formatted


class MockCurrencyConverter:
    
    def __init__(self, fixed_rate: float = 1550.00):
        self.fixed_rate = fixed_rate
    
    def get_exchange_rate(self, from_currency: str = "NGN", to_currency: str = "USD") -> float:
        return self.fixed_rate
    
    def convert(self, amount: Decimal, from_currency: str = "NGN", to_currency: str = "USD", rate: float = None) -> Decimal:
        rate = rate or self.fixed_rate
        converted = amount / Decimal(str(rate))
        return converted.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    
    def format_currency(self, amount: Decimal, currency: str, include_symbol: bool = True) -> str:
        symbols = {"NGN": "₦", "USD": "$", "EUR": "€", "GBP": "£"}
        symbol = symbols.get(currency, currency + " ")
        formatted = f"{amount:,.2f}"
        return f"{symbol}{formatted}" if include_symbol else formatted


def get_currency_converter(use_mock: bool = False, config_dir: str = None):
    if use_mock:
        return MockCurrencyConverter()
    return CurrencyConverter(config_dir=config_dir)
