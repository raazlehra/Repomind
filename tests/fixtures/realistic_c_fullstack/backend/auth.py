from .services import AuthService


def login_endpoint(username: str, password: str):
    svc = AuthService()
    return svc.login(username, password)
