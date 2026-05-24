const drones = (window.DRONES || []).filter((d) => {
  const regionId = window.REGION_ID;
  if (!regionId || regionId === null) return true;
  const match = (d.drone_id || "").match(/^DRONE_(FR\d+)_/);
  return match && match[1] === regionId;
});
const region = window.REGION || "";

const map = L.map('map').setView([40.8, 23.5], 7);
L.tileLayer('https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png', {
  maxZoom: 17,
  attribution: 'Map data: &copy; OpenStreetMap | Map style: &copy; OpenTopoMap'
}).addTo(map);

function makeDroneIcon(selected) {
  const iconUrl = selected
    ? (window.DRONE_ICON_SELECTED_URL || window.DRONE_ICON_URL)
    : window.DRONE_ICON_URL;
  if (iconUrl) {
    return L.icon({
      iconUrl,
      iconSize: [44, 44],
      iconAnchor: [22, 22],
      popupAnchor: [0, -22],
      className: selected ? 'drone-map-icon drone-map-icon--selected' : 'drone-map-icon',
    });
  }
  return L.divIcon({
    className: selected ? 'drone-marker selected' : 'drone-marker',
    html: '<span class="drone-marker-fallback" aria-hidden="true">✈</span>',
    iconSize: [36, 36],
    iconAnchor: [18, 18],
  });
}

const markers = {};
let selectedDroneId = drones.length > 0 ? drones[0].drone_id : null;

function getInitialCoords(drone) {
  return [drone.home_lat || 40.95, drone.home_lng || 24.5];
}

function initMarkers() {
  drones.forEach(drone => {
    const coords = getInitialCoords(drone);
    const isSelected = drone.drone_id === selectedDroneId;
    const marker = L.marker(coords, {
      icon: makeDroneIcon(isSelected),
      zIndexOffset: isSelected ? 2000 : 1000
    }).addTo(map);
    marker.bindTooltip(drone.name || drone.drone_id, { direction: 'top', offset: [0, -12] });
    marker.on('click', () => selectDrone(drone.drone_id));
    markers[drone.drone_id] = marker;
  });
  if (drones.length > 0) {
    map.fitBounds(L.latLngBounds(drones.map(d => getInitialCoords(d))), { padding: [40, 40] });
  }
}

function selectDrone(droneId) {
  if (!droneId) return;
  selectedDroneId = droneId;
  document.querySelectorAll('.drone-list-item').forEach(item => {
    item.classList.toggle('selected', item.dataset.droneId === droneId);
  });
  Object.entries(markers).forEach(([id, marker]) => {
    marker.setIcon(makeDroneIcon(id === droneId));
    marker.setZIndexOffset(id === droneId ? 2000 : 1000);
  });
  updateSelectedTelemetry();
}

function bindListClicks() {
  document.querySelectorAll('.drone-list-item').forEach(item => {
    item.addEventListener('click', () => selectDrone(item.dataset.droneId));
  });
}

function updateListStats(liveDrones) {
  liveDrones.forEach(drone => {
    const item = document.querySelector(`.drone-list-item[data-drone-id="${drone.drone_id}"]`);
    if (!item) return;
    const batteryEl = item.querySelector('.battery-value');
    const fireEl = item.querySelector('.fire-value');
    if (batteryEl) batteryEl.textContent = `${drone.battery.percentage.toFixed(0)}%`;
    if (fireEl) {
      if (drone.fire_detection.detected) {
        fireEl.textContent = 'Ανίχνευση!';
        fireEl.className = 'fire-value fire-alert';
      } else {
        fireEl.textContent = 'Κανονική';
        fireEl.className = 'fire-value';
      }
    }
  });
}

function updateMarkerPositions(liveDrones) {
  liveDrones.forEach(drone => {
    const marker = markers[drone.drone_id];
    if (marker) marker.setLatLng([drone.location.lat, drone.location.lon]);
  });
}

function renderTelemetry(data) {
  document.getElementById('telemetry-drone-name').textContent = data.name || data.drone_id;
  document.getElementById('telemetry-drone-model').textContent = data.model || '';
  document.getElementById('location').textContent =
    `${data.location.lat.toFixed(4)}° N, ${data.location.lon.toFixed(4)}° E`;
  document.getElementById('altitude').textContent = `${data.location.altitude.toFixed(1)} m`;
  document.getElementById('speed').textContent = `${data.movement.speed.toFixed(1)} m/s`;
  document.getElementById('heading').textContent = `${data.movement.heading.toFixed(0)}°`;
  document.getElementById('battery').textContent =
    `${data.battery.percentage.toFixed(0)}% (${data.battery.voltage.toFixed(1)}V)`;
  const fireStatus = document.getElementById('fire-status');
  if (data.fire_detection.detected) {
    fireStatus.textContent =
      `Ανίχνευση Πυρκαγιάς! (Εμπιστοσύνη: ${(data.fire_detection.confidence * 100).toFixed(0)}%)`;
    fireStatus.className = 'fire-alert';
  } else {
    fireStatus.textContent = 'Κανονική κατάσταση';
    fireStatus.className = '';
  }
}

function filterDronesByRegion(list) {
  const regionId = window.REGION_ID;
  if (!regionId) return list || [];
  return (list || []).filter((d) => {
    const match = (d.drone_id || "").match(/^DRONE_(FR\d+)_/);
    return match && match[1] === regionId;
  });
}

async function fetchAllDrones() {
  try {
    const response = await fetch(`/api/drones?region=${encodeURIComponent(region)}`);
    if (!response.ok) {
      console.error("Error fetching drones:", response.status);
      return [];
    }
    const data = await response.json();
    return filterDronesByRegion(data.drones || []);
  } catch (e) {
    console.error("Error fetching drones:", e);
    return [];
  }
}

async function fetchDroneTelemetry(droneId) {
  try {
    const response = await fetch(`/api/drone_telemetry/${encodeURIComponent(droneId)}`);
    if (!response.ok) return null;
    return await response.json();
  } catch (e) {
    console.error('Error fetching telemetry:', e);
    return null;
  }
}

async function updateSelectedTelemetry() {
  if (!selectedDroneId) return;
  const data = await fetchDroneTelemetry(selectedDroneId);
  if (data) {
    renderTelemetry(data);
    const marker = markers[selectedDroneId];
    if (marker) map.panTo([data.location.lat, data.location.lon]);
  }
}

async function updateAllDrones() {
  const liveDrones = await fetchAllDrones();
  if (!liveDrones) return;
  updateMarkerPositions(liveDrones);
  updateListStats(liveDrones);
  if (selectedDroneId) {
    const selected = liveDrones.find(d => d.drone_id === selectedDroneId);
    if (selected) renderTelemetry(selected);
  }
}

initMarkers();
bindListClicks();
if (selectedDroneId) updateSelectedTelemetry();
setInterval(updateAllDrones, 2000);
