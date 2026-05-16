-- Allow read access for dashboard tables when using anon/publishable key.
-- Run this in Supabase SQL Editor.

ALTER TABLE IF EXISTS nodes ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS node_locations ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS node_regions ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS fire_regions ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS sensor_readings ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS parent_node_reports ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "anon_read_nodes" ON nodes;
CREATE POLICY "anon_read_nodes"
ON nodes
FOR SELECT
TO anon, authenticated
USING (true);

DROP POLICY IF EXISTS "anon_read_node_regions" ON node_regions;
CREATE POLICY "anon_read_node_regions"
ON node_regions
FOR SELECT
TO anon, authenticated
USING (true);

DROP POLICY IF EXISTS "anon_read_node_locations" ON node_locations;
CREATE POLICY "anon_read_node_locations"
ON node_locations
FOR SELECT
TO anon, authenticated
USING (true);

DROP POLICY IF EXISTS "anon_read_fire_regions" ON fire_regions;
CREATE POLICY "anon_read_fire_regions"
ON fire_regions
FOR SELECT
TO anon, authenticated
USING (true);

DROP POLICY IF EXISTS "anon_read_sensor_readings" ON sensor_readings;
CREATE POLICY "anon_read_sensor_readings"
ON sensor_readings
FOR SELECT
TO anon, authenticated
USING (true);

DROP POLICY IF EXISTS "anon_read_parent_node_reports" ON parent_node_reports;
CREATE POLICY "anon_read_parent_node_reports"
ON parent_node_reports
FOR SELECT
TO anon, authenticated
USING (true);
