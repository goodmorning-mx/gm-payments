from __future__ import annotations

from datetime import UTC, datetime
from threading import RLock
from uuid import uuid4

from .contracts import CheckoutSession, Payment, PaymentLineItem, PaymentProvider, PaymentStatus, Refund, WebhookEvent


class InMemoryPaymentStore:
    def __init__(self) -> None:
        self.payments: dict[str, Payment] = {}
        self.events: set[str] = set()
        self._lock = RLock()

    def find_by_idempotency_key(self, key: str) -> Payment | None:
        return next((p for p in self.payments.values() if p.idempotency_key == key), None)

    def save(self, payment: Payment) -> Payment:
        with self._lock:
            self.payments[payment.id] = payment
        return payment

    def get(self, payment_id: str) -> Payment | None:
        return self.payments.get(payment_id)

    def mark_event(self, event_id: str) -> bool:
        with self._lock:
            if event_id in self.events:
                return False
            self.events.add(event_id)
            return True


class PaymentService:
    def __init__(self, provider: PaymentProvider, store: InMemoryPaymentStore | None = None) -> None:
        self.provider = provider
        self.store = store or InMemoryPaymentStore()

    def create_checkout(
        self,
        *,
        line_items: list[PaymentLineItem],
        currency: str,
        success_url: str,
        cancel_url: str,
        user_id: str,
        product_id: str,
        organization_id: str | None = None,
        order_id: str | None = None,
        customer_email: str | None = None,
        idempotency_key: str | None = None,
    ) -> tuple[Payment, CheckoutSession]:
        if not line_items:
            raise ValueError("at least one line item is required")
        currency = currency.lower()
        if len(currency) != 3 or not currency.isalpha():
            raise ValueError("currency must be a three-letter code")
        if idempotency_key and (existing := self.store.find_by_idempotency_key(idempotency_key)):
            return existing, CheckoutSession(existing.checkout_session_id or "", None, existing.provider_payment_id)
        metadata = {"product_id": product_id, "user_id": user_id}
        if organization_id:
            metadata["organization_id"] = organization_id
        if order_id:
            metadata["order_id"] = order_id
        session = self.provider.create_checkout_session(
            line_items=line_items,
            currency=currency,
            success_url=success_url,
            cancel_url=cancel_url,
            customer_email=customer_email,
            metadata=metadata,
            idempotency_key=idempotency_key,
        )
        now = datetime.now(UTC)
        payment = Payment(
            id=str(uuid4()), provider=self.provider.name, provider_payment_id=session.payment_id,
            checkout_session_id=session.id, user_id=user_id, organization_id=organization_id,
            product_id=product_id, order_id=order_id, currency=currency,
            amount=sum(item.unit_amount * item.quantity for item in line_items),
            status=PaymentStatus.PENDING, metadata=metadata, idempotency_key=idempotency_key,
            created_at=now, updated_at=now,
        )
        return self.store.save(payment), session

    def get_payment(self, payment_id: str) -> Payment:
        payment = self.store.get(payment_id)
        if not payment:
            raise KeyError(payment_id)
        return payment

    def refund(self, payment_id: str, amount: int | None = None) -> Refund:
        payment = self.get_payment(payment_id)
        if payment.status not in {PaymentStatus.PAID, PaymentStatus.REFUNDED}:
            raise ValueError("only paid payments can be refunded")
        if amount is not None and (amount <= 0 or amount > payment.amount):
            raise ValueError("refund amount must be positive and not exceed the payment")
        if not payment.provider_payment_id:
            raise ValueError("payment has no provider payment id")
        refund = self.provider.refund_payment(payment.provider_payment_id, amount)
        if refund.status == PaymentStatus.REFUNDED:
            payment.status = PaymentStatus.REFUNDED
            payment.updated_at = datetime.now(UTC)
            self.store.save(payment)
        return refund

    def process_webhook(self, event: WebhookEvent) -> bool:
        if not self.store.mark_event(event.id):
            return False
        object_data = event.data.get("object", event.data)
        provider_payment_id = object_data.get("payment_intent") or object_data.get("id")
        payment = next((p for p in self.store.payments.values() if p.provider_payment_id == provider_payment_id or p.checkout_session_id == object_data.get("id")), None)
        if payment:
            mapping = {
                "checkout.session.completed": PaymentStatus.PAID,
                "payment_intent.succeeded": PaymentStatus.PAID,
                "payment_intent.payment_failed": PaymentStatus.FAILED,
                "checkout.session.expired": PaymentStatus.CANCELED,
                "charge.refunded": PaymentStatus.REFUNDED,
            }
            if event.type in mapping:
                payment.status = mapping[event.type]
                payment.updated_at = datetime.now(UTC)
                self.store.save(payment)
        return True
