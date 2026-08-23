
from .models import DashboardModel


class DashboardService:
    def get_dashboard(self, user_id: int) -> DashboardModel:
        return DashboardModel(total=42, active=10)
