UPDATE ohlcv_candles c
SET source = 'websocket_ohlc'
FROM (
    SELECT provider, symbol, epic, event_timestamp_utc
    FROM raw_market_events
    WHERE event_timestamp_utc IS NOT NULL
      AND lower(event_type) LIKE '%ohlc%'
    GROUP BY provider, symbol, epic, event_timestamp_utc
) e
WHERE c.provider = e.provider
  AND c.symbol = e.symbol
  AND c.epic = e.epic
  AND c.timestamp_utc = e.event_timestamp_utc
  AND c.source <> 'websocket_ohlc';
