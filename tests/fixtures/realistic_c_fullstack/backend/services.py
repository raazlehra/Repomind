from .models import DashboardModel


class DashboardService:
    def get_dashboard(self, user_id: int) -> DashboardModel:
        # In a real app this would query DB and assemble the response
        return DashboardModel(total=42, active=10)


class AuthService:
    def login(self, username: str, password: str) -> dict:
        return {"user": username}
