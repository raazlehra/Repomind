from app.auth import AuthService
from app.email import EmailService
from app.models import User

def test_login() -> None:
    service = AuthService(EmailService())
    assert service.login(User("a@example.com", "hash"), "secret")
