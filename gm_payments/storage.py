from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, BigInteger, DateTime, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from .contracts import Payment


class Base(DeclarativeBase):
    pass


class PaymentRecord(Base):
    __tablename__ = "payments"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    provider: Mapped[str] = mapped_column(String(32))
    provider_payment_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    checkout_session_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    user_id: Mapped[str] = mapped_column(String(255))
    organization_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    product_id: Mapped[str] = mapped_column(String(255))
    order_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    currency: Mapped[str] = mapped_column(String(3))
    amount: Mapped[int] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(16))
    payment_metadata: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict)
    idempotency_key: Mapped[str | None] = mapped_column(String(255), nullable=True, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


class PaymentEventRecord(Base):
    __tablename__ = "payment_events"
    __table_args__ = (UniqueConstraint("provider", "provider_event_id"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    provider: Mapped[str] = mapped_column(String(32))
    provider_event_id: Mapped[str] = mapped_column(String(255))
    event_type: Mapped[str] = mapped_column(String(255))
    payment_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    processed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


class SQLAlchemyPaymentStore:
    """Persistence adapter; handlers and providers never access PostgreSQL directly."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def find_by_idempotency_key(self, key: str) -> Payment | None:
        record = self.session.query(PaymentRecord).filter_by(idempotency_key=key).one_or_none()
        return self._to_payment(record) if record else None

    def save(self, payment: Payment) -> Payment:
        record = self.session.get(PaymentRecord, payment.id) or PaymentRecord(id=payment.id)
        record.provider = payment.provider
        record.provider_payment_id = payment.provider_payment_id
        record.checkout_session_id = payment.checkout_session_id
        record.user_id = payment.user_id
        record.organization_id = payment.organization_id
        record.product_id = payment.product_id
        record.order_id = payment.order_id
        record.currency = payment.currency
        record.amount = payment.amount
        record.status = payment.status.value
        record.payment_metadata = payment.metadata
        record.idempotency_key = payment.idempotency_key
        record.created_at = payment.created_at or datetime.now(UTC)
        record.updated_at = payment.updated_at or datetime.now(UTC)
        self.session.add(record)
        self.session.commit()
        return payment

    def get(self, payment_id: str) -> Payment | None:
        record = self.session.get(PaymentRecord, payment_id)
        return self._to_payment(record) if record else None

    def mark_event(self, event_id: str) -> bool:
        if self.session.query(PaymentEventRecord).filter_by(provider_event_id=event_id).one_or_none():
            return False
        self.session.add(PaymentEventRecord(id=str(uuid4()), provider="stripe", provider_event_id=event_id, event_type="unknown", payload={}))
        self.session.commit()
        return True

    @staticmethod
    def _to_payment(record: PaymentRecord) -> Payment:
        from .contracts import PaymentStatus

        return Payment(
            id=record.id, provider=record.provider, provider_payment_id=record.provider_payment_id,
            checkout_session_id=record.checkout_session_id, user_id=record.user_id,
            organization_id=record.organization_id, product_id=record.product_id, order_id=record.order_id,
            currency=record.currency, amount=record.amount, status=PaymentStatus(record.status),
            metadata=record.payment_metadata or {}, idempotency_key=record.idempotency_key,
            created_at=record.created_at, updated_at=record.updated_at,
        )
