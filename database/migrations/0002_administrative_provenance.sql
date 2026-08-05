-- Kane Condo administrative provenance and immutable source-release lineage.

CREATE TABLE county (
    county_id INTEGER PRIMARY KEY,
    county_key TEXT NOT NULL UNIQUE
        CHECK (
            length(county_key) > 0
            AND county_key = lower(county_key)
            AND county_key NOT GLOB '*[^a-z0-9-]*'
            AND county_key NOT LIKE '-%'
            AND county_key NOT LIKE '%-'
            AND county_key NOT LIKE '%--%'
        ),
    name TEXT NOT NULL CHECK (length(trim(name)) > 0),
    state_code TEXT NOT NULL
        CHECK (length(state_code) = 2 AND state_code = upper(state_code)),
    country_code TEXT NOT NULL DEFAULT 'US'
        CHECK (length(country_code) = 2 AND country_code = upper(country_code)),
    fips_code TEXT NOT NULL UNIQUE
        CHECK (length(fips_code) = 5 AND fips_code NOT GLOB '*[^0-9]*'),
    created_at DATETIME NOT NULL
);

CREATE TABLE source_agency (
    source_agency_id INTEGER PRIMARY KEY,
    agency_key TEXT NOT NULL UNIQUE
        CHECK (
            length(agency_key) > 0
            AND agency_key = lower(agency_key)
            AND agency_key NOT GLOB '*[^a-z0-9-]*'
            AND agency_key NOT LIKE '-%'
            AND agency_key NOT LIKE '%-'
            AND agency_key NOT LIKE '%--%'
        ),
    name TEXT NOT NULL CHECK (length(trim(name)) > 0),
    jurisdiction TEXT NOT NULL CHECK (length(trim(jurisdiction)) > 0),
    homepage_uri TEXT,
    created_at DATETIME NOT NULL
);

CREATE TABLE dataset (
    dataset_id INTEGER PRIMARY KEY,
    dataset_key TEXT NOT NULL UNIQUE
        CHECK (
            length(dataset_key) > 0
            AND dataset_key = lower(dataset_key)
            AND dataset_key NOT GLOB '*[^a-z0-9-]*'
            AND dataset_key NOT LIKE '-%'
            AND dataset_key NOT LIKE '%-'
            AND dataset_key NOT LIKE '%--%'
        ),
    county_id INTEGER NOT NULL,
    source_agency_id INTEGER NOT NULL,
    name TEXT NOT NULL CHECK (length(trim(name)) > 0),
    description TEXT NOT NULL DEFAULT '',
    data_kind TEXT NOT NULL
        CHECK (data_kind IN ('boundary', 'roads', 'water', 'buildings', 'tabular', 'other')),
    source_uri TEXT NOT NULL CHECK (length(trim(source_uri)) > 0),
    created_at DATETIME NOT NULL,
    CONSTRAINT fk_dataset_county
        FOREIGN KEY (county_id) REFERENCES county (county_id),
    CONSTRAINT fk_dataset_agency
        FOREIGN KEY (source_agency_id) REFERENCES source_agency (source_agency_id),
    CONSTRAINT uk_dataset_owner UNIQUE (dataset_id, county_id, source_agency_id)
);

CREATE TABLE harvest_run (
    harvest_run_id INTEGER PRIMARY KEY,
    harvest_key TEXT NOT NULL UNIQUE
        CHECK (
            length(harvest_key) > 0
            AND harvest_key = lower(harvest_key)
            AND harvest_key NOT GLOB '*[^a-z0-9-]*'
            AND harvest_key NOT LIKE '-%'
            AND harvest_key NOT LIKE '%-'
            AND harvest_key NOT LIKE '%--%'
        ),
    dataset_id INTEGER NOT NULL,
    started_at DATETIME NOT NULL,
    completed_at DATETIME,
    status TEXT NOT NULL
        CHECK (status IN ('planned', 'running', 'succeeded', 'failed')),
    source_metadata_json TEXT NOT NULL DEFAULT '{}',
    object_count INTEGER CHECK (object_count IS NULL OR object_count >= 0),
    error_message TEXT,
    created_at DATETIME NOT NULL,
    CONSTRAINT fk_harvest_dataset
        FOREIGN KEY (dataset_id) REFERENCES dataset (dataset_id),
    CONSTRAINT uk_harvest_dataset UNIQUE (harvest_run_id, dataset_id),
    CONSTRAINT ck_harvest_state CHECK (
        (status IN ('planned', 'running') AND completed_at IS NULL AND error_message IS NULL)
        OR (status = 'succeeded' AND completed_at IS NOT NULL AND error_message IS NULL)
        OR (status = 'failed' AND completed_at IS NOT NULL AND length(trim(error_message)) > 0)
    )
);

CREATE TABLE source_file (
    source_file_id INTEGER PRIMARY KEY,
    harvest_run_id INTEGER NOT NULL,
    file_role TEXT NOT NULL
        CHECK (file_role IN ('source', 'manifest', 'metadata', 'inventory', 'exclusions', 'other')),
    relative_path TEXT NOT NULL CHECK (length(trim(relative_path)) > 0),
    byte_length INTEGER NOT NULL CHECK (byte_length >= 0),
    sha256 TEXT NOT NULL
        CHECK (length(sha256) = 64 AND sha256 NOT GLOB '*[^0-9a-f]*'),
    media_type TEXT NOT NULL DEFAULT 'application/octet-stream',
    created_at DATETIME NOT NULL,
    CONSTRAINT fk_source_file_harvest
        FOREIGN KEY (harvest_run_id) REFERENCES harvest_run (harvest_run_id),
    CONSTRAINT uk_source_file_path UNIQUE (harvest_run_id, file_role, relative_path)
);

CREATE TABLE source_release (
    source_release_id INTEGER PRIMARY KEY,
    release_key TEXT NOT NULL UNIQUE
        CHECK (
            length(release_key) > 0
            AND release_key = lower(release_key)
            AND release_key NOT GLOB '*[^a-z0-9-]*'
            AND release_key NOT LIKE '-%'
            AND release_key NOT LIKE '%-'
            AND release_key NOT LIKE '%--%'
        ),
    dataset_id INTEGER NOT NULL,
    harvest_run_id INTEGER NOT NULL,
    lifecycle_status TEXT NOT NULL
        CHECK (lifecycle_status IN ('candidate', 'accepted', 'superseded', 'rejected')),
    source_published_at DATETIME,
    content_sha256 TEXT NOT NULL
        CHECK (length(content_sha256) = 64 AND content_sha256 NOT GLOB '*[^0-9a-f]*'),
    feature_count INTEGER NOT NULL CHECK (feature_count >= 0),
    metadata_json TEXT NOT NULL DEFAULT '{}',
    accepted_at DATETIME,
    superseded_by_release_id INTEGER,
    created_at DATETIME NOT NULL,
    CONSTRAINT fk_release_dataset
        FOREIGN KEY (dataset_id) REFERENCES dataset (dataset_id),
    CONSTRAINT fk_release_harvest_dataset
        FOREIGN KEY (harvest_run_id, dataset_id)
        REFERENCES harvest_run (harvest_run_id, dataset_id),
    CONSTRAINT fk_release_superseded_by
        FOREIGN KEY (superseded_by_release_id)
        REFERENCES source_release (source_release_id),
    CONSTRAINT ck_release_acceptance CHECK (
        (lifecycle_status IN ('accepted', 'superseded') AND accepted_at IS NOT NULL)
        OR (lifecycle_status IN ('candidate', 'rejected') AND accepted_at IS NULL)
    ),
    CONSTRAINT ck_release_supersession CHECK (
        (lifecycle_status = 'superseded' AND superseded_by_release_id IS NOT NULL)
        OR (lifecycle_status <> 'superseded' AND superseded_by_release_id IS NULL)
    )
);

CREATE UNIQUE INDEX ux_source_release_one_accepted
    ON source_release (dataset_id)
    WHERE lifecycle_status = 'accepted';
CREATE INDEX ix_harvest_run_dataset_started
    ON harvest_run (dataset_id, started_at);
CREATE INDEX ix_source_file_harvest
    ON source_file (harvest_run_id);
CREATE INDEX ix_source_release_dataset_status
    ON source_release (dataset_id, lifecycle_status);

INSERT INTO gpkg_contents (
    table_name,
    data_type,
    identifier,
    description,
    min_x,
    min_y,
    max_x,
    max_y,
    srs_id
) VALUES
    ('county', 'attributes', 'Kane Condo counties', 'County jurisdictions tracked by Kane Condo', NULL, NULL, NULL, NULL, NULL),
    ('source_agency', 'attributes', 'Kane Condo source agencies', 'Official organizations that publish tracked datasets', NULL, NULL, NULL, NULL, NULL),
    ('dataset', 'attributes', 'Kane Condo datasets', 'Tracked official datasets and their ownership', NULL, NULL, NULL, NULL, NULL),
    ('harvest_run', 'attributes', 'Kane Condo harvest runs', 'Immutable retrieval attempts and source metadata', NULL, NULL, NULL, NULL, NULL),
    ('source_file', 'attributes', 'Kane Condo source files', 'Preserved source-evidence file identities', NULL, NULL, NULL, NULL, NULL),
    ('source_release', 'attributes', 'Kane Condo source releases', 'Candidate and accepted release lineage', NULL, NULL, NULL, NULL, NULL);
