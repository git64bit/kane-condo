-- Kane Condo project-owned building identity and official-footprint mappings.
CREATE TABLE project_building (
    project_building_id INTEGER PRIMARY KEY,
    building_key TEXT NOT NULL UNIQUE
        CHECK (
            length(building_key) = 68
            AND substr(building_key, 1, 4) = 'kcb-'
            AND substr(building_key, 5) NOT GLOB '*[^0-9a-f]*'
        ),
    lifecycle_status TEXT NOT NULL DEFAULT 'active'
        CHECK (lifecycle_status IN ('active', 'inactive', 'retired')),
    created_from_source_building_id INTEGER NOT NULL UNIQUE,
    identity_algorithm TEXT NOT NULL
        CHECK (identity_algorithm = 'sha256-release-feature-v1'),
    created_at DATETIME NOT NULL,
    retired_at DATETIME,
    CONSTRAINT fk_project_building_origin
        FOREIGN KEY (created_from_source_building_id)
        REFERENCES source_building (source_building_id),
    CONSTRAINT ck_project_building_retirement CHECK (
        (lifecycle_status = 'retired' AND retired_at IS NOT NULL)
        OR (lifecycle_status <> 'retired' AND retired_at IS NULL)
    )
);

CREATE TABLE project_building_source_mapping (
    mapping_id INTEGER PRIMARY KEY,
    project_building_id INTEGER NOT NULL,
    source_building_id INTEGER NOT NULL,
    relationship_type TEXT NOT NULL
        CHECK (relationship_type IN (
            'initial', 'continuation', 'replacement', 'split',
            'merge', 'reappearance', 'manual'
        )),
    decision_method TEXT NOT NULL
        CHECK (decision_method IN ('deterministic-seed', 'automatic', 'reviewed')),
    mapping_status TEXT NOT NULL
        CHECK (mapping_status IN ('proposed', 'confirmed', 'rejected')),
    created_at DATETIME NOT NULL,
    reviewed_at DATETIME,
    CONSTRAINT fk_project_mapping_project
        FOREIGN KEY (project_building_id)
        REFERENCES project_building (project_building_id),
    CONSTRAINT fk_project_mapping_source
        FOREIGN KEY (source_building_id)
        REFERENCES source_building (source_building_id),
    CONSTRAINT uk_project_mapping_pair
        UNIQUE (project_building_id, source_building_id),
    CONSTRAINT ck_project_mapping_review CHECK (
        (decision_method = 'reviewed' AND reviewed_at IS NOT NULL)
        OR (decision_method <> 'reviewed' AND reviewed_at IS NULL)
    )
);

CREATE INDEX ix_project_building_lifecycle
    ON project_building (lifecycle_status, project_building_id);
CREATE INDEX ix_project_mapping_project
    ON project_building_source_mapping (project_building_id, mapping_status);
CREATE INDEX ix_project_mapping_source
    ON project_building_source_mapping (source_building_id, mapping_status);
CREATE UNIQUE INDEX ux_project_mapping_initial_project
    ON project_building_source_mapping (project_building_id)
    WHERE relationship_type = 'initial' AND mapping_status = 'confirmed';
CREATE UNIQUE INDEX ux_project_mapping_initial_source
    ON project_building_source_mapping (source_building_id)
    WHERE relationship_type = 'initial' AND mapping_status = 'confirmed';

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
        'project_building',
        'attributes',
        'Kane Condo project buildings',
        'Project-owned building identities independent of official source identifiers',
        NULL, NULL, NULL, NULL, NULL
    ),
    (
        'project_building_source_mapping',
        'attributes',
        'Kane Condo building mappings',
        'Auditable mappings between project building identities and official footprints',
        NULL, NULL, NULL, NULL, NULL
    );
