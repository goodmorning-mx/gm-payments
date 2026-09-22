from __future__ import annotations

from fastapi.testclient import TestClient
from stripe._request_options import extract_options_from_dict

from gm_payments.api import create_app
from gm_payments.contracts import CheckoutSession, PaymentLineItem, PaymentStatus, Refund, WebhookEvent
from gm_payments.service import PaymentService
from gm_payments.stripe_provider import StripeProvider


class FakeProvider:
    name = "fake"

    def __init__(self):
        self.calls = []

    def create_checkout_session(self, **kwargs):
        self.calls.append(kwargs)
        return CheckoutSession("cs_test", "https://checkout.test", "pi_test")

    def retrieve_payment(self, provider_payment_id):
        return PaymentStatus.PAID

    def refund_payment(self, provider_payment_id, amount=None):
        return Refund("re_test", provider_payment_id, amount or 1000, PaymentStatus.REFUNDED)

    def verify_webhook(self, payload, signature):
        if signature != "valid":
            raise ValueError("invalid Stripe webhook signature")
        return WebhookEvent("evt_1", "payment_intent.succeeded", {"object": {"id": "pi_test"}})


def client():
    provider = FakeProvider()
    service = PaymentService(provider)
    return TestClient(create_app(service)), provider, service


def checkout_payload(**extra):
    value = {
        "line_items": [{"description": "CV review", "unit_amount": 1200, "quantity": 2}],
        "currency": "USD", "success_url": "https://app.test/success", "cancel_url": "https://app.test/cancel",
        "user_id": "user-1", "product_id": "cv-review", "order_id": "order-1", "idempotency_key": "idem-1",
    }
    value.update(extra)
    return value


def test_checkout_persists_associations_and_amount():
    app, provider, service = client()
    response = app.post("/payments/checkout", json=checkout_payload())
    assert response.status_code == 201
    payment = response.json()["payment"]
    assert payment["amount"] == 2400
    assert payment["metadata"] == {"product_id": "cv-review", "user_id": "user-1", "order_id": "order-1"}
    assert provider.calls[0]["metadata"]["user_id"] == "user-1"
    assert service.get_payment(payment["id"]).status == PaymentStatus.PENDING


def test_idempotency_does_not_create_second_payment():
    app, provider, service = client()
    first = app.post("/payments/checkout", json=checkout_payload()).json()
    second = app.post("/payments/checkout", json=checkout_payload()).json()
    assert first["payment"]["id"] == second["payment"]["id"]
    assert len(provider.calls) == 1
    assert len(service.store.payments) == 1


def test_webhook_signature_and_duplicate_are_handled():
    app, _, service = client()
    response = app.post("/payments/checkout", json=checkout_payload())
    payment_id = response.json()["payment"]["id"]
    assert app.post("/payments/webhooks/stripe", content=b"{}", headers={"Stripe-Signature": "bad"}).status_code == 400
    headers = {"Stripe-Signature": "valid"}
    assert app.post("/payments/webhooks/stripe", content=b"{}", headers=headers).json() == {"received": True, "processed": True}
    assert app.post("/payments/webhooks/stripe", content=b"{}", headers=headers).json() == {"received": True, "processed": False}
    assert service.get_payment(payment_id).status == PaymentStatus.PAID


def test_refund_requires_paid_payment_and_valid_amount():
    app, _, service = client()
    payment = app.post("/payments/checkout", json=checkout_payload()).json()["payment"]
    assert app.post(f"/payments/{payment['id']}/refund", json={}).status_code == 400
    service.get_payment(payment["id"]).status = PaymentStatus.PAID
    assert app.post(f"/payments/{payment['id']}/refund", json={"amount": 2400}).json()["status"] == "refunded"


def test_health_and_secret_not_exposed():
    app, _, _ = client()
    assert app.get("/health").json() == {"status": "ok"}
    assert "STRIPE_SECRET_KEY" not in app.get("/openapi.json").text


def test_invalid_amount_and_currency_are_rejected():
    app, _, _ = client()
    assert app.post("/payments/checkout", json=checkout_payload(currency="US", line_items=[{"description": "x", "unit_amount": 0}])).status_code == 422


def test_stripe_provider_uses_checkout_payment_mode_and_metadata():
    class Session:
        @staticmethod
        def create(**kwargs):
            Session.kwargs = kwargs
            return {"id": "cs_1", "url": "https://stripe.test", "payment_intent": "pi_1"}

    Checkout = type("Checkout", (), {"Session": Session})

    class FakeStripe:
        checkout = Checkout
        api_key = None

    provider = StripeProvider("sk_test_only", "whsec_test_only", stripe_module=FakeStripe)
    result = provider.create_checkout_session(
        line_items=[PaymentLineItem(description="x", unit_amount=100, quantity=1)],
        currency="USD", success_url="https://ok", cancel_url="https://cancel",
        customer_email=None, metadata={"product_id": "p", "user_id": "u"}, idempotency_key="checkout-idem-1",
    )
    assert result.id == "cs_1"
    assert Session.kwargs["mode"] == "payment"
    assert Session.kwargs["metadata"]["user_id"] == "u"
    assert Session.kwargs["idempotency_key"] == "checkout-idem-1"
    assert "options" not in Session.kwargs
    sdk_options, checkout_params = extract_options_from_dict(Session.kwargs)
    assert sdk_options["idempotency_key"] == "checkout-idem-1"
    assert "idempotency_key" not in checkout_params
