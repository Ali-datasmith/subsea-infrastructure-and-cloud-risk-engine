-- =============================================================================
-- Subsea Infrastructure & Cloud Risk Engine — DuckDB DDL
-- Extensions (spatial / h3) are loaded in Python (src/db_engine.py) BEFORE this
-- script runs, so this file contains ONLY DDL + seed data. No INSTALL / LOAD here.
-- =============================================================================

-- 3.1 Subsea cable systems (route geometry as LINESTRING)
CREATE TABLE IF NOT EXISTS subsea_cables (
    cable_id            VARCHAR PRIMARY KEY,
    cable_name          VARCHAR NOT NULL,
    owner_consortium    VARCHAR,
    rfs_year            SMALLINT,
    capacity_tbps       DOUBLE,
    length_km           DOUBLE,
    route_geom          GEOMETRY NOT NULL,
    zone                VARCHAR NOT NULL,
    hyperscaler_owned   BOOLEAN DEFAULT FALSE,
    metadata            JSON,
    updated_at          TIMESTAMPTZ DEFAULT current_timestamp
);

-- 3.2 Cable landing points (ColumnLayer + ArcLayer endpoints)
CREATE TABLE IF NOT EXISTS cable_landing_points (
    landing_id          VARCHAR PRIMARY KEY,
    cable_id            VARCHAR NOT NULL REFERENCES subsea_cables(cable_id),
    station_name        VARCHAR NOT NULL,
    country             VARCHAR NOT NULL,
    location_geom       GEOMETRY NOT NULL,
    nearest_cloud_region VARCHAR
);

-- 3.3 Cable incidents (fault events ingested from CableIncidentPayload)
CREATE TABLE IF NOT EXISTS cable_incidents (
    incident_id             UUID PRIMARY KEY,
    cable_id                VARCHAR NOT NULL,
    fault_type              VARCHAR NOT NULL,
    status                  VARCHAR NOT NULL,
    zone                    VARCHAR NOT NULL,
    fault_location          GEOMETRY NOT NULL,
    detected_at             TIMESTAMPTZ NOT NULL,
    reported_by             VARCHAR NOT NULL,
    affected_segment_km     DOUBLE,
    repair_vessel_assigned  VARCHAR,
    estimated_repair_days   INTEGER,
    vessel_correlations     JSON,
    raw_source_payload      JSON,
    ingested_at             TIMESTAMPTZ DEFAULT current_timestamp
);
CREATE INDEX IF NOT EXISTS idx_incidents_detected_at ON cable_incidents(detected_at);
CREATE INDEX IF NOT EXISTS idx_incidents_status ON cable_incidents(status);
CREATE INDEX IF NOT EXISTS idx_incidents_zone ON cable_incidents(zone);

-- 3.4 Cloud regions (ColumnLayer nodes)
CREATE TABLE IF NOT EXISTS cloud_regions (
    region_id       VARCHAR PRIMARY KEY,
    provider        VARCHAR NOT NULL,
    region_code     VARCHAR NOT NULL,
    display_name    VARCHAR,
    location_geom   GEOMETRY NOT NULL,
    tier            VARCHAR DEFAULT 'standard'
);

-- 3.5 Cloud latency metrics (time-series)
CREATE TABLE IF NOT EXISTS cloud_latency_metrics (
    metric_id             UUID PRIMARY KEY,
    provider              VARCHAR NOT NULL,
    origin_region         VARCHAR NOT NULL,
    destination_region    VARCHAR NOT NULL,
    sampled_at            TIMESTAMPTZ NOT NULL,
    latency_ms            DOUBLE NOT NULL,
    baseline_latency_ms   DOUBLE NOT NULL,
    packet_loss_pct       DOUBLE NOT NULL,
    anomaly_score         DOUBLE NOT NULL,
    nearest_cable_id      VARCHAR
);
CREATE INDEX IF NOT EXISTS idx_latency_sampled_at ON cloud_latency_metrics(sampled_at);
CREATE INDEX IF NOT EXISTS idx_latency_anomaly ON cloud_latency_metrics(anomaly_score);

-- 3.6 Gemini risk briefs (LLM enrichment output; VARIANT for full audit)
CREATE TABLE IF NOT EXISTS risk_briefs (
    brief_id                        UUID PRIMARY KEY,
    generated_at                    TIMESTAMPTZ NOT NULL,
    related_incident_ids            UUID[],
    headline                        VARCHAR NOT NULL,
    executive_summary               VARCHAR NOT NULL,
    risk_level                      VARCHAR NOT NULL,
    affected_zones                  VARCHAR[],
    affected_cloud_providers        VARCHAR[],
    estimated_impacted_traffic_pct  DOUBLE,
    confidence_score                DOUBLE,
    recommended_actions             JSON,
    model_version                   VARCHAR,
    raw_llm_response                JSON
);

-- 3.7 H3 spatial aggregation table (materialized for H3HexagonLayer)
CREATE TABLE IF NOT EXISTS h3_risk_zones (
    h3_index            VARCHAR PRIMARY KEY,
    resolution          TINYINT NOT NULL DEFAULT 3,
    incident_count      INTEGER NOT NULL DEFAULT 0,
    max_risk_level      VARCHAR,
    avg_anomaly_score   DOUBLE,
    affected_cable_ids  VARCHAR[],
    computed_at         TIMESTAMPTZ DEFAULT current_timestamp
);

-- Seed reference data: major cloud regions (approximate DC hub coordinates)
INSERT OR IGNORE INTO cloud_regions VALUES
    ('aws:us-east-1',      'aws',   'us-east-1',      'AWS N. Virginia',       ST_Point(-77.46, 38.95),  'standard'),
    ('aws:eu-west-1',      'aws',   'eu-west-1',      'AWS Ireland',           ST_Point(-6.26, 53.35),   'standard'),
    ('aws:ap-southeast-1', 'aws',   'ap-southeast-1', 'AWS Singapore',         ST_Point(103.85, 1.35),   'standard'),
    ('aws:me-south-1',     'aws',   'me-south-1',     'AWS Bahrain',           ST_Point(50.55, 26.07),   'standard'),
    ('azure:eastus',       'azure', 'eastus',         'Azure East US',         ST_Point(-79.38, 43.65),  'standard'),
    ('azure:westeurope',   'azure', 'westeurope',     'Azure West Europe',     ST_Point(4.90, 52.37),    'standard'),
    ('azure:southeastasia','azure', 'southeastasia',  'Azure Southeast Asia',  ST_Point(103.85, 1.35),   'standard'),
    ('gcp:us-central1',    'gcp',   'us-central1',    'GCP Iowa',              ST_Point(-93.62, 41.60),  'standard'),
    ('gcp:europe-west1',   'gcp',   'europe-west1',   'GCP Belgium',           ST_Point(4.35, 50.85),    'standard'),
    ('gcp:asia-southeast1','gcp',   'asia-southeast1','GCP Singapore',         ST_Point(103.85, 1.35),   'standard'),
    ('oci:us-ashburn-1',   'oci',   'us-ashburn-1',   'OCI Ashburn',           ST_Point(-77.46, 39.04),  'standard'),
    ('oci:eu-frankfurt-1', 'oci',   'eu-frankfurt-1', 'OCI Frankfurt',         ST_Point(8.68, 50.11),    'standard');

-- Seed reference data: critical subsea cable systems
INSERT OR IGNORE INTO subsea_cables (cable_id, cable_name, owner_consortium, rfs_year, capacity_tbps, length_km, route_geom, zone, hyperscaler_owned, metadata) VALUES
    ('aae-1',       'AAE-1',          'Consortium',       2017, 40.0,  25000, ST_GeomFromText('LINESTRING(103.85 1.35, 50.55 26.07, 32.30 30.05, 13.40 52.52)'), 'red_sea_bab_el_mandeb', FALSE, NULL),
    ('eig',         'EIG',            'Consortium',       2012, 3.84,  15000, ST_GeomFromText('LINESTRING(-0.12 51.50, -5.60 36.00, 10.75 34.75, 32.30 30.05, 50.55 26.07)'), 'red_sea_bab_el_mandeb', FALSE, NULL),
    ('seacom',      'Seacom',         'Seacom Ltd',       2009, 1.28,  17000, ST_GeomFromText('LINESTRING(32.58 -25.97, 40.50 -15.00, 50.55 26.07, 32.30 30.05, 9.00 45.00)'), 'red_sea_bab_el_mandeb', FALSE, NULL),
    ('c-lion1',     'C-Lion1',        'Cinia',            2016, 144.0, 1172,  ST_GeomFromText('LINESTRING(24.94 60.17, 21.00 58.00, 18.00 56.50)'), 'baltic_sea', FALSE, NULL),
    ('bcs-ew',      'BCS East-West',  'Arelion',          2005, 1.28,  218,   ST_GeomFromText('LINESTRING(21.00 56.50, 18.50 55.70)'), 'baltic_sea', FALSE, NULL),
    ('estlink-2',   'Estlink 2',      'Elering/Fingrid',  2014, 0.65,  170,  ST_GeomFromText('LINESTRING(24.94 59.44, 24.50 60.10)'), 'baltic_sea', FALSE, NULL),
    ('curie',       'Curie',          'Google',           2019, 72.0,  10500, ST_GeomFromText('LINESTRING(-118.40 33.90, -70.40 -23.65)'), 'other', TRUE, NULL),
    ('dunant',      'Dunant',         'Google',           2020, 250.0, 6600,  ST_GeomFromText('LINESTRING(-75.50 36.80, -1.60 43.30)'), 'other', TRUE, NULL),
    ('grace-hopper','Grace Hopper',   'Google',           2022, 350.0, 6250,  ST_GeomFromText('LINESTRING(-74.00 40.70, -1.60 43.30)'), 'other', TRUE, NULL),
    ('topaz',       'Topaz',          'Google',           2023, 240.0, 14700, ST_GeomFromText('LINESTRING(-122.40 37.70, 139.70 35.60)'), 'taiwan_luzon_strait', TRUE, NULL),
    ('firmina',     'Firmina',        'Google',           2024, 250.0, 13000, ST_GeomFromText('LINESTRING(-75.50 36.80, -46.60 -23.55)'), 'other', TRUE, NULL),
    ('equiano',     'Equiano',        'Google',           2022, 144.0, 15000, ST_GeomFromText('LINESTRING(-9.10 38.70, -15.00 12.00, 3.40 6.50, 18.40 -33.90)'), 'west_africa_coast', TRUE, NULL),
    ('2africa',     '2Africa',        'Meta/Consortium',  2024, 180.0, 45000, ST_GeomFromText('LINESTRING(-1.60 43.30, -15.00 12.00, 3.40 6.50, 40.50 -15.00, 50.55 26.07)'), 'west_africa_coast', FALSE, NULL),
    ('anjan',       'Anjana',         'Meta',             2025, 480.0, 6800,  ST_GeomFromText('LINESTRING(-74.00 40.70, -8.60 41.15)'), 'other', TRUE, NULL),
    ('bifrost',     'Bifrost',        'Meta',             2025, 480.0, 15000, ST_GeomFromText('LINESTRING(-118.40 33.90, 103.85 1.35, 106.80 -6.20)'), 'malacca_singapore_strait', TRUE, NULL),
    ('marea',       'Marea',          'Microsoft/Meta',   2017, 200.0, 6600,  ST_GeomFromText('LINESTRING(-75.90 36.80, -2.90 43.25)'), 'other', TRUE, NULL),
    ('tgn-gulf',    'TGN-Gulf',       'Tata',             2005, 5.12,  8000,  ST_GeomFromText('LINESTRING(50.55 26.07, 72.80 19.00, 80.20 13.00)'), 'red_sea_bab_el_mandeb', FALSE, NULL);

-- Seed reference data: cable landing points
INSERT OR IGNORE INTO cable_landing_points VALUES
    ('lp-aae1-sg',    'aae-1',    'Singapore East',     'Singapore',   ST_Point(103.85, 1.35),   'gcp:asia-southeast1'),
    ('lp-aae1-bh',    'aae-1',    'Manama',             'Bahrain',     ST_Point(50.55, 26.07),   'aws:me-south-1'),
    ('lp-aae1-eg',    'aae-1',    'Alexandria',         'Egypt',       ST_Point(32.30, 30.05),   NULL),
    ('lp-aae1-de',    'aae-1',    'Frankfurt',          'Germany',     ST_Point(13.40, 52.52),   'oci:eu-frankfurt-1'),
    ('lp-clion1-fi',  'c-lion1',  'Helsinki',           'Finland',     ST_Point(24.94, 60.17),   NULL),
    ('lp-clion1-de',  'c-lion1',  'Rostock',            'Germany',     ST_Point(18.00, 56.50),   NULL),
    ('lp-curie-us',   'curie',    'Los Angeles',        'USA',         ST_Point(-118.40, 33.90), 'aws:us-east-1'),
    ('lp-curie-cl',   'curie',    'Valparaiso',         'Chile',       ST_Point(-70.40, -23.65), NULL),
    ('lp-dunant-us',  'dunant',   'Virginia Beach',     'USA',         ST_Point(-75.50, 36.80),  'aws:us-east-1'),
    ('lp-dunant-fr',  'dunant',   'Saint-Hilaire',      'France',      ST_Point(-1.60, 43.30),   'azure:westeurope'),
    ('lp-topaz-us',   'topaz',    'San Luis Obispo',    'USA',         ST_Point(-122.40, 37.70), 'gcp:us-central1'),
    ('lp-topaz-jp',   'topaz',    'Tokyo',              'Japan',       ST_Point(139.70, 35.60),  NULL),
    ('lp-marea-us',   'marea',    'Virginia Beach',     'USA',         ST_Point(-75.90, 36.80),  'aws:us-east-1'),
    ('lp-marea-es',   'marea',    'Bilbao',             'Spain',       ST_Point(-2.90, 43.25),   'azure:westeurope');
-- =============================================================================
-- Pass B — free-tier external signal tables (weather + news + composite score)
-- All JSON (works on every DuckDB storage format). No VARIANT here.
-- =============================================================================

CREATE TABLE IF NOT EXISTS news_risk_signals (
    news_id          UUID PRIMARY KEY,
    source           VARCHAR NOT NULL,
    title            VARCHAR NOT NULL,
    link             VARCHAR NOT NULL UNIQUE,
    published_at     TIMESTAMPTZ NOT NULL,
    zone             VARCHAR NOT NULL,
    severity         VARCHAR NOT NULL,
    matched_keywords VARCHAR[],
    raw_payload      JSON
);
CREATE INDEX IF NOT EXISTS idx_news_published_at ON news_risk_signals(published_at);
CREATE INDEX IF NOT EXISTS idx_news_zone ON news_risk_signals(zone);

CREATE TABLE IF NOT EXISTS weather_risk_signals (
    sample_id                 UUID PRIMARY KEY,
    cable_id                  VARCHAR,
    zone                      VARCHAR NOT NULL,
    sample_lat                DOUBLE NOT NULL,
    sample_lon                DOUBLE NOT NULL,
    sampled_at                TIMESTAMPTZ NOT NULL,
    wind_speed_kmh            DOUBLE NOT NULL,
    wind_gust_kmh             DOUBLE NOT NULL,
    wave_height_m             DOUBLE NOT NULL,
    precipitation_mm          DOUBLE NOT NULL,
    weather_fault_probability DOUBLE NOT NULL,
    repair_vessel_delayed     BOOLEAN NOT NULL DEFAULT FALSE,
    raw_payload               JSON
);
CREATE INDEX IF NOT EXISTS idx_weather_sampled_at ON weather_risk_signals(sampled_at);
CREATE INDEX IF NOT EXISTS idx_weather_zone ON weather_risk_signals(zone);

CREATE TABLE IF NOT EXISTS cable_risk_scores (
    cable_id          VARCHAR PRIMARY KEY,
    zone              VARCHAR NOT NULL,
    incident_score    DOUBLE NOT NULL DEFAULT 0,
    weather_score     DOUBLE NOT NULL DEFAULT 0,
    news_score        DOUBLE NOT NULL DEFAULT 0,
    composite_score   DOUBLE NOT NULL DEFAULT 0,
    max_news_severity VARCHAR,
    repair_delayed    BOOLEAN NOT NULL DEFAULT FALSE,
    computed_at       TIMESTAMPTZ DEFAULT current_timestamp
);
CREATE INDEX IF NOT EXISTS idx_scores_composite ON cable_risk_scores(composite_score);
