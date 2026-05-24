CREATE TABLE IF NOT EXISTS fire_regions (
    region_id VARCHAR(10) PRIMARY KEY,
    name TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS node_regions (
    node_id VARCHAR(20),
    region_id VARCHAR(10),
    PRIMARY KEY (node_id),
    FOREIGN KEY (node_id) REFERENCES nodes(node_id),
    FOREIGN KEY (region_id) REFERENCES fire_regions(region_id)
);
