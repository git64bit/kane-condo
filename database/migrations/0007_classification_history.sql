-- Kane Condo authoritative building classification state and append-only history.
CREATE TABLE building_classification_event (
    classification_event_id INTEGER PRIMARY KEY,
    event_key TEXT NOT NULL UNIQUE
        CHECK (
            length(event_key) BETWEEN 1 AND 128
            AND event_key NOT GLOB '*[^A-Za-z0-9._:-]*'
        ),
    project_building_id INTEGER NOT NULL,
    predecessor_event_id INTEGER,
    event_kind TEXT NOT NULL
        CHECK (event_kind IN ('classification', 'correction', 'undo')),
    previous_classification TEXT NOT NULL
        CHECK (previous_classification IN (
            'unclassified', 'other', 'condominium', 'apartments'
        )),
    new_classification TEXT NOT NULL
        CHECK (new_classification IN (
            'unclassified', 'other', 'condominium', 'apartments'
        )),
    reverses_event_id INTEGER,
    created_at DATETIME NOT NULL,
    CONSTRAINT fk_classification_event_project
        FOREIGN KEY (project_building_id)
        REFERENCES project_building (project_building_id),
    CONSTRAINT fk_classification_event_predecessor
        FOREIGN KEY (predecessor_event_id)
        REFERENCES building_classification_event (classification_event_id),
    CONSTRAINT fk_classification_event_reversal
        FOREIGN KEY (reverses_event_id)
        REFERENCES building_classification_event (classification_event_id),
    CONSTRAINT ck_classification_event_change
        CHECK (previous_classification <> new_classification),
    CONSTRAINT ck_classification_event_undo
        CHECK (
            (event_kind = 'undo' AND reverses_event_id IS NOT NULL)
            OR (event_kind <> 'undo' AND reverses_event_id IS NULL)
        )
);

CREATE TABLE building_classification_current (
    project_building_id INTEGER PRIMARY KEY,
    classification TEXT NOT NULL
        CHECK (classification IN ('other', 'condominium', 'apartments')),
    classification_event_id INTEGER NOT NULL UNIQUE,
    CONSTRAINT fk_classification_current_project
        FOREIGN KEY (project_building_id)
        REFERENCES project_building (project_building_id),
    CONSTRAINT fk_classification_current_event
        FOREIGN KEY (classification_event_id)
        REFERENCES building_classification_event (classification_event_id)
);

CREATE INDEX ix_classification_event_project
    ON building_classification_event (
        project_building_id,
        classification_event_id
    );
CREATE INDEX ix_classification_event_kind
    ON building_classification_event (event_kind, classification_event_id);
CREATE INDEX ix_classification_current_class
    ON building_classification_current (classification, project_building_id);

CREATE TRIGGER tr_classification_event_no_update
BEFORE UPDATE ON building_classification_event
BEGIN
    SELECT RAISE(ABORT, 'building classification history is append-only');
END;

CREATE TRIGGER tr_classification_event_no_delete
BEFORE DELETE ON building_classification_event
BEGIN
    SELECT RAISE(ABORT, 'building classification history is append-only');
END;

CREATE TRIGGER tr_classification_current_insert_match
BEFORE INSERT ON building_classification_current
BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1
        FROM building_classification_event event
        WHERE event.classification_event_id = NEW.classification_event_id
          AND event.project_building_id = NEW.project_building_id
          AND event.new_classification = NEW.classification
    ) THEN RAISE(ABORT, 'current classification does not match its event') END;
END;

CREATE TRIGGER tr_classification_current_update_match
BEFORE UPDATE ON building_classification_current
BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1
        FROM building_classification_event event
        WHERE event.classification_event_id = NEW.classification_event_id
          AND event.project_building_id = NEW.project_building_id
          AND event.new_classification = NEW.classification
    ) THEN RAISE(ABORT, 'current classification does not match its event') END;
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
) VALUES
    (
        'building_classification_event',
        'attributes',
        'Kane Condo classification history',
        'Append-only authoritative classification events for project buildings',
        NULL, NULL, NULL, NULL, NULL
    ),
    (
        'building_classification_current',
        'attributes',
        'Kane Condo current classifications',
        'Explicit current classifications; missing rows mean Unclassified',
        NULL, NULL, NULL, NULL, NULL
    );
