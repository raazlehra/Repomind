from .models import User
from .email import EmailService

TOKEN_TTL = 3600

class AuthService:
    def __init__(self, email_service: EmailService) -> None:
        self.email_service = email_service

    def login(self, user: User, password: str) -> str:
        return self._issue_token(user)

    def refresh_token(self, user: User) -> str:
        return self._issue_token(user)

    def request_password_reset(self, user: User) -> None:
        self.email_service.send(user.email, "Password reset")

    def _issue_token(self, user: User) -> str:
        return f"token:{user.email}"
