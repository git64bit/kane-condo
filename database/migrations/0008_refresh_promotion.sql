-- Kane Condo append-only refresh promotion and rollback history.
CREATE TABLE refresh_promotion_event (
    promotion_event_id INTEGER PRIMARY KEY,
    event_key TEXT NOT NULL UNIQUE
        CHECK (
            length(event_key) BETWEEN 1 AND 160
            AND event_key NOT GLOB '*[^A-Za-z0-9._:-]*'
        ),
    promotion_key TEXT NOT NULL
        CHECK (
            length(promotion_key) > 0
            AND promotion_key = lower(promotion_key)
            AND promotion_key NOT GLOB '*[^a-z0-9-]*'
            AND promotion_key NOT LIKE '-%'
            AND promotion_key NOT LIKE '%-'
            AND promotion_key NOT LIKE '%--%'
        ),
    event_kind TEXT NOT NULL CHECK (event_kind IN ('promotion', 'rollback')),
    related_event_id INTEGER,
    previous_database_sha256 TEXT NOT NULL
        CHECK (length(previous_database_sha256) = 64 AND previous_database_sha256 NOT GLOB '*[^0-9a-f]*'),
    prepared_candidate_sha256 TEXT NOT NULL
        CHECK (length(prepared_candidate_sha256) = 64 AND prepared_candidate_sha256 NOT GLOB '*[^0-9a-f]*'),
    promotion_plan_sha256 TEXT NOT NULL
        CHECK (length(promotion_plan_sha256) = 64 AND promotion_plan_sha256 NOT GLOB '*[^0-9a-f]*'),
    reconciliation_key TEXT NOT NULL CHECK (length(trim(reconciliation_key)) > 0),
    reconciliation_sha256 TEXT NOT NULL
        CHECK (length(reconciliation_sha256) = 64 AND reconciliation_sha256 NOT GLOB '*[^0-9a-f]*'),
    authorization_kind TEXT NOT NULL CHECK (authorization_kind = 'explicit-command'),
    details_json TEXT NOT NULL,
    created_at DATETIME NOT NULL,
    CONSTRAINT fk_refresh_promotion_related
        FOREIGN KEY (related_event_id) REFERENCES refresh_promotion_event (promotion_event_id),
    CONSTRAINT ck_refresh_promotion_relation CHECK (
        (event_kind = 'promotion' AND related_event_id IS NULL)
        OR (event_kind = 'rollback' AND related_event_id IS NOT NULL)
    )
);

CREATE INDEX ix_refresh_promotion_key
    ON refresh_promotion_event (promotion_key, promotion_event_id);
CREATE INDEX ix_refresh_promotion_kind
    ON refresh_promotion_event (event_kind, promotion_event_id);

CREATE TRIGGER tr_refresh_promotion_event_no_update
BEFORE UPDATE ON refresh_promotion_event
BEGIN
    SELECT RAISE(ABORT, 'refresh promotion history is append-only');
END;

CREATE TRIGGER tr_refresh_promotion_event_no_delete
BEFORE DELETE ON refresh_promotion_event
BEGIN
    SELECT RAISE(ABORT, 'refresh promotion history is append-only');
END;

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
) VALUES (
    'refresh_promotion_event',
    'attributes',
    'Kane Condo refresh promotion history',
    'Append-only authoritative database promotion and rollback events',
    NULL,
    NULL,
    NULL,
    NULL,
    NULL
);
