from __future__ import annotations

from typing import Any

from .contracts import CheckoutSession, PaymentLineItem, PaymentStatus, Refund, WebhookEvent


def _value(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


class StripeProvider:
    name = "stripe"

    def __init__(self, secret_key: str, webhook_secret: str, stripe_module: Any | None = None) -> None:
        if not secret_key or not webhook_secret:
            raise ValueError("Stripe secret and webhook secret are required")
        if stripe_module is None:
            import stripe as stripe_module  # type: ignore[no-redef]
        self._stripe = stripe_module
        self._stripe.api_key = secret_key
        self._webhook_secret = webhook_secret

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
    ) -> CheckoutSession:
        params: dict[str, Any] = {
            "mode": "payment",
            "line_items": [
                {
                    "price_data": {
                        "currency": currency.lower(),
                        "product_data": {"name": item.description},
                        "unit_amount": item.unit_amount,
                    },
                    "quantity": item.quantity,
                }
                for item in line_items
            ],
            "success_url": success_url,
            "cancel_url": cancel_url,
            "metadata": metadata,
        }
        if customer_email:
            params["customer_email"] = customer_email
        if idempotency_key:
            # stripe-python extracts this SDK request option and sends it as an
            # Idempotency-Key header instead of a Checkout Session parameter.
            params["idempotency_key"] = idempotency_key
        session = self._stripe.checkout.Session.create(**params)
        return CheckoutSession(
            id=str(_value(session, "id")),
            url=_value(session, "url"),
            payment_id=_value(session, "payment_intent"),
            status=PaymentStatus.PENDING,
            raw=dict(session) if isinstance(session, dict) else {},
        )

    def retrieve_payment(self, provider_payment_id: str) -> PaymentStatus:
        intent = self._stripe.PaymentIntent.retrieve(provider_payment_id)
        return {
            "succeeded": PaymentStatus.PAID,
            "processing": PaymentStatus.PENDING,
            "requires_payment_method": PaymentStatus.PENDING,
            "requires_action": PaymentStatus.PENDING,
            "canceled": PaymentStatus.CANCELED,
        }.get(str(_value(intent, "status")), PaymentStatus.FAILED)

    def refund_payment(self, provider_payment_id: str, amount: int | None = None) -> Refund:
        params: dict[str, Any] = {"payment_intent": provider_payment_id}
        if amount is not None:
            params["amount"] = amount
        refund = self._stripe.Refund.create(**params)
        status = PaymentStatus.REFUNDED if _value(refund, "status") in {"succeeded", "pending"} else PaymentStatus.FAILED
        return Refund(id=str(_value(refund, "id")), payment_id=provider_payment_id, amount=int(_value(refund, "amount", amount or 0)), status=status, raw=dict(refund) if isinstance(refund, dict) else {})

    def verify_webhook(self, payload: bytes, signature: str) -> WebhookEvent:
        try:
            event = self._stripe.Webhook.construct_event(payload, signature, self._webhook_secret)
        except Exception as exc:
            raise ValueError("invalid Stripe webhook signature") from exc
        return WebhookEvent(id=str(_value(event, "id")), type=str(_value(event, "type")), data=dict(_value(event, "data", {})), raw=dict(event) if isinstance(event, dict) else {})
