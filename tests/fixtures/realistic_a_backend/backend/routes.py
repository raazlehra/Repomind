from fastapi import APIRouter, Depends
from .services import AuthService

router = APIRouter(prefix="/auth")


@router.post("/login")
def login(username: str, password: str):
    service = AuthService()
    return service.login(username, password)
