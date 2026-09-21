from __future__ import annotations

import os
from typing import Annotated

from fastapi import APIRouter, FastAPI, Header, HTTPException, Request, status
from pydantic import BaseModel, Field

from .contracts import PaymentLineItem, PaymentStatus
from .service import PaymentService
from .stripe_provider import StripeProvider


class LineItemInput(BaseModel):
    description: str = Field(min_length=1)
    unit_amount: int = Field(gt=0)
    quantity: int = Field(default=1, gt=0)


class CheckoutInput(BaseModel):
    line_items: list[LineItemInput] = Field(min_length=1)
    currency: str = Field(min_length=3, max_length=3)
    success_url: str
    cancel_url: str
    user_id: str = Field(min_length=1)
    product_id: str = Field(min_length=1)
    organization_id: str | None = None
    order_id: str | None = None
    customer_email: str | None = None
    idempotency_key: str | None = None


class RefundInput(BaseModel):
    amount: int | None = Field(default=None, gt=0)


def _payment_payload(payment) -> dict:
    return {
        "id": payment.id,
        "provider": payment.provider,
        "provider_payment_id": payment.provider_payment_id,
        "checkout_session_id": payment.checkout_session_id,
        "user_id": payment.user_id,
        "organization_id": payment.organization_id,
        "product_id": payment.product_id,
        "order_id": payment.order_id,
        "currency": payment.currency,
        "amount": payment.amount,
        "status": payment.status,
        "metadata": payment.metadata,
    }


def create_app(service: PaymentService | None = None) -> FastAPI:
    if service is None:
        if os.getenv("PAYMENT_PROVIDER", "stripe") != "stripe":
            raise RuntimeError("unsupported payment provider")
        service = PaymentService(StripeProvider(os.environ["STRIPE_SECRET_KEY"], os.environ["STRIPE_WEBHOOK_SECRET"]))
    app = FastAPI(title="gm-payments")
    router = APIRouter(prefix="/payments")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @router.post("/checkout", status_code=status.HTTP_201_CREATED)
    def checkout(payload: CheckoutInput):
        try:
            payment, session = service.create_checkout(
                line_items=[PaymentLineItem(**item.model_dump()) for item in payload.line_items],
                **payload.model_dump(exclude={"line_items"}),
            )
        except (ValueError, KeyError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"payment": _payment_payload(payment), "checkout_session": {"id": session.id, "url": session.url}}

    @router.get("/{payment_id}")
    def get_payment(payment_id: str):
        try:
            return _payment_payload(service.get_payment(payment_id))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="payment not found") from exc

    @router.post("/{payment_id}/refund")
    def refund(payment_id: str, payload: RefundInput):
        try:
            value = service.refund(payment_id, payload.amount)
            return {"id": value.id, "payment_id": value.payment_id, "amount": value.amount, "status": value.status}
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="payment not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/webhooks/stripe")
    async def stripe_webhook(request: Request, stripe_signature: Annotated[str | None, Header(alias="Stripe-Signature")] = None):
        if not stripe_signature:
            raise HTTPException(status_code=400, detail="Stripe-Signature header is required")
        try:
            event = service.provider.verify_webhook(await request.body(), stripe_signature)
            processed = service.process_webhook(event)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"received": True, "processed": processed}

    app.include_router(router)
    return app
