-- Insert parent nodes
INSERT INTO nodes (node_id, title, is_parent) VALUES
('N1', 'Node 1', TRUE),
('N2', 'Node 2', TRUE)
ON CONFLICT (node_id) DO UPDATE
SET title = EXCLUDED.title,
    is_parent = EXCLUDED.is_parent;

-- Insert child nodes
INSERT INTO nodes (node_id, title, is_parent) VALUES
('N1_1', 'Node 1.1', FALSE),
('N1_2', 'Node 1.2', FALSE),
('N1_3', 'Node 1.3', FALSE),
('N2_1', 'Node 2.1', FALSE),
('N2_2', 'Node 2.2', FALSE)
ON CONFLICT (node_id) DO UPDATE
SET title = EXCLUDED.title,
    is_parent = EXCLUDED.is_parent;

-- Node coordinates near Kavala for map rendering
INSERT INTO node_locations (node_id, lat, lng, map_label) VALUES
('N1',   40.939500, 24.401500, 'Kavala West Hub'),
('N1_1', 40.945500, 24.411500, 'Kavala Industrial Zone'),
('N1_2', 40.9315696, 24.3685927, 'Kavala City North'),
('N1_3', 40.9580361, 24.4011451, 'Kavala East Coast'),
('N2',   40.965000, 24.475000, 'Kavala North Hub'),
('N2_1', 40.978000, 24.490000, 'Amygdaleonas Area'),
('N2_2', 40.9470944, 24.4630878, 'Nea Peramos Area')
ON CONFLICT (node_id) DO UPDATE
SET lat = EXCLUDED.lat,
    lng = EXCLUDED.lng,
    map_label = EXCLUDED.map_label;

-- Establish hierarchy relationships
INSERT INTO node_hierarchy (parent_id, child_id) VALUES
('N1', 'N1_1'),
('N1', 'N1_2'),
('N1', 'N1_3'),
('N2', 'N2_1'),
('N2', 'N2_2')
ON CONFLICT (parent_id, child_id) DO NOTHING;

-- Sample sensor readings for one of the nodes
INSERT INTO sensor_readings (
    node_id, danger_level, temperature, humidity,
    gas_and_smoke, rain, wind_speed,
    flora_density, slope, vegetation_type
) VALUES
('N1_1', 2, 25.50, 45.30, 12.45, FALSE, 5.20, 75.30, 10.50, 'Deciduous'),
('N1_1', 3, 28.75, 40.20, 15.80, FALSE, 6.50, 74.80, 10.60, 'Deciduous'),
('N2_1', 1, 22.30, 50.10, 8.90, TRUE, 8.20, 60.50, 15.30, 'Coniferous'),
('N2_2', 4, 30.10, 35.60, 25.30, FALSE, 12.40, 45.20, 5.80, 'Mixed');

-- Sample sensor readings for N1_3 (Node 1.3)
INSERT INTO sensor_readings (node_id, danger_level, temperature, humidity, gas_and_smoke, rain, wind_speed, flora_density, slope)
VALUES
('N1_3', 1, 22.5, 60.0, 10.2, FALSE, 5.5, 65.0, 12.0),
('N1_3', 2, 24.1, 58.5, 15.7, TRUE, 8.2, 63.5, 12.0),
('N1_3', 1, 21.8, 62.3, 8.9, FALSE, 4.8, 66.2, 12.0);

-- Reports for Parent N1
INSERT INTO parent_node_reports (parent_id, child_id, data_received, data_valid, status_message) VALUES
('N1', 'N1_1', TRUE, TRUE, 'Data received successfully and validated.'),
('N1', 'N1_2', TRUE, FALSE, 'Temperature reading exceeded safe limit.'),
('N1', 'N1_3', TRUE, TRUE, 'Data looks normal and valid.');

-- Reports for Parent N2
INSERT INTO parent_node_reports (parent_id, child_id, data_received, data_valid, status_message) VALUES
('N2', 'N2_1', TRUE, TRUE, 'All readings within expected range.'),
('N2', 'N2_2', FALSE, NULL, 'No data received from node.');
