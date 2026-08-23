from backend.models import Payment
from backend.service import PaymentService

def test_payment() -> None:
    assert PaymentService().process(Payment())
