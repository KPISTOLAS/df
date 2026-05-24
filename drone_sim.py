"""
In-memory per-drone telemetry simulator with random walk movement.
"""
import math
import random
import time
from typing import Any, Dict, Optional

_drone_states: Dict[str, Dict[str, Any]] = {}


def _safe_float(value, default: float) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _distance_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    dlat = (lat2 - lat1) * 111.0
    dlng = (lng2 - lng1) * 111.0 * math.cos(math.radians((lat1 + lat2) / 2))
    return math.sqrt(dlat ** 2 + dlng ** 2)


def init_drone(drone_id: str, home_lat: float, home_lng: float) -> None:
    if drone_id in _drone_states:
        return
    _drone_states[drone_id] = {
        "lat": home_lat,
        "lng": home_lng,
        "altitude": random.uniform(45, 55),
        "speed": random.uniform(4, 6),
        "heading": random.uniform(0, 360),
        "battery_percentage": random.uniform(70, 100),
        "battery_voltage": random.uniform(10.8, 12.6),
        "fire_detected": False,
        "fire_confidence": 0.0,
        "fire_temperature": 0.0,
        "last_update": time.time(),
    }


def step(drone_id: str, home_lat: float, home_lng: float, roam_radius_km: float = 2.0) -> None:
    if drone_id not in _drone_states:
        init_drone(drone_id, home_lat, home_lng)
    state = _drone_states[drone_id]
    movement_range = 0.0008
    state["lat"] += random.uniform(-movement_range, movement_range)
    state["lng"] += random.uniform(-movement_range, movement_range)
    dist = _distance_km(state["lat"], state["lng"], home_lat, home_lng)
    if dist > roam_radius_km:
        ratio = roam_radius_km / dist if dist > 0 else 1.0
        state["lat"] = home_lat + (state["lat"] - home_lat) * ratio
        state["lng"] = home_lng + (state["lng"] - home_lng) * ratio
    state["altitude"] = max(40, min(80, state["altitude"] + random.uniform(-2, 2)))
    state["speed"] = max(3, min(10, state["speed"] + random.uniform(-0.5, 0.5)))
    state["heading"] = (state["heading"] + random.uniform(-15, 15)) % 360
    state["battery_percentage"] = max(0, state["battery_percentage"] - random.uniform(0.05, 0.15))
    state["battery_voltage"] = max(9.0, 12.6 * (state["battery_percentage"] / 100))
    if random.random() < 0.05:
        state["fire_detected"] = True
        state["fire_confidence"] = random.uniform(0.7, 0.95)
        state["fire_temperature"] = random.uniform(200, 350)
    else:
        state["fire_detected"] = False
        state["fire_confidence"] = 0.0
        state["fire_temperature"] = random.uniform(20, 35)
    state["last_update"] = time.time()


def snapshot(drone_id: str, drone_meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if drone_id not in _drone_states:
        meta = drone_meta or {}
        init_drone(drone_id, meta.get("home_lat", 40.95), meta.get("home_lng", 24.5))
    state = _drone_states[drone_id]
    meta = drone_meta or {}
    return {
        "drone_id": drone_id,
        "name": meta.get("name", drone_id),
        "model": meta.get("model", "Unknown"),
        "operational_status": meta.get("operational_status", "active"),
        "location": {"lat": state["lat"], "lon": state["lng"], "altitude": state["altitude"]},
        "movement": {"speed": state["speed"], "heading": state["heading"]},
        "battery": {"percentage": state["battery_percentage"], "voltage": state["battery_voltage"]},
        "fire_detection": {
            "detected": state["fire_detected"],
            "confidence": state["fire_confidence"],
            "temperature": state["fire_temperature"],
        },
        "last_update": float(state["last_update"]),
    }


def step_all(drones: list) -> None:
    for drone in drones or []:
        drone_id = drone.get("drone_id")
        if not drone_id:
            continue
        step(
            drone_id,
            _safe_float(drone.get("home_lat"), 40.95),
            _safe_float(drone.get("home_lng"), 24.5),
            _safe_float(drone.get("roam_radius_km"), 2.0),
        )
