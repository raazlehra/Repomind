
from .services import DashboardService


def dashboard_endpoint(user_id: int):
    svc = DashboardService()
    return svc.get_dashboard(user_id)
