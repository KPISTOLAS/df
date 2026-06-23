import os
import re
import unicodedata
from datetime import datetime, timezone
import httpx
import certifi
from supabase import create_client, Client
try:
    from supabase.lib.client_options import SyncClientOptions
except ImportError:
    from supabase.lib.client_options import ClientOptions as SyncClientOptions

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


def _region_id_from_drone_id(drone_id):
    """Parse FR code from drone_id (e.g. DRONE_FR10_01 -> FR10). Avoids FR1 matching FR10/FR13."""
    match = re.match(r'^DRONE_(FR\d+)_', drone_id or '')
    return match.group(1) if match else None


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

def _normalize_region_name(region_name):
    if not region_name:
        return ""
    text = unicodedata.normalize("NFC", str(region_name).strip())
    return " ".join(text.split())


REGION_NAME_TO_ID = {
    "Ανατολικής Μακεδονίας και Θράκης": "FR1",
    "Κεντρικής Μακεδονίας": "FR2",
    "Δυτικής Μακεδονίας": "FR3",
    "Ηπείρου": "FR4",
    "Θεσσαλίας": "FR5",
    "Ιονίων Νήσων": "FR6",
    "Δυτικής Ελλάδας": "FR7",
    "Στερεάς Ελλάδας": "FR8",
    "Αττικής": "FR10",
    "Πελοποννήσου": "FR9",
    "Βορείου Αιγαίου": "FR11",
    "Νοτίου Αιγαίου": "FR12",
    "Κρήτης": "FR13",
}


def get_region_id(region_name):
    normalized = _normalize_region_name(region_name)
    if normalized == "Αρχηγείο / Ε.Σ.Κ.Ε.ΔΙ.Κ.":
        return None  # Headquarters has access to all regions

    return REGION_NAME_TO_ID.get(normalized)


def _node_ids_for_region(region_id):
    if not region_id:
        return set()
    response = (
        supabase.table("node_regions")
        .select("node_id")
        .eq("region_id", region_id)
        .execute()
    )
    return {row["node_id"] for row in (response.data or []) if row.get("node_id")}


def get_nodes_by_region(region_id):
    """Get nodes strictly mapped to region_id in node_regions."""
    try:
        allowed_ids = _node_ids_for_region(region_id)
        if not allowed_ids:
            return []

        response = (
            supabase.table("nodes")
            .select("node_id, title, location, description, is_parent")
            .in_("node_id", list(allowed_ids))
            .execute()
        )
        nodes = [
            node for node in (response.data or [])
            if node.get("node_id") in allowed_ids
        ]
        for node in nodes:
            node["region_id"] = region_id
        return _merge_latest_danger_levels(_merge_node_locations(nodes))
    except Exception as e:
        print(f"Error querying nodes for region {region_id}: {e}")
        return []


def get_nodes_for_dashboard(region_name, region_id=None):
    """Load dashboard nodes. Prefer explicit region_id (session) over name lookup."""
    try:
        normalized = _normalize_region_name(region_name)
        if normalized == "Αρχηγείο / Ε.Σ.Κ.Ε.ΔΙ.Κ.":
            response = (
                supabase.table("nodes")
                .select("node_id, title, location, description, is_parent")
                .execute()
            )
            nodes = response.data or []
            for node in nodes:
                node["region_id"] = get_node_region(node.get("node_id"))
            return _merge_latest_danger_levels(_merge_node_locations(nodes))

        resolved_id = region_id or get_region_id(normalized)
        if not resolved_id:
            return []
        return get_nodes_by_region(resolved_id)
    except Exception as e:
        print(f"Error loading nodes for dashboard: {str(e)}")
        return []


def _normalize_drone_row(drone):
    """Coerce DB types so templates and JSON serialization never fail."""
    if not drone:
        return drone
    row = dict(drone)
    for key in ("home_lat", "home_lng", "roam_radius_km"):
        if key in row and row[key] is not None:
            try:
                row[key] = float(row[key])
            except (TypeError, ValueError):
                row[key] = None
    for key, val in list(row.items()):
        if hasattr(val, "isoformat"):
            row[key] = val.isoformat()
    return row


def _normalize_drone_rows(drones):
    return [_normalize_drone_row(d) for d in (drones or [])]


def _get_mock_drones():
    return [
        {"drone_id": "DRONE_FR1_01", "name": "ΣΜΗΕΑ Αμυγδαλεώνας", "model": "DJI Matrice 30T",
         "operational_status": "active", "home_lat": 40.97, "home_lng": 24.37, "roam_radius_km": 2.5},
        {"drone_id": "DRONE_FR1_02", "name": "ΣΜΗΕΑ Χρυσούπολη", "model": "Autel EVO Max",
         "operational_status": "active", "home_lat": 40.995, "home_lng": 24.7, "roam_radius_km": 2.0},
        {"drone_id": "DRONE_FR1_03", "name": "ΣΜΗΕΑ Καβάλας", "model": "DJI Mavic 3T",
         "operational_status": "active", "home_lat": 40.94, "home_lng": 24.41, "roam_radius_km": 1.8},
    ]


_DRONE_SELECT = "drone_id, name, model, operational_status, home_lat, home_lng, roam_radius_km"


def _fetch_drones_by_ids(drone_ids):
    if not drone_ids:
        return []
    response = supabase.table("drones").select(_DRONE_SELECT).in_("drone_id", drone_ids).execute()
    return _normalize_drone_rows(response.data or [])


def _fetch_drones_by_region_id(region_id):
    """Load drones for a region from drone_regions, or by drone_id prefix if mapping missing."""
    drone_regions = supabase.table("drone_regions").select("drone_id").eq("region_id", region_id).execute()
    drone_ids = [row["drone_id"] for row in (drone_regions.data or [])]
    drones = _fetch_drones_by_ids(drone_ids)
    if drones:
        return drones

    all_response = supabase.table("drones").select(_DRONE_SELECT).execute()
    filtered = [
        row for row in (all_response.data or [])
        if _region_id_from_drone_id(row.get("drone_id")) == region_id
    ]
    if filtered:
        return _normalize_drone_rows(filtered)

    return _get_mock_drones_for_region(region_id)


def get_drones_for_region(region_name):
    try:
        if region_name == "Αρχηγείο / Ε.Σ.Κ.Ε.ΔΙ.Κ.":
            response = supabase.table("drones").select(_DRONE_SELECT).execute()
            drones = _normalize_drone_rows(response.data or [])
            return drones if drones else _get_mock_drones_for_region(None)

        region_id = get_region_id(region_name)
        if not region_id:
            return []
        return _fetch_drones_by_region_id(region_id)
    except Exception as e:
        print(f"Error loading drones: {e}")
        region_id = get_region_id(region_name)
        if not region_id:
            return []
        return _get_mock_drones_for_region(region_id)


def _get_mock_drones_for_region(region_id):
    """Return mock drones filtered by region when DB table is missing or empty."""
    all_mocks = {
        "FR1": [
            {"drone_id": "DRONE_FR1_01", "name": "ΣΜΗΕΑ Αμυγδαλεώνας", "model": "DJI Matrice 30T",
             "operational_status": "active", "home_lat": 40.97, "home_lng": 24.37, "roam_radius_km": 2.5},
            {"drone_id": "DRONE_FR1_02", "name": "ΣΜΗΕΑ Χρυσούπολη", "model": "Autel EVO Max",
             "operational_status": "active", "home_lat": 40.995, "home_lng": 24.7, "roam_radius_km": 2.0},
            {"drone_id": "DRONE_FR1_03", "name": "ΣΜΗΕΑ Καβάλας", "model": "DJI Mavic 3T",
             "operational_status": "active", "home_lat": 40.94, "home_lng": 24.41, "roam_radius_km": 1.8},
        ],
        "FR2": [
            {"drone_id": "DRONE_FR2_01", "name": "ΣΜΗΕΑ Θεσσαλονίκης", "model": "DJI Matrice 30T",
             "operational_status": "active", "home_lat": 40.64, "home_lng": 22.94, "roam_radius_km": 3.0},
            {"drone_id": "DRONE_FR2_02", "name": "ΣΜΗΕΑ Χαλκιδικής", "model": "Autel EVO Max",
             "operational_status": "active", "home_lat": 40.32, "home_lng": 23.45, "roam_radius_km": 2.5},
        ],
        "FR9": [
            {"drone_id": "DRONE_FR9_01", "name": "ΣΜΗΕΑ Πάτρας", "model": "DJI Matrice 30T",
             "operational_status": "active", "home_lat": 38.25, "home_lng": 21.73, "roam_radius_km": 2.5},
            {"drone_id": "DRONE_FR9_02", "name": "ΣΜΗΕΑ Τρίπολης", "model": "Autel EVO Max",
             "operational_status": "active", "home_lat": 37.51, "home_lng": 22.38, "roam_radius_km": 2.0},
        ],
        "FR10": [
            {"drone_id": "DRONE_FR10_01", "name": "ΣΜΗΕΑ Αθηνών", "model": "DJI Matrice 30T",
             "operational_status": "active", "home_lat": 37.98, "home_lng": 23.73, "roam_radius_km": 3.5},
            {"drone_id": "DRONE_FR10_02", "name": "ΣΜΗΕΑ Πειραιά", "model": "DJI Mavic 3T",
             "operational_status": "active", "home_lat": 37.94, "home_lng": 23.65, "roam_radius_km": 2.0},
            {"drone_id": "DRONE_FR10_03", "name": "ΣΜΗΕΑ Μαραθώνα", "model": "Autel EVO Max",
             "operational_status": "active", "home_lat": 38.15, "home_lng": 23.96, "roam_radius_km": 2.5},
        ],
        "FR13": [
            {"drone_id": "DRONE_FR13_01", "name": "ΣΜΗΕΑ Ηρακλείου", "model": "DJI Matrice 30T",
             "operational_status": "active", "home_lat": 35.34, "home_lng": 25.14, "roam_radius_km": 2.5},
        ],
    }
    if region_id is None:
        return [d for drones in all_mocks.values() for d in drones]
    return all_mocks.get(region_id, [])


def get_drone_info(drone_id):
    try:
        response = supabase.table("drones").select(
            "drone_id, name, model, operational_status, home_lat, home_lng, roam_radius_km"
        ).eq("drone_id", drone_id).execute()
        if response.data:
            return _normalize_drone_row(response.data[0])
    except Exception as e:
        print(f"Error querying drone {drone_id}: {e}")
    for d in _get_mock_drones_for_region(None):
        if d["drone_id"] == drone_id:
            return d
    return None


def get_drone_region(drone_id):
    parsed = _region_id_from_drone_id(drone_id)
    try:
        response = supabase.table("drone_regions").select("region_id").eq("drone_id", drone_id).execute()
        if response.data:
            db_region = response.data[0]["region_id"]
            if parsed and db_region != parsed:
                return parsed
            return db_region
    except Exception as e:
        print(f"Error getting drone region: {e}")
    return parsed


# ---------------------------------------------------------------------------
# Admin panel statistics
# ---------------------------------------------------------------------------

# Tables the dashboard relies on. Used for the database health check.
ADMIN_HEALTH_TABLES = [
    "nodes",
    "node_locations",
    "node_regions",
    "node_hierarchy",
    "sensor_readings",
    "parent_node_reports",
    "drones",
    "drone_regions",
    "fire_regions",
]


def _table_health(table):
    """Return a health entry for a single table: status + row count."""
    try:
        response = supabase.table(table).select("*", count="exact").limit(1).execute()
        count = response.count if response.count is not None else len(response.data or [])
        return {
            "table": table,
            "status": "ok" if count and count > 0 else "empty",
            "count": count or 0,
            "error": None,
        }
    except Exception as e:
        return {"table": table, "status": "error", "count": None, "error": str(e)}


def get_database_health():
    """Probe each core table and summarise overall database health."""
    tables = [_table_health(t) for t in ADMIN_HEALTH_TABLES]
    has_error = any(t["status"] == "error" for t in tables)
    has_empty = any(t["status"] == "empty" for t in tables)

    if has_error:
        overall = "down" if all(t["status"] == "error" for t in tables) else "degraded"
    elif has_empty:
        overall = "degraded"
    else:
        overall = "healthy"

    return {"overall": overall, "tables": tables}


def get_node_message_status():
    """
    Report which nodes are sending sensor data and which are silent.
    "Silent" nodes have zero sensor_readings -> treated as missing messages.
    """
    try:
        nodes_resp = supabase.table("nodes").select("node_id, title, location, is_parent").execute()
        all_nodes = nodes_resp.data or []

        readings_resp = supabase.table("sensor_readings").select("node_id, timestamp").execute()
        readings = readings_resp.data or []

        latest_by_node = {}
        for row in readings:
            node_id = row.get("node_id")
            ts = row.get("timestamp")
            if not node_id:
                continue
            if node_id not in latest_by_node or (ts or "") > (latest_by_node[node_id] or ""):
                latest_by_node[node_id] = ts

        reporting, silent = [], []
        for node in all_nodes:
            node_id = node.get("node_id")
            entry = {
                "node_id": node_id,
                "title": node.get("title"),
                "location": node.get("location"),
                "is_parent": node.get("is_parent"),
                "last_reading_at": latest_by_node.get(node_id),
            }
            if node_id in latest_by_node:
                reporting.append(entry)
            else:
                silent.append(entry)

        latest_overall = max(latest_by_node.values(), default=None) if latest_by_node else None

        return {
            "total_nodes": len(all_nodes),
            "reporting_count": len(reporting),
            "silent_count": len(silent),
            "total_readings": len(readings),
            "latest_reading_at": latest_overall,
            "silent_nodes": sorted(silent, key=lambda n: n["node_id"] or "")[:50],
        }
    except Exception as e:
        print(f"Error computing node message status: {e}")
        return {
            "total_nodes": 0,
            "reporting_count": 0,
            "silent_count": 0,
            "total_readings": 0,
            "latest_reading_at": None,
            "silent_nodes": [],
            "error": str(e),
        }


def get_parent_report_status(issue_limit=25):
    """
    Summarise parent_node_reports: how many child messages were missing
    (data_received = false) or invalid (data_valid = false).
    """
    try:
        resp = (
            supabase.table("parent_node_reports")
            .select("report_id, parent_id, child_id, timestamp, data_received, data_valid, status_message")
            .order("timestamp", desc=True)
            .execute()
        )
        reports = resp.data or []

        missing = [r for r in reports if r.get("data_received") is False]
        invalid = [r for r in reports if r.get("data_received") is not False and r.get("data_valid") is False]
        ok = [r for r in reports if r.get("data_received") is not False and r.get("data_valid") is not False]

        issues = [r for r in reports if r.get("data_received") is False or r.get("data_valid") is False]

        return {
            "total": len(reports),
            "missing_count": len(missing),
            "invalid_count": len(invalid),
            "ok_count": len(ok),
            "recent_issues": issues[:issue_limit],
        }
    except Exception as e:
        print(f"Error computing parent report status: {e}")
        return {
            "total": 0,
            "missing_count": 0,
            "invalid_count": 0,
            "ok_count": 0,
            "recent_issues": [],
            "error": str(e),
        }


def get_admin_stats():
    """Aggregate all statistics shown on the admin panel."""
    health = get_database_health()
    nodes = get_node_message_status()
    parent_reports = get_parent_report_status()

    table_counts = {t["table"]: t["count"] for t in health["tables"]}

    return {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "database": health,
        "totals": {
            "nodes": table_counts.get("nodes") or 0,
            "drones": table_counts.get("drones") or 0,
            "regions": table_counts.get("fire_regions") or 0,
            "sensor_readings": table_counts.get("sensor_readings") or 0,
            "parent_reports": table_counts.get("parent_node_reports") or 0,
        },
        "node_messages": nodes,
        "parent_reports": parent_reports,
    }