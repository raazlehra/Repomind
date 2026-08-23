from .models import User


class UserRepository:
    def __init__(self) -> None:
        # simple in-memory placeholder
        self._data = {"alice": {"id": 1, "username": "alice", "password": "pw"}}

    def find_by_username(self, username: str) -> dict | None:
        return self._data.get(username)
