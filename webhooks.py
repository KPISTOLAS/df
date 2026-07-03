"""
Webhook alert subscriptions for the Fire Safety Dashboard.

Admins register webhook URLs that receive an HTTP POST whenever a node's latest
``danger_level`` meets or exceeds a configured threshold. Because the hosted
Supabase project is read-only (RLS) in this environment, subscriptions are
persisted to a small local JSON file rather than the database.

The alert evaluation is data-driven: it reads the latest danger level per node
from the existing dashboard queries, so it works with the static seed data
(no wall-clock/freshness assumptions).
"""

import os
import json
import uuid
import threading
from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx

# Danger levels run 1 (low) .. 5 (critical); see childColorByDanger in index.html.
MIN_LEVEL = 1
MAX_LEVEL = 5
DEFAULT_THRESHOLD = 3

# Headquarters region name — a webhook with region=None (or this value) matches all regions.
HEADQUARTERS = "Αρχηγείο / Ε.Σ.Κ.Ε.ΔΙ.Κ."

_STORE_PATH = os.getenv("WEBHOOKS_STORE", os.path.join(os.path.dirname(__file__), "webhooks.json"))
_DELIVERY_TIMEOUT = float(os.getenv("WEBHOOK_TIMEOUT", "5"))
_lock = threading.RLock()


def _now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load():
    try:
        with open(_STORE_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
            return data if isinstance(data, list) else []
    except FileNotFoundError:
        return []
    except Exception as e:
        print(f"Warning: could not read webhook store: {e}")
        return []


def _save(subscriptions):
    tmp = f"{_STORE_PATH}.tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(subscriptions, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, _STORE_PATH)


def _validate_url(url):
    parsed = urlparse((url or "").strip())
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError("Το URL του webhook πρέπει να είναι έγκυρο http(s) URL.")
    return url.strip()


def _clamp_threshold(value):
    try:
        level = int(value)
    except (TypeError, ValueError):
        raise ValueError("Το όριο επικινδυνότητας πρέπει να είναι ακέραιος.")
    return max(MIN_LEVEL, min(MAX_LEVEL, level))


def list_webhooks():
    with _lock:
        return _load()


def get_webhook(webhook_id):
    with _lock:
        for sub in _load():
            if sub.get("id") == webhook_id:
                return sub
    return None


def create_webhook(url, min_danger_level=DEFAULT_THRESHOLD, region=None, description=""):
    url = _validate_url(url)
    threshold = _clamp_threshold(min_danger_level)
    region = (region or "").strip() or None
    if region == HEADQUARTERS:
        region = None

    sub = {
        "id": uuid.uuid4().hex[:12],
        "url": url,
        "min_danger_level": threshold,
        "region": region,
        "description": (description or "").strip(),
        "enabled": True,
        "created_at": _now_iso(),
        "last_triggered_at": None,
        "last_status": None,
        "last_error": None,
        "delivery_count": 0,
    }
    with _lock:
        subs = _load()
        subs.append(sub)
        _save(subs)
    return sub


def delete_webhook(webhook_id):
    with _lock:
        subs = _load()
        remaining = [s for s in subs if s.get("id") != webhook_id]
        if len(remaining) == len(subs):
            return False
        _save(remaining)
        return True


def set_enabled(webhook_id, enabled):
    with _lock:
        subs = _load()
        target = None
        for sub in subs:
            if sub.get("id") == webhook_id:
                sub["enabled"] = bool(enabled)
                target = sub
                break
        if target is None:
            return None
        _save(subs)
        return target


def _record_delivery(webhook_id, status, error):
    with _lock:
        subs = _load()
        for sub in subs:
            if sub.get("id") == webhook_id:
                sub["last_triggered_at"] = _now_iso()
                sub["last_status"] = status
                sub["last_error"] = error
                sub["delivery_count"] = (sub.get("delivery_count") or 0) + 1
                _save(subs)
                break


def _deliver(sub, payload):
    """POST payload to a single webhook, recording the outcome. Returns a result dict."""
    result = {"webhook_id": sub.get("id"), "url": sub.get("url"), "ok": False,
              "status": None, "error": None}
    try:
        resp = httpx.post(
            sub["url"],
            json=payload,
            timeout=_DELIVERY_TIMEOUT,
            headers={"Content-Type": "application/json",
                     "User-Agent": "FireSafetyDashboard-Webhook/1.0"},
        )
        result["status"] = resp.status_code
        result["ok"] = 200 <= resp.status_code < 300
        if not result["ok"]:
            result["error"] = f"HTTP {resp.status_code}"
    except Exception as e:
        result["error"] = str(e)
    _record_delivery(sub["id"], result["status"], result["error"])
    return result


def _alert_from_node(node, threshold):
    return {
        "node_id": node.get("node_id"),
        "title": node.get("title"),
        "location": node.get("location") or node.get("map_label"),
        "region_id": node.get("region_id"),
        "danger_level": node.get("danger_level"),
        "threshold": threshold,
        "lat": node.get("lat"),
        "lng": node.get("lng"),
    }


def _matches(sub, node, region_id_for_name):
    """A subscription matches a node when the danger threshold is met and (optional) region filter passes."""
    level = node.get("danger_level")
    if level is None:
        return False
    try:
        if int(level) < int(sub.get("min_danger_level", DEFAULT_THRESHOLD)):
            return False
    except (TypeError, ValueError):
        return False
    region = sub.get("region")
    if region:
        wanted = region_id_for_name(region)
        if wanted and node.get("region_id") != wanted:
            return False
    return True


def current_alerts(load_all_nodes, threshold=MIN_LEVEL):
    """Return every node whose latest danger_level >= threshold, sorted high→low."""
    nodes = load_all_nodes() or []
    alerts = []
    for node in nodes:
        level = node.get("danger_level")
        if level is None:
            continue
        try:
            if int(level) >= int(threshold):
                alerts.append(_alert_from_node(node, threshold))
        except (TypeError, ValueError):
            continue
    alerts.sort(key=lambda a: (a.get("danger_level") or 0), reverse=True)
    return alerts


def evaluate_and_dispatch(load_all_nodes, region_id_for_name):
    """
    Scan all nodes, match them against enabled subscriptions, and POST an alert
    payload to each matching webhook. Returns a summary of deliveries.
    """
    nodes = load_all_nodes() or []
    subs = [s for s in list_webhooks() if s.get("enabled")]

    deliveries = []
    matched_nodes = set()
    for sub in subs:
        matches = [n for n in nodes if _matches(sub, n, region_id_for_name)]
        if not matches:
            continue
        alerts = [_alert_from_node(n, sub.get("min_danger_level")) for n in matches]
        for a in alerts:
            matched_nodes.add(a["node_id"])
        payload = {
            "event": "fire_safety.alert",
            "generated_at": _now_iso(),
            "webhook_id": sub.get("id"),
            "threshold": sub.get("min_danger_level"),
            "region": sub.get("region"),
            "alert_count": len(alerts),
            "alerts": alerts,
        }
        deliveries.append(_deliver(sub, payload))

    return {
        "generated_at": _now_iso(),
        "enabled_webhooks": len(subs),
        "triggered_webhooks": len(deliveries),
        "matched_nodes": len(matched_nodes),
        "deliveries": deliveries,
    }


def test_webhook(webhook_id):
    """Send a sample payload to a single webhook to verify connectivity."""
    sub = get_webhook(webhook_id)
    if not sub:
        return None
    payload = {
        "event": "fire_safety.test",
        "generated_at": _now_iso(),
        "webhook_id": sub.get("id"),
        "message": "Δοκιμαστική ειδοποίηση από τον Πίνακα Πυρασφάλειας.",
        "alerts": [{
            "node_id": "N0_0",
            "title": "Δοκιμαστικός κόμβος",
            "location": "—",
            "region_id": sub.get("region"),
            "danger_level": MAX_LEVEL,
            "threshold": sub.get("min_danger_level"),
        }],
    }
    return _deliver(sub, payload)
