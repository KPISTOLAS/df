-- =============================================================================
-- Migrate_Update_And_Insert.sql
-- Run in Supabase SQL Editor (or psql) on an EXISTING database.
-- Safe to re-run: uses ON CONFLICT ... DO UPDATE / DO NOTHING.
--
-- Aligns with App_test.py / DatabaseScript.py region mapping:
--   FR9  = Πελοποννήσου  |  FR10 = Αττικής
-- =============================================================================

BEGIN;

-- -----------------------------------------------------------------------------
-- 1) FIRE REGIONS (13 Π.Υ. – matches login.html + DatabaseScript.py)
-- -----------------------------------------------------------------------------
INSERT INTO fire_regions (region_id, name) VALUES
('FR1',  'Περιφερειακή Πυροσβεστική Διοίκηση Ανατολικής Μακεδονίας και Θράκης'),
('FR2',  'Περιφερειακή Πυροσβεστική Διοίκηση Κεντρικής Μακεδονίας'),
('FR3',  'Περιφερειακή Πυροσβεστική Διοίκηση Δυτικής Μακεδονίας'),
('FR4',  'Περιφερειακή Πυροσβεστική Διοίκηση Ηπείρου'),
('FR5',  'Περιφερειακή Πυροσβεστική Διοίκηση Θεσσαλίας'),
('FR6',  'Περιφερειακή Πυροσβεστική Διοίκηση Ιονίων Νήσων'),
('FR7',  'Περιφερειακή Πυροσβεστική Διοίκηση Δυτικής Ελλάδας'),
('FR8',  'Περιφερειακή Πυροσβεστική Διοίκηση Στερεάς Ελλάδας'),
('FR9',  'Περιφερειακή Πυροσβεστική Διοίκηση Πελοποννήσου'),
('FR10', 'Περιφερειακή Πυροσβεστική Διοίκηση Αττικής'),
('FR11', 'Περιφερειακή Πυροσβεστική Διοίκηση Βορείου Αιγαίου'),
('FR12', 'Περιφερειακή Πυροσβεστική Διοίκηση Νοτίου Αιγαίου'),
('FR13', 'Περιφερειακή Πυροσβεστική Διοίκηση Κρήτης')
ON CONFLICT (region_id) DO UPDATE
SET name = EXCLUDED.name;

-- Fix legacy mis-labelled rows (old Insert(Fd).sql had FR9/FR10 names swapped)
UPDATE fire_regions SET name = 'Περιφερειακή Πυροσβεστική Διοίκηση Πελοποννήσου'
WHERE region_id = 'FR9';
UPDATE fire_regions SET name = 'Περιφερειακή Πυροσβεστική Διοίκηση Αττικής'
WHERE region_id = 'FR10';

-- -----------------------------------------------------------------------------
-- 2) NODES (required before node_regions FK)
-- -----------------------------------------------------------------------------
INSERT INTO nodes (node_id, title, is_parent) VALUES
('N1',   'Node 1', TRUE),
('N2',   'Node 2', TRUE),
('N1_1', 'Node 1.1', FALSE),
('N1_2', 'Node 1.2', FALSE),
('N1_3', 'Node 1.3', FALSE),
('N2_1', 'Node 2.1', FALSE),
('N2_2', 'Node 2.2', FALSE)
ON CONFLICT (node_id) DO UPDATE
SET title = EXCLUDED.title,
    is_parent = EXCLUDED.is_parent;

-- -----------------------------------------------------------------------------
-- 3) NODE LOCATIONS (map coordinates)
-- -----------------------------------------------------------------------------
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

-- -----------------------------------------------------------------------------
-- 4) NODE HIERARCHY
-- -----------------------------------------------------------------------------
INSERT INTO node_hierarchy (parent_id, child_id) VALUES
('N1', 'N1_1'),
('N1', 'N1_2'),
('N1', 'N1_3'),
('N2', 'N2_1'),
('N2', 'N2_2')
ON CONFLICT (parent_id, child_id) DO NOTHING;

-- -----------------------------------------------------------------------------
-- 5) NODE ↔ REGION (FR1 demo network)
-- -----------------------------------------------------------------------------
INSERT INTO node_regions (node_id, region_id) VALUES
('N1',   'FR1'),
('N2',   'FR1'),
('N1_1', 'FR1'),
('N1_2', 'FR1'),
('N1_3', 'FR1'),
('N2_1', 'FR1'),
('N2_2', 'FR1')
ON CONFLICT (node_id) DO UPDATE
SET region_id = EXCLUDED.region_id;

-- -----------------------------------------------------------------------------
-- 6) DRONES
-- -----------------------------------------------------------------------------
INSERT INTO drones (
    drone_id, node_id, name, model, operational_status,
    last_maintenance, max_flight_time, home_lat, home_lng, roam_radius_km
) VALUES
('DRONE_FR1_01',  NULL, 'ΣΜΗΕΑ Αμυγδαλεώνας',   'DJI Matrice 30T', 'active', '2025-04-10', 45, 40.97,  24.37,  2.5),
('DRONE_FR1_02',  NULL, 'ΣΜΗΕΑ Χρυσούπολη',      'Autel EVO Max',   'active', '2025-03-22', 40, 40.995, 24.7,   2.0),
('DRONE_FR1_03',  NULL, 'ΣΜΗΕΑ Καβάλας',        'DJI Mavic 3T',    'active', '2025-05-01', 35, 40.94,  24.41,  1.8),
('DRONE_FR2_01',  NULL, 'ΣΜΗΕΑ Θεσσαλονίκης',   'DJI Matrice 30T', 'active', '2025-04-15', 45, 40.64,  22.94,  3.0),
('DRONE_FR2_02',  NULL, 'ΣΜΗΕΑ Χαλκιδικής',     'Autel EVO Max',   'active', '2025-02-18', 40, 40.32,  23.45,  2.5),
('DRONE_FR2_03',  NULL, 'ΣΜΗΕΑ Κατερίνης',      'DJI Mavic 3T',    'active', '2025-01-30', 35, 40.27,  22.51,  2.0),
('DRONE_FR9_01',  NULL, 'ΣΜΗΕΑ Πάτρας',         'DJI Matrice 30T', 'active', '2025-03-05', 45, 38.25,  21.73,  2.5),
('DRONE_FR9_02',  NULL, 'ΣΜΗΕΑ Τρίπολης',       'Autel EVO Max',   'active', '2025-04-20', 40, 37.51,  22.38,  2.0),
('DRONE_FR10_01', NULL, 'ΣΜΗΕΑ Αθηνών',         'DJI Matrice 30T', 'active', '2025-05-10', 45, 37.98,  23.73,  3.5),
('DRONE_FR10_02', NULL, 'ΣΜΗΕΑ Πειραιά',        'DJI Mavic 3T',    'active', '2025-04-01', 35, 37.94,  23.65,  2.0),
('DRONE_FR10_03', NULL, 'ΣΜΗΕΑ Μαραθώνα',       'Autel EVO Max',   'active', '2025-02-28', 40, 38.15,  23.96,  2.5),
('DRONE_FR13_01', NULL, 'ΣΜΗΕΑ Ηρακλείου',      'DJI Matrice 30T', 'active', '2025-03-18', 45, 35.34,  25.14,  2.5),
('DRONE_FR13_02', NULL, 'ΣΜΗΕΑ Χανίων',        'Autel EVO Max',   'active', '2025-04-25', 40, 35.51,  24.02,  2.0),
('DRONE_FR13_03', NULL, 'ΣΜΗΕΑ Ρεθύμνου',       'DJI Mavic 3T',    'active', '2025-01-15', 35, 35.37,  24.47,  1.8)
ON CONFLICT (drone_id) DO UPDATE
SET name = EXCLUDED.name,
    model = EXCLUDED.model,
    operational_status = EXCLUDED.operational_status,
    home_lat = EXCLUDED.home_lat,
    home_lng = EXCLUDED.home_lng,
    roam_radius_km = EXCLUDED.roam_radius_km;

-- -----------------------------------------------------------------------------
-- 7) DRONE ↔ REGION (must match drone_id prefix: DRONE_FR9_* → FR9, etc.)
-- -----------------------------------------------------------------------------
INSERT INTO drone_regions (drone_id, region_id) VALUES
('DRONE_FR1_01',  'FR1'),
('DRONE_FR1_02',  'FR1'),
('DRONE_FR1_03',  'FR1'),
('DRONE_FR2_01',  'FR2'),
('DRONE_FR2_02',  'FR2'),
('DRONE_FR2_03',  'FR2'),
('DRONE_FR9_01',  'FR9'),
('DRONE_FR9_02',  'FR9'),
('DRONE_FR10_01', 'FR10'),
('DRONE_FR10_02', 'FR10'),
('DRONE_FR10_03', 'FR10'),
('DRONE_FR13_01', 'FR13'),
('DRONE_FR13_02', 'FR13'),
('DRONE_FR13_03', 'FR13')
ON CONFLICT (drone_id) DO UPDATE
SET region_id = EXCLUDED.region_id;

-- Repair wrong drone_regions if an old seed mapped by swapped names
UPDATE drone_regions SET region_id = 'FR9'
WHERE drone_id LIKE 'DRONE_FR9_%';
UPDATE drone_regions SET region_id = 'FR10'
WHERE drone_id LIKE 'DRONE_FR10_%';
UPDATE drone_regions SET region_id = 'FR1'
WHERE drone_id LIKE 'DRONE_FR1_%'
  AND drone_id NOT LIKE 'DRONE_FR10_%'
  AND drone_id NOT LIKE 'DRONE_FR11_%'
  AND drone_id NOT LIKE 'DRONE_FR12_%'
  AND drone_id NOT LIKE 'DRONE_FR13_%';

COMMIT;

-- -----------------------------------------------------------------------------
-- 8) OPTIONAL: sample sensor data + parent reports (uncomment if tables are empty)
-- -----------------------------------------------------------------------------
/*
INSERT INTO sensor_readings (
    node_id, danger_level, temperature, humidity,
    gas_and_smoke, rain, wind_speed, flora_density, slope, vegetation_type
) VALUES
('N1_1', 2, 25.50, 45.30, 12.45, FALSE, 5.20, 75.30, 10.50, 'Deciduous'),
('N1_1', 3, 28.75, 40.20, 15.80, FALSE, 6.50, 74.80, 10.60, 'Deciduous'),
('N2_1', 1, 22.30, 50.10, 8.90,  TRUE,  8.20, 60.50, 15.30, 'Coniferous'),
('N2_2', 4, 30.10, 35.60, 25.30, FALSE, 12.40, 45.20, 5.80,  'Mixed')
ON CONFLICT DO NOTHING;

INSERT INTO parent_node_reports (parent_id, child_id, data_received, data_valid, status_message) VALUES
('N1', 'N1_1', TRUE, TRUE,  'Data received successfully and validated.'),
('N1', 'N1_2', TRUE, FALSE, 'Temperature reading exceeded safe limit.'),
('N1', 'N1_3', TRUE, TRUE,  'Data looks normal and valid.'),
('N2', 'N2_1', TRUE, TRUE,  'All readings within expected range.'),
('N2', 'N2_2', FALSE, NULL, 'No data received from node.')
ON CONFLICT DO NOTHING;
*/

-- -----------------------------------------------------------------------------
-- 9) VERIFICATION (read-only)
-- -----------------------------------------------------------------------------
SELECT region_id, name FROM fire_regions ORDER BY region_id;

SELECT nr.region_id, COUNT(*) AS node_count
FROM node_regions nr
GROUP BY nr.region_id
ORDER BY nr.region_id;

SELECT dr.region_id, COUNT(*) AS drone_count
FROM drone_regions dr
GROUP BY dr.region_id
ORDER BY dr.region_id;

SELECT d.drone_id, d.name, dr.region_id
FROM drones d
LEFT JOIN drone_regions dr ON dr.drone_id = d.drone_id
ORDER BY dr.region_id, d.drone_id;
