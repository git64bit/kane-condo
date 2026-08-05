-- Kane Condo GeoPackage 1.4.0 foundation and immutable migration ledger.

CREATE TABLE schema_migration (
    migration_id INTEGER PRIMARY KEY,
    filename TEXT NOT NULL UNIQUE,
    sha256 TEXT NOT NULL UNIQUE
        CHECK (length(sha256) = 64 AND sha256 NOT GLOB '*[^0-9a-f]*'),
    applied_at DATETIME NOT NULL
);

CREATE TABLE gpkg_spatial_ref_sys (
    srs_name TEXT NOT NULL,
    srs_id INTEGER NOT NULL PRIMARY KEY,
    organization TEXT NOT NULL,
    organization_coordsys_id INTEGER NOT NULL,
    definition TEXT NOT NULL,
    description TEXT
);

INSERT INTO gpkg_spatial_ref_sys (
    srs_name,
    srs_id,
    organization,
    organization_coordsys_id,
    definition,
    description
) VALUES
    (
        'Undefined Cartesian',
        -1,
        'NONE',
        -1,
        'undefined',
        'undefined Cartesian coordinate reference system'
    ),
    (
        'Undefined geographic',
        0,
        'NONE',
        0,
        'undefined',
        'undefined geographic coordinate reference system'
    ),
    (
        'WGS 84 geodetic',
        4326,
        'EPSG',
        4326,
        'GEOGCS["WGS 84",DATUM["WGS_1984",SPHEROID["WGS 84",6378137,298.257223563]],PRIMEM["Greenwich",0],UNIT["degree",0.0174532925199433],AXIS["Longitude",EAST],AXIS["Latitude",NORTH]]',
        'longitude/latitude coordinates on the WGS 84 datum'
    );

CREATE TABLE gpkg_contents (
    table_name TEXT NOT NULL PRIMARY KEY,
    data_type TEXT NOT NULL,
    identifier TEXT UNIQUE,
    description TEXT DEFAULT '',
    last_change DATETIME NOT NULL
        DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    min_x DOUBLE,
    min_y DOUBLE,
    max_x DOUBLE,
    max_y DOUBLE,
    srs_id INTEGER,
    CONSTRAINT fk_gc_r_srs_id
        FOREIGN KEY (srs_id) REFERENCES gpkg_spatial_ref_sys (srs_id)
);

CREATE TABLE gpkg_geometry_columns (
    table_name TEXT NOT NULL,
    column_name TEXT NOT NULL,
    geometry_type_name TEXT NOT NULL,
    srs_id INTEGER NOT NULL,
    z TINYINT NOT NULL,
    m TINYINT NOT NULL,
    CONSTRAINT pk_geom_cols PRIMARY KEY (table_name, column_name),
    CONSTRAINT uk_gc_table_name UNIQUE (table_name),
    CONSTRAINT fk_gc_tn
        FOREIGN KEY (table_name) REFERENCES gpkg_contents (table_name),
    CONSTRAINT fk_gc_srs
        FOREIGN KEY (srs_id) REFERENCES gpkg_spatial_ref_sys (srs_id),
    CONSTRAINT ck_gc_z CHECK (z IN (0, 1, 2)),
    CONSTRAINT ck_gc_m CHECK (m IN (0, 1, 2))
);

CREATE TABLE gpkg_extensions (
    table_name TEXT,
    column_name TEXT,
    extension_name TEXT NOT NULL,
    definition TEXT NOT NULL,
    scope TEXT NOT NULL,
    CONSTRAINT ge_tce UNIQUE (table_name, column_name, extension_name),
    CONSTRAINT ge_scope CHECK (scope IN ('read-write', 'write-only'))
);

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
    'schema_migration',
    'attributes',
    'Kane Condo schema migrations',
    'Applied SQL migrations and their SHA-256 identities',
    NULL,
    NULL,
    NULL,
    NULL,
    NULL
);
