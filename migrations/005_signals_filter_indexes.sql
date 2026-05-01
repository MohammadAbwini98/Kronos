CREATE INDEX IF NOT EXISTS idx_signals_symbol_resolution_time_desc
    ON signals(symbol, resolution, timestamp_utc DESC);

CREATE INDEX IF NOT EXISTS idx_signals_symbol_signal_time_desc
    ON signals(symbol, signal, timestamp_utc DESC);

CREATE INDEX IF NOT EXISTS idx_signals_symbol_status_time_desc
    ON signals(symbol, status, timestamp_utc DESC);
