import os
import httpx
import certifi
from supabase import create_client, Client
from supabase.lib.client_options import SyncClientOptions

# Supabase details (prefer environment variables; keep defaults for local development)
SUPABASE_URL = os.getenv("SUPABASE_URL", "https://pwdiolgrydbgmmpkxlnc.supabase.co").strip()
SUPABASE_KEY = os.getenv(
    "SUPABASE_SERVICE_ROLE_KEY",
    os.getenv(
        "SUPABASE_KEY",
        os.getenv("SUPABASE_ANON_KEY", "sb_publishable_odkvXlbdQaeNojzilGsbLA_kIlR93xp")
    )
).strip()


def _build_client_options():
    """
    SSL behavior:
    - default: certificate verification enabled
    - SUPABASE_CA_BUNDLE=<path>: use custom CA bundle file
    - SUPABASE_SSL_VERIFY=false: disable verification (dev fallback only)
    """
    verify_env = os.getenv("SUPABASE_SSL_VERIFY", "true").strip().lower()
    ca_bundle = os.getenv("SUPABASE_CA_BUNDLE", "").strip()

    if ca_bundle:
        return SyncClientOptions(httpx_client=httpx.Client(verify=ca_bundle))

    if verify_env in ("0", "false", "no", "off"):
        return SyncClientOptions(httpx_client=httpx.Client(verify=False))

    # Use certifi CA bundle by default to avoid Windows local issuer issues.
    return SyncClientOptions(httpx_client=httpx.Client(verify=certifi.where()))

def _is_ssl_cert_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return "certificate_verify_failed" in msg or "unable to get local issuer certificate" in msg


# Create Supabase client
try:
    if not SUPABASE_URL or not SUPABASE_KEY:
        raise ValueError("SUPABASE_URL and SUPABASE_KEY must be set.")

    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY, options=_build_client_options())
    supabase.table("nodes").select("*").limit(1).execute()
except Exception as e:
    # Windows/local networks sometimes fail CA validation. Retry once with verify=False.
    if _is_ssl_cert_error(e) and os.getenv("SUPABASE_SSL_VERIFY", "").strip() == "":
        print("SSL certificate verification failed. Retrying with SUPABASE_SSL_VERIFY=false for local development.")
        os.environ["SUPABASE_SSL_VERIFY"] = "false"
        supabase = create_client(SUPABASE_URL, SUPABASE_KEY, options=_build_client_options())
        supabase.table("nodes").select("*").limit(1).execute()
    else:
        print(f"Failed to connect to Supabase: {e}")
        print("Tip: set SUPABASE_CA_BUNDLE to your CA file, or SUPABASE_SSL_VERIFY=false for local dev fallback.")
        raise

# Function to get node information
def _merge_node_locations(nodes):
    """
    Merge lat/lng from node_locations into node dictionaries.
    Keeps compatibility with existing templates that expect flat lat/lng fields.
    """
    try:
        if not nodes:
            return nodes

        node_ids = [node.get("node_id") for node in nodes if node.get("node_id")]
        if not node_ids:
            return nodes

        location_response = supabase.table("node_locations") \
            .select("node_id, lat, lng, map_label") \
            .in_("node_id", node_ids) \
            .execute()

        location_map = {row["node_id"]: row for row in (location_response.data or [])}
        for node in nodes:
            loc = location_map.get(node.get("node_id"))
            if not loc:
                continue
            node["lat"] = loc.get("lat")
            node["lng"] = loc.get("lng")
            node["map_label"] = loc.get("map_label")
            if not node.get("location") and loc.get("map_label"):
                node["location"] = loc.get("map_label")

        return nodes
    except Exception as e:
        print(f"Warning: could not merge node locations: {e}")
        return nodes


def _merge_latest_danger_levels(nodes):
    """
    Merge latest danger_level from sensor_readings into each node.
    """
    try:
        if not nodes:
            return nodes

        node_ids = [node.get("node_id") for node in nodes if node.get("node_id")]
        if not node_ids:
            return nodes

        readings_response = supabase.table("sensor_readings") \
            .select("node_id, danger_level, timestamp") \
            .in_("node_id", node_ids) \
            .order("timestamp", desc=True) \
            .execute()

        latest_by_node = {}
        for reading in (readings_response.data or []):
            node_id = reading.get("node_id")
            if node_id and node_id not in latest_by_node:
                latest_by_node[node_id] = reading

        for node in nodes:
            latest = latest_by_node.get(node.get("node_id"))
            if latest:
                node["danger_level"] = latest.get("danger_level")

        return nodes
    except Exception as e:
        print(f"Warning: could not merge latest danger levels: {e}")
        return nodes


def get_node_info(node_id):
    try:
        response = supabase.table("nodes").select("*").eq("node_id", node_id).execute()
        if not response.data:
            return None
        merged = _merge_node_locations([response.data[0]])
        return merged[0] if merged else response.data[0]
    except Exception as e:
        print(f"Error querying node {node_id}: {e}")
        return None

def get_node_history(node_id):
    try:
        response = supabase.table("sensor_readings")\
            .select("*")\
            .eq("node_id", node_id)\
            .order("timestamp", desc=True)\
            .execute()
        return response.data
    except Exception as e:
        print(f"Error querying history for node {node_id}: {e}")
        return None

def get_nodes_by_region(region_id):
    """Get all nodes for a specific region using node_regions mapping."""
    try:
        node_regions = supabase.table("node_regions") \
            .select("node_id") \
            .eq("region_id", region_id) \
            .execute()

        node_ids = [row["node_id"] for row in (node_regions.data or [])]
        if not node_ids:
            # Fallback: if no mappings exist yet, return all nodes so UI is never empty.
            response = supabase.table("nodes") \
                .select("node_id, title, location, description, is_parent") \
                .execute()
            return _merge_node_locations(response.data or [])

        response = supabase.table("nodes") \
            .select("node_id, title, location, description, is_parent") \
            .in_("node_id", node_ids) \
            .execute()
        return _merge_latest_danger_levels(_merge_node_locations(response.data or []))
    except Exception as e:
        print(f"Error querying nodes for region {region_id}: {e}")
        return []

def get_node_region(node_id):
    """Get the region_id for a specific node"""
    response = supabase.table('node_regions') \
        .select('region_id') \
        .eq('node_id', node_id) \
        .execute()
    return response.data[0]['region_id'] if response.data else None

def get_parent_node_reports(parent_id):
    try:
        response = supabase.table("parent_node_reports") \
            .select("*") \
            .eq("parent_id", parent_id) \
            .order("timestamp", desc=True) \
            .execute()
        return response.data
    except Exception as e:
        print(f"Error querying Parent_Node_Reports for parent {parent_id}: {e}")
        return []

def get_region_id(region_name):
    if region_name == "Αρχηγείο / Ε.Σ.Κ.Ε.ΔΙ.Κ.":
        return None  # Headquarters has access to all regions

    region_mapping = {
        "Ανατολικής Μακεδονίας και Θράκης": "FR1",
        "Κεντρικής Μακεδονίας": "FR2",
        "Δυτικής Μακεδονίας": "FR3",
        "Ηπείρου": "FR4",
        "Θεσσαλίας": "FR5",
        "Ιονίων Νήσων": "FR6",
        "Δυτικής Ελλάδας": "FR7",
        "Στερεάς Ελλάδας": "FR8",
        "Αττικής": "FR9",
        "Πελοποννήσου": "FR10",
        "Βορείου Αιγαίου": "FR11",
        "Νοτίου Αιγαίου": "FR12",
        "Κρήτης": "FR13"
    }
    return region_mapping.get(region_name)

def get_nodes_for_dashboard(region_name):
    try:
        if region_name == 'Αρχηγείο / Ε.Σ.Κ.Ε.ΔΙ.Κ.':
            # For headquarters, get all nodes without region filtering
            response = supabase.table("nodes") \
                .select("node_id, title, location, description, is_parent") \
                .execute()
        else:
            # For regional offices, filter by region
            region_id = get_region_id(region_name)
            if not region_id:
                return None

            # First get all node_ids for this region from node_regions table
            node_regions = supabase.table('node_regions') \
                .select('node_id') \
                .eq('region_id', region_id) \
                .execute()

            node_ids = [nr['node_id'] for nr in node_regions.data] if node_regions.data else []

            if not node_ids:
                # Fallback: region has no mappings yet, show all nodes.
                response = supabase.table("nodes") \
                    .select("node_id, title, location, description, is_parent") \
                    .execute()
                return _merge_latest_danger_levels(_merge_node_locations(response.data or []))

            # Then get all node details for these node_ids
            response = supabase.table("nodes") \
                .select("node_id, title, location, description, is_parent") \
                .in_("node_id", node_ids) \
                .execute()

        return _merge_latest_danger_levels(_merge_node_locations(response.data or []))
    except Exception as e:
        print(f"Error loading nodes for dashboard: {str(e)}")
        return None