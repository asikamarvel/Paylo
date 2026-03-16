"""Harvest API client."""

import requests
from datetime import datetime, timedelta
import os


class HarvestClient:
    
    BASE_URL = "https://api.harvestapp.com/v2"
    
    def __init__(self, account_id: str = None, access_token: str = None):
        self.account_id = account_id or os.getenv("HARVEST_ACCOUNT_ID")
        self.access_token = access_token or os.getenv("HARVEST_ACCESS_TOKEN")
        
        if not self.account_id or not self.access_token:
            raise ValueError("Harvest credentials required. Set HARVEST_ACCOUNT_ID and HARVEST_ACCESS_TOKEN.")
        
        self.headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Harvest-Account-Id": self.account_id,
            "User-Agent": "Advanced Payroll",
            "Content-Type": "application/json"
        }
    
    def _make_request(self, endpoint: str, params: dict = None) -> dict:
        url = f"{self.BASE_URL}/{endpoint}"
        response = requests.get(url, headers=self.headers, params=params)
        response.raise_for_status()
        return response.json()
    
    def _paginate_all(self, endpoint: str, params: dict = None, key: str = None) -> list:
        params = params or {}
        all_results = []
        page = 1
        
        while True:
            params["page"] = page
            data = self._make_request(endpoint, params)
            
            if key is None:
                for k, v in data.items():
                    if isinstance(v, list):
                        key = k
                        break
            
            results = data.get(key, [])
            all_results.extend(results)
            
            if data.get("next_page") is None:
                break
            page += 1
        
        return all_results
    
    def get_users(self) -> list:
        return self._paginate_all("users", key="users")
    
    def get_user(self, user_id: int) -> dict:
        return self._make_request(f"users/{user_id}")
    
    def get_projects(self) -> list:
        return self._paginate_all("projects", key="projects")
    
    def get_project(self, project_id: int) -> dict:
        return self._make_request(f"projects/{project_id}")
    
    def get_time_entries(self, from_date: datetime = None, to_date: datetime = None, 
                         user_id: int = None, project_id: int = None) -> list:
        params = {}
        
        if from_date:
            params["from"] = from_date.strftime("%Y-%m-%d")
        if to_date:
            params["to"] = to_date.strftime("%Y-%m-%d")
        if user_id:
            params["user_id"] = user_id
        if project_id:
            params["project_id"] = project_id
        
        return self._paginate_all("time_entries", params=params, key="time_entries")
    
    def get_monthly_time_entries(self, year: int, month: int, user_id: int = None) -> list:
        from_date = datetime(year, month, 1)
        
        if month == 12:
            to_date = datetime(year + 1, 1, 1) - timedelta(days=1)
        else:
            to_date = datetime(year, month + 1, 1) - timedelta(days=1)
        
        return self.get_time_entries(from_date=from_date, to_date=to_date, user_id=user_id)
    
    def aggregate_hours_by_user(self, time_entries: list, projects: list = None) -> dict:
        project_map = {}
        if projects:
            for p in projects:
                project_map[p["id"]] = p
        
        user_hours = {}
        
        for entry in time_entries:
            user_name = entry.get("user", {}).get("name", "Unknown")
            project_name = entry.get("project", {}).get("name", "Unknown")
            hours = float(entry.get("hours", 0))
            
            if user_name not in user_hours:
                user_hours[user_name] = {"total": 0, "billable": 0, "non_billable": 0, "by_project": {}}
            
            user_hours[user_name]["total"] += hours
            
            if entry.get("billable", False):
                user_hours[user_name]["billable"] += hours
            else:
                user_hours[user_name]["non_billable"] += hours
            
            if project_name not in user_hours[user_name]["by_project"]:
                user_hours[user_name]["by_project"][project_name] = 0
            user_hours[user_name]["by_project"][project_name] += hours
        
        return user_hours


class MockHarvestClient:
    
    def __init__(self):
        self.mock_users = [
            {"id": 1, "first_name": "John", "last_name": "Doe", "email": "john@example.com"},
            {"id": 2, "first_name": "Jane", "last_name": "Smith", "email": "jane@example.com"},
        ]
        
        self.mock_projects = [
            {"id": 1, "name": "Project Alpha", "is_billable": True},
            {"id": 2, "name": "Internal Operations", "is_billable": False},
        ]
    
    def get_users(self) -> list:
        return self.mock_users
    
    def get_projects(self) -> list:
        return self.mock_projects
    
    def get_monthly_time_entries(self, year: int, month: int, user_id: int = None) -> list:
        return [
            {"user": {"id": 1, "name": "John Doe"}, "project": {"id": 1, "name": "Project Alpha"}, 
             "hours": 40, "billable": True},
            {"user": {"id": 1, "name": "John Doe"}, "project": {"id": 2, "name": "Internal Operations"}, 
             "hours": 20, "billable": False},
            {"user": {"id": 2, "name": "Jane Smith"}, "project": {"id": 1, "name": "Project Alpha"}, 
             "hours": 35, "billable": True},
        ]
    
    def aggregate_hours_by_user(self, time_entries: list, projects: list = None) -> dict:
        user_hours = {}
        
        for entry in time_entries:
            user_name = entry.get("user", {}).get("name", "Unknown")
            project_name = entry.get("project", {}).get("name", "Unknown")
            hours = float(entry.get("hours", 0))
            
            if user_name not in user_hours:
                user_hours[user_name] = {"total": 0, "billable": 0, "non_billable": 0, "by_project": {}}
            
            user_hours[user_name]["total"] += hours
            
            if entry.get("billable", False):
                user_hours[user_name]["billable"] += hours
            else:
                user_hours[user_name]["non_billable"] += hours
            
            if project_name not in user_hours[user_name]["by_project"]:
                user_hours[user_name]["by_project"][project_name] = 0
            user_hours[user_name]["by_project"][project_name] += hours
        
        return user_hours


def get_harvest_client(use_mock: bool = False, **kwargs):
    if use_mock:
        return MockHarvestClient()
    return HarvestClient(**kwargs)
