from .repository import UserRepository


class AuthService:
    def __init__(self) -> None:
        self.repo = UserRepository()

    def login(self, username: str, password: str) -> dict:
        user = self.repo.find_by_username(username)
        if not user or user.get("password") != password:
            return {"success": False}
        return {"success": True, "user_id": user.get("id")}
