-- Kane Condo immutable road and water features grouped by official source release.
CREATE TABLE source_map_feature (
    source_map_feature_id INTEGER PRIMARY KEY,
    source_release_id INTEGER NOT NULL,
    source_file_id INTEGER NOT NULL,
    source_feature_id TEXT NOT NULL CHECK (length(trim(source_feature_id)) > 0),
    source_ordinal INTEGER NOT NULL CHECK (source_ordinal >= 1),
    geometry BLOB NOT NULL,
    geometry_type TEXT NOT NULL
        CHECK (geometry_type IN ('LineString', 'MultiLineString', 'Polygon', 'MultiPolygon')),
    geometry_sha256 TEXT NOT NULL
        CHECK (length(geometry_sha256) = 64 AND geometry_sha256 NOT GLOB '*[^0-9a-f]*'),
    attributes_json TEXT NOT NULL,
    attributes_sha256 TEXT NOT NULL
        CHECK (length(attributes_sha256) = 64 AND attributes_sha256 NOT GLOB '*[^0-9a-f]*'),
    content_sha256 TEXT NOT NULL
        CHECK (length(content_sha256) = 64 AND content_sha256 NOT GLOB '*[^0-9a-f]*'),
    min_x DOUBLE NOT NULL,
    min_y DOUBLE NOT NULL,
    max_x DOUBLE NOT NULL,
    max_y DOUBLE NOT NULL,
    created_at DATETIME NOT NULL,
    CONSTRAINT fk_map_feature_release
        FOREIGN KEY (source_release_id) REFERENCES source_release (source_release_id),
    CONSTRAINT fk_map_feature_source_file
        FOREIGN KEY (source_file_id) REFERENCES source_file (source_file_id),
    CONSTRAINT ck_map_feature_bounds CHECK (
        min_x <= max_x AND min_y <= max_y
        AND (min_x < max_x OR min_y < max_y)
    ),
    CONSTRAINT uk_map_feature_release_feature
        UNIQUE (source_release_id, source_feature_id),
    CONSTRAINT uk_map_feature_release_ordinal
        UNIQUE (source_release_id, source_ordinal)
);

CREATE INDEX ix_source_map_feature_release
    ON source_map_feature (source_release_id, source_feature_id);
CREATE INDEX ix_source_map_feature_bounds
    ON source_map_feature (min_x, max_x, min_y, max_y);

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
    'source_map_feature',
    'features',
    'Kane County roads and water',
    'Immutable normalized road and water features grouped by official source release',
    NULL,
    NULL,
    NULL,
    NULL,
    4326
);

INSERT INTO gpkg_geometry_columns (
    table_name,
    column_name,
    geometry_type_name,
    srs_id,
    z,
    m
) VALUES (
    'source_map_feature',
    'geometry',
    'GEOMETRY',
    4326,
    0,
    0
);
