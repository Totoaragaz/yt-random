CREATE TABLE IF NOT EXISTS videos (
    serial_id          SERIAL PRIMARY KEY,
    id                 TEXT UNIQUE NOT NULL,
    title              TEXT,
    channel_id         TEXT,
    category_id        INTEGER,
    language           TEXT,
    duration_seconds   INTEGER,
    view_count         BIGINT,
    discovered_via     TEXT REFERENCES videos(id) ON DELETE SET NULL,
    search_term        TEXT,
    search_date_window TEXT,
    collected_at       TIMESTAMPTZ DEFAULT now()
);
