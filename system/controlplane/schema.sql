-- Reference DDL for ops review only. NOT executed by the control-plane: the
-- runtime schema is created by SQLAlchemy metadata.create_all (app/models.py)
-- when AUTO_MIGRATE=1. Keep this file in sync with app/models.py.
--
-- Parameter defaults are application-side (uuid4(), now() in Python, JSON
-- column defaults), so the columns below are declared without server defaults
-- except the timestamps that Postgres can supply.

CREATE TABLE users (
    id          BIGSERIAL PRIMARY KEY,
    subject     VARCHAR(255) NOT NULL UNIQUE,
    name        VARCHAR(255),
    email       VARCHAR(320),
    groups      JSONB NOT NULL DEFAULT '[]'::jsonb,
    is_admin    BOOLEAN NOT NULL DEFAULT false,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX ix_users_email ON users (email);

CREATE TABLE jobs (
    id           UUID PRIMARY KEY,                  -- job id == gallery directory name
    owner_id     BIGINT NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    template_id  VARCHAR(128) NOT NULL,
    params       JSONB NOT NULL DEFAULT '{}'::jsonb,
    status       VARCHAR(16) NOT NULL DEFAULT 'queued'
                 CHECK (status IN ('queued', 'running', 'success', 'failed', 'cancelled')),
    client_id    VARCHAR(64),
    counts       JSONB NOT NULL DEFAULT '{}'::jsonb,
    error        TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at   TIMESTAMPTZ,
    finished_at  TIMESTAMPTZ
);

CREATE INDEX ix_jobs_owner_id ON jobs (owner_id);
-- FIFO claim: SELECT ... WHERE status = 'queued' ORDER BY created_at LIMIT 1.
CREATE INDEX ix_jobs_status_created_at ON jobs (status, created_at);

CREATE TABLE gallery_media (
    id            BIGSERIAL PRIMARY KEY,
    job_id        UUID NOT NULL REFERENCES jobs (id) ON DELETE CASCADE,
    user_id       BIGINT NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    kind          VARCHAR(16) NOT NULL CHECK (kind IN ('image', 'video')),
    filename      VARCHAR(255) NOT NULL,
    size_bytes    BIGINT NOT NULL,
    content_type  VARCHAR(128) NOT NULL,
    sha256        VARCHAR(64) NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_gallery_media_job_filename UNIQUE (job_id, filename)
);

CREATE INDEX ix_gallery_media_job_id ON gallery_media (job_id);
CREATE INDEX ix_gallery_media_user_id ON gallery_media (user_id);

CREATE TABLE sessions (
    id          VARCHAR(64) PRIMARY KEY,              -- unguessable session id (bearer half of the cookie)
    user_id     BIGINT REFERENCES users (id) ON DELETE CASCADE,  -- NULL while an authorization code is pending
    csrf_token  VARCHAR(64),
    state       VARCHAR(128) UNIQUE,
    nonce       VARCHAR(128),
    expires_at  TIMESTAMPTZ NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX ix_sessions_user_id ON sessions (user_id);
