from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any, Protocol


class PaymentStatus(StrEnum):
    PENDING = "pending"
    PAID = "paid"
    FAILED = "failed"
    CANCELED = "canceled"
    REFUNDED = "refunded"


@dataclass(frozen=True)
class PaymentLineItem:
    description: str
    unit_amount: int
    quantity: int = 1

    def __post_init__(self) -> None:
        if not self.description.strip():
            raise ValueError("line item description is required")
        if self.unit_amount <= 0:
            raise ValueError("line item amount must be positive")
        if self.quantity <= 0:
            raise ValueError("line item quantity must be positive")


@dataclass
class CheckoutSession:
    id: str
    url: str | None
    payment_id: str | None
    status: PaymentStatus = PaymentStatus.PENDING
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class Payment:
    id: str
    provider: str
    provider_payment_id: str | None
    checkout_session_id: str | None
    user_id: str
    organization_id: str | None
    product_id: str
    order_id: str | None
    currency: str
    amount: int
    status: PaymentStatus
    metadata: dict[str, str]
    idempotency_key: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass
class Refund:
    id: str
    payment_id: str
    amount: int
    status: PaymentStatus
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class WebhookEvent:
    id: str
    type: str
    data: dict[str, Any]
    raw: dict[str, Any] = field(default_factory=dict)


class PaymentProvider(Protocol):
    name: str

    def create_checkout_session(
        self,
        *,
        line_items: list[PaymentLineItem],
        currency: str,
        success_url: str,
        cancel_url: str,
        customer_email: str | None,
        metadata: dict[str, str],
        idempotency_key: str | None,
    ) -> CheckoutSession: ...

    def retrieve_payment(self, provider_payment_id: str) -> PaymentStatus: ...

    def refund_payment(self, provider_payment_id: str, amount: int | None = None) -> Refund: ...

    def verify_webhook(self, payload: bytes, signature: str) -> WebhookEvent: ...
