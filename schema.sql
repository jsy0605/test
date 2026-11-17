CREATE TABLE IF NOT EXISTS Art (
    artwork_id TEXT NOT NULL PRIMARY KEY CHECK (artwork_id GLOB '[0-9][0-9][0-9]'),
    artwork_title TEXT NOT NULL DEFAULT '',
    artist TEXT NOT NULL DEFAULT '',
    location TEXT NOT NULL,
    theme TEXT NOT NULL,
    description TEXT NOT NULL,
    x REAL,
    y REAL,
    artwork_index INTEGER NOT NULL UNIQUE CHECK (artwork_index BETWEEN 1 AND 999),
    artist_name TEXT NOT NULL,
    title TEXT NOT NULL,
    artwork_code TEXT NOT NULL DEFAULT '',
    image_path TEXT NOT NULL DEFAULT '',
    image_alt TEXT NOT NULL DEFAULT '',
    CHECK (artwork_id = printf('%03d', artwork_index)),
    CHECK (length(trim(location)) BETWEEN 1 AND 64),
    CHECK (x IS NULL OR x BETWEEN -1e12 AND 1e12),
    CHECK (y IS NULL OR y BETWEEN -1e12 AND 1e12)
);

CREATE TABLE IF NOT EXISTS Pose (
    robot_id TEXT NOT NULL PRIMARY KEY,
    x REAL,
    y REAL,
    theta REAL,
    active INTEGER NOT NULL CHECK (active IN (0, 1)),
    frame_id TEXT NOT NULL DEFAULT 'map',
    pose_updated_at INTEGER,
    CHECK (
        (x IS NULL AND y IS NULL AND theta IS NULL AND pose_updated_at IS NULL)
        OR (x IS NOT NULL AND y IS NOT NULL AND theta IS NOT NULL AND pose_updated_at IS NOT NULL)
    )
);

CREATE TABLE IF NOT EXISTS courses (
    id TEXT PRIMARY KEY,
    data TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS catalog_migrations (
    version TEXT PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS admin_users (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    auth_version INTEGER NOT NULL DEFAULT 1,
    created_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS admin_login_attempts (
    client_address TEXT PRIMARY KEY,
    failures INTEGER NOT NULL,
    window_started REAL NOT NULL,
    blocked_until REAL NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS admin_sessions (
    token_hash TEXT PRIMARY KEY,
    admin_id INTEGER NOT NULL REFERENCES admin_users(id),
    expires_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS TourSession (
    created_time INTEGER NOT NULL,
    mode TEXT NOT NULL CHECK (mode IN ('course', 'free')),
    route TEXT,
    status TEXT NOT NULL CHECK (status IN ('calling', 'active', 'completed', 'cancelled')),
    end_time INTEGER,
    record_id TEXT NOT NULL PRIMARY KEY,
    artwork_ids TEXT NOT NULL,
    visited_ids TEXT NOT NULL DEFAULT '[]',
    started_at INTEGER,
    robot_id TEXT,
    robot_namespace TEXT,
    visitor_id TEXT
);

CREATE INDEX IF NOT EXISTS tour_session_created_time ON TourSession (created_time DESC, record_id DESC);

CREATE TABLE IF NOT EXISTS Log (
    log_id INTEGER PRIMARY KEY AUTOINCREMENT,
    robot_id TEXT NOT NULL CHECK (length(robot_id) BETWEEN 1 AND 64),
    sent_at INTEGER NOT NULL CHECK (sent_at BETWEEN 0 AND 253402300799999),
    message TEXT NOT NULL CHECK (length(trim(message)) BETWEEN 1 AND 10000)
);

CREATE INDEX IF NOT EXISTS robot_log_sent_at ON Log (sent_at DESC, log_id DESC);
