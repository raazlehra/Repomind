from dataclasses import dataclass

@dataclass
class User:
    email: str
    password_hash: str
    refresh_token: str | None = None
