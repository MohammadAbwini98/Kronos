CREATE TABLE IF NOT EXISTS live_quotes (
    provider TEXT NOT NULL DEFAULT 'Capital.com',
    symbol TEXT NOT NULL,
    epic TEXT NOT NULL,
    bid NUMERIC(20, 8),
    ask NUMERIC(20, 8),
    mid NUMERIC(20, 8),
    price NUMERIC(20, 8) NOT NULL,
    timestamp_utc TIMESTAMPTZ,
    source TEXT NOT NULL DEFAULT 'websocket_quote',
    raw_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY(provider, symbol, epic)
);

CREATE INDEX IF NOT EXISTS idx_live_quotes_symbol_updated
    ON live_quotes(symbol, updated_at DESC);
