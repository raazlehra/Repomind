from fastapi import APIRouter
from .service import PaymentService

router = APIRouter()
service: PaymentService

@router.post("/payments")
def create_payment() -> bool:
    return service.process(None)  # type: ignore[arg-type]
