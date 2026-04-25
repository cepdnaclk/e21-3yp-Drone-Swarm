const cameraIds = [1, 2, 3, 4];
const trackerPlot = document.getElementById("trackerPlot");
const statusText = document.getElementById("statusText");
const statusDot = document.getElementById("statusDot");
const messageText = document.getElementById("messageText");
const coordX = document.getElementById("coord-x");
const coordY = document.getElementById("coord-y");
const coordZ = document.getElementById("coord-z");

const backendBase = `${window.location.protocol}//${window.location.host}`;

cameraIds.forEach((id) => {
  const img = document.getElementById(`cam-${id}-feed`);
  img.src = `${backendBase}/video/${id}`;
});

function setStatus(status) {
  statusText.textContent = status;
  statusDot.className = "status-dot";

  if (status === "tracking") {
    statusDot.classList.add("status-tracking");
  } else if (status === "waiting") {
    statusDot.classList.add("status-waiting");
  } else {
    statusDot.classList.add("status-error");
  }
}

function updateCameraBadges(cameras) {
  (cameras || []).forEach((camera) => {
    const badge = document.getElementById(`cam-${camera.camera_id}-badge`);
    if (!badge) {
      return;
    }

    if (camera.detected) {
      badge.textContent = "Locked";
      badge.className = "badge badge-live";
    } else {
      badge.textContent = "Scanning";
      badge.className = "badge badge-idle";
    }
  });
}

function updateCoordinates(point) {
  if (!point) {
    coordX.textContent = "--";
    coordY.textContent = "--";
    coordZ.textContent = "--";
    return;
  }

  coordX.textContent = `${point[0].toFixed(2)} m`;
  coordY.textContent = `${point[1].toFixed(2)} m`;
  coordZ.textContent = `${point[2].toFixed(2)} m`;
}

function refreshPlot() {
  trackerPlot.src = `${backendBase}/plot/3d?t=${Date.now()}`;
}

async function pollState() {
  try {
    const response = await fetch(`${backendBase}/api/state`, { cache: "no-store" });
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }

    const state = await response.json();
    setStatus(state.status || "waiting");
    messageText.textContent = state.message || "Tracker connected";
    updateCameraBadges(state.cameras);
    updateCoordinates(state.current_point);
    refreshPlot();
  } catch (_error) {
    setStatus("error");
    messageText.textContent = "Backend unavailable";
    updateCoordinates(null);
  }
}

refreshPlot();
pollState();
window.setInterval(pollState, 250);
