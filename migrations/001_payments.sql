CREATE TABLE IF NOT EXISTS payments (
    id UUID PRIMARY KEY,
    provider TEXT NOT NULL,
    provider_payment_id TEXT,
    checkout_session_id TEXT,
    user_id TEXT NOT NULL,
    organization_id TEXT,
    product_id TEXT NOT NULL,
    order_id TEXT,
    currency CHAR(3) NOT NULL,
    amount BIGINT NOT NULL CHECK (amount > 0),
    status TEXT NOT NULL CHECK (status IN ('pending', 'paid', 'failed', 'canceled', 'refunded')),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    idempotency_key TEXT UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS payments_provider_payment_id_key
    ON payments (provider, provider_payment_id)
    WHERE provider_payment_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS payment_events (
    id UUID PRIMARY KEY,
    provider TEXT NOT NULL,
    provider_event_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    payment_id UUID REFERENCES payments(id),
    payload JSONB NOT NULL,
    processed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (provider, provider_event_id)
);
