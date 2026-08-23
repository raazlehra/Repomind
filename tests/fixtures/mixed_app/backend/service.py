from .models import Payment

class PaymentService:
    def process(self, payment: Payment) -> bool:
        return payment.validate()
