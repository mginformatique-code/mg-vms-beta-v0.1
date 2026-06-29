-- ====================================================================
-- MG-VMS — Schéma PostgreSQL (PRODUCTION)
-- Optimisé pour plusieurs millions d'événements et centaines de millions
-- de lectures ANPR. Index ciblés + partitionnement temporel recommandé.
-- ⚠️ Artefact de production — non utilisé par le backend de dev (MongoDB).
-- ====================================================================

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";   -- recherche plaque rapide (LIKE/regex)

-- -------------------- RBAC --------------------
CREATE TABLE roles (
    id          SMALLINT PRIMARY KEY,
    code        VARCHAR(20) UNIQUE NOT NULL,     -- admin/technician/client/readonly/guest
    level       SMALLINT NOT NULL
);

CREATE TABLE permissions (
    id          SERIAL PRIMARY KEY,
    code        VARCHAR(64) UNIQUE NOT NULL
);

CREATE TABLE role_permissions (
    role_id     SMALLINT REFERENCES roles(id) ON DELETE CASCADE,
    perm_id     INTEGER REFERENCES permissions(id) ON DELETE CASCADE,
    PRIMARY KEY (role_id, perm_id)
);

-- -------------------- Sites & utilisateurs --------------------
CREATE TABLE sites (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name        VARCHAR(160) NOT NULL,
    type        VARCHAR(60)  NOT NULL,
    address     TEXT,
    lat         DOUBLE PRECISION,
    lng         DOUBLE PRECISION,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE users (
    id            UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    email         CITEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    name          VARCHAR(160) NOT NULL,
    role_id       SMALLINT NOT NULL REFERENCES roles(id),
    twofa_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    twofa_secret  TEXT,
    active        BOOLEAN NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE user_sites (   -- cloisonnement multi-site
    user_id     UUID REFERENCES users(id) ON DELETE CASCADE,
    site_id     UUID REFERENCES sites(id) ON DELETE CASCADE,
    PRIMARY KEY (user_id, site_id)
);

CREATE TABLE groups (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name        VARCHAR(120) NOT NULL,
    site_id     UUID REFERENCES sites(id) ON DELETE CASCADE
);

-- -------------------- Caméras --------------------
CREATE TABLE cameras (
    id            UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    site_id       UUID NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
    name          VARCHAR(120) NOT NULL,
    ip            INET,
    port          INTEGER DEFAULT 554,
    protocol      VARCHAR(10) DEFAULT 'RTSP',     -- RTSP/ONVIF/HTTP/HTTPS
    codec         VARCHAR(10) DEFAULT 'H264',     -- H264/H265/MJPEG
    rtsp_url      TEXT,
    model         VARCHAR(120),
    username      VARCHAR(120),
    password_enc  TEXT,
    ptz_enabled   BOOLEAN DEFAULT FALSE,
    lat           DOUBLE PRECISION,
    lng           DOUBLE PRECISION,
    status        VARCHAR(12) DEFAULT 'offline',  -- online/offline
    last_seen     TIMESTAMPTZ,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_cameras_site   ON cameras(site_id);
CREATE INDEX idx_cameras_status ON cameras(status);

-- -------------------- Événements IA (partitionné par mois) --------------------
CREATE TABLE events (
    id          UUID NOT NULL DEFAULT uuid_generate_v4(),
    camera_id   UUID NOT NULL,
    site_id     UUID NOT NULL,
    type        VARCHAR(40) NOT NULL,          -- person/car/fire/intrusion...
    confidence  REAL,
    thumbnail   TEXT,
    ts          TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (id, ts)
) PARTITION BY RANGE (ts);
CREATE INDEX idx_events_ts     ON events(ts DESC);
CREATE INDEX idx_events_site   ON events(site_id, ts DESC);
CREATE INDEX idx_events_type   ON events(type, ts DESC);
-- Exemple de partition mensuelle (à automatiser via pg_partman) :
-- CREATE TABLE events_2026_06 PARTITION OF events FOR VALUES FROM ('2026-06-01') TO ('2026-07-01');

-- -------------------- ANPR (très gros volume, partitionné) --------------------
CREATE TABLE plates (
    id            UUID NOT NULL DEFAULT uuid_generate_v4(),
    plate         VARCHAR(16) NOT NULL,
    camera_id     UUID NOT NULL,
    site_id       UUID NOT NULL,
    confidence    REAL,
    country       VARCHAR(4),
    vehicle_color VARCHAR(24),
    vehicle_make  VARCHAR(40),
    vehicle_model VARCHAR(60),
    vehicle_type  VARCHAR(24),
    direction     VARCHAR(16),
    lat           DOUBLE PRECISION,
    lng           DOUBLE PRECISION,
    list_status   VARCHAR(8) DEFAULT 'none',   -- none/white/black
    image_url     TEXT,
    vehicle_crop  TEXT,
    plate_crop    TEXT,
    ts            TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (id, ts)
) PARTITION BY RANGE (ts);
CREATE INDEX idx_plates_plate ON plates USING gin (plate gin_trgm_ops);  -- recherche partielle ultra-rapide
CREATE INDEX idx_plates_ts    ON plates(ts DESC);
CREATE INDEX idx_plates_site  ON plates(site_id, ts DESC);
CREATE INDEX idx_plates_attrs ON plates(vehicle_make, vehicle_color, vehicle_type);

CREATE TABLE watchlist (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    plate       VARCHAR(16) UNIQUE NOT NULL,
    list_type   VARCHAR(8) NOT NULL,           -- white/black
    reason      TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- -------------------- Alertes / Audit / Logs --------------------
CREATE TABLE alerts (
    id            UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    type          VARCHAR(40),
    severity      VARCHAR(12),                 -- critical/warning/info
    message       TEXT NOT NULL,
    camera_id     UUID,
    site_id       UUID,
    acknowledged  BOOLEAN DEFAULT FALSE,
    ts            TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_alerts_ack ON alerts(acknowledged, ts DESC);

CREATE TABLE audit_logs (
    id          BIGSERIAL PRIMARY KEY,
    user_id     UUID,
    user_email  CITEXT,
    action      VARCHAR(64) NOT NULL,
    target      TEXT,
    details     TEXT,
    ip          INET,
    ts          TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_audit_ts   ON audit_logs(ts DESC);
CREATE INDEX idx_audit_user ON audit_logs(user_id, ts DESC);

-- -------------------- Enregistrements / Exports / Plugins --------------------
CREATE TABLE recordings (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    camera_id   UUID NOT NULL REFERENCES cameras(id) ON DELETE CASCADE,
    start_ts    TIMESTAMPTZ NOT NULL,
    end_ts      TIMESTAMPTZ,
    storage_key TEXT NOT NULL,                 -- chemin MinIO/S3/NAS
    size_bytes  BIGINT,
    mode        VARCHAR(16),                   -- continuous/schedule/motion/ai/manual
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_rec_cam ON recordings(camera_id, start_ts DESC);

CREATE TABLE exports (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id     UUID,
    kind        VARCHAR(16),                   -- mp4/jpeg/zip/csv/pdf
    status      VARCHAR(16) DEFAULT 'pending',
    storage_key TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE plugins (
    id          VARCHAR(40) PRIMARY KEY,
    name        VARCHAR(120),
    category    VARCHAR(40),
    version     VARCHAR(16),
    core        BOOLEAN DEFAULT FALSE,
    enabled     BOOLEAN DEFAULT FALSE,
    config      JSONB DEFAULT '{}'::jsonb
);

CREATE TABLE favorites (
    user_id     UUID REFERENCES users(id) ON DELETE CASCADE,
    camera_id   UUID REFERENCES cameras(id) ON DELETE CASCADE,
    PRIMARY KEY (user_id, camera_id)
);

-- -------------------- Supervision réseau (équipements) --------------------
CREATE TABLE equipment (
    id            UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    site_id       UUID NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
    parent_id     UUID REFERENCES equipment(id) ON DELETE SET NULL,  -- topologie
    name          VARCHAR(120) NOT NULL,
    type          VARCHAR(20) NOT NULL,           -- Switch/Routeur/NAS/UPS/Serveur/NVR/Caméra/Générique
    ip            INET,
    vendor        VARCHAR(60),
    model         VARCHAR(120),
    snmp_enabled  BOOLEAN DEFAULT TRUE,
    status        VARCHAR(12) DEFAULT 'offline',  -- online/warning/offline
    latency_ms    REAL,
    uptime_sec    BIGINT DEFAULT 0,
    on_battery    BOOLEAN DEFAULT FALSE,          -- UPS
    battery_pct   SMALLINT,                       -- UPS
    autonomy_min  SMALLINT,                       -- UPS
    last_seen     TIMESTAMPTZ,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_equipment_site   ON equipment(site_id);
CREATE INDEX idx_equipment_parent ON equipment(parent_id);
CREATE INDEX idx_equipment_status ON equipment(status);

-- Données de référence RBAC
INSERT INTO roles (id, code, level) VALUES
 (4,'admin',4),(3,'technician',3),(2,'client',2),(1,'readonly',1),(0,'guest',0)
ON CONFLICT DO NOTHING;
