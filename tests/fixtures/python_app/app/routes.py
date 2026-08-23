from fastapi import APIRouter
from .auth import AuthService

router = APIRouter()
auth_service: AuthService

@router.post("/login")
def login(email: str, password: str) -> str:
    return auth_service.login(email, password)  # type: ignore[arg-type]

@router.post("/refresh")
def refresh(email: str) -> str:
    return auth_service.refresh_token(email)  # type: ignore[arg-type]
