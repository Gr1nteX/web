CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    is_admin BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE TABLE sessions (
    token TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TIMESTAMP NOT NULL DEFAULT now()
);

CREATE TABLE tasks (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    n INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued',
    progress INTEGER NOT NULL DEFAULT 0,
    result TEXT,
    error TEXT,
    worker TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT now(),
    started_at TIMESTAMP,
    finished_at TIMESTAMP
);

CREATE TABLE workers (
    name TEXT PRIMARY KEY,
    task_id INTEGER,
    last_seen TIMESTAMP NOT NULL DEFAULT now()
);

CREATE TABLE servers (
    name TEXT PRIMARY KEY,
    requests INTEGER NOT NULL DEFAULT 0,
    last_seen TIMESTAMP NOT NULL DEFAULT now()
);

INSERT INTO users (username, password_hash, is_admin)
VALUES ('admin', 'admin$86bf42eb184c2fb8dc846efb5790ee80fc244cb7ca9a4bd1dbfd35e7d7b8fd3c', TRUE);
