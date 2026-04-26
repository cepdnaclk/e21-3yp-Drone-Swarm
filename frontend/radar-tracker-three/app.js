import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";

const cameraIds = [1, 2, 3, 4];
const backendBase = `${window.location.protocol}//${window.location.host}`;
const statusText = document.getElementById("statusText");
const statusDot = document.getElementById("statusDot");
const messageText = document.getElementById("messageText");
const coordX = document.getElementById("coord-x");
const coordY = document.getElementById("coord-y");
const coordZ = document.getElementById("coord-z");
const trackerScene = document.getElementById("trackerScene");

cameraIds.forEach((id) => {
  const img = document.getElementById(`cam-${id}-feed`);
  img.src = `${backendBase}/video/${id}`;
});

const scene = new THREE.Scene();
scene.background = new THREE.Color(0x08131f);
scene.fog = new THREE.Fog(0x08131f, 12, 30);

const renderer = new THREE.WebGLRenderer({ antialias: true });
renderer.setPixelRatio(window.devicePixelRatio);
trackerScene.appendChild(renderer.domElement);

const camera = new THREE.PerspectiveCamera(46, 1, 0.1, 100);
camera.position.set(10, 8, 10);

const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;
controls.target.set(0, 1.5, 0);

const ambientLight = new THREE.AmbientLight(0xffffff, 0.52);
scene.add(ambientLight);

const keyLight = new THREE.DirectionalLight(0x8fdcff, 1.0);
keyLight.position.set(8, 12, 4);
scene.add(keyLight);

const fillLight = new THREE.DirectionalLight(0x8cff9e, 0.45);
fillLight.position.set(-6, 8, -4);
scene.add(fillLight);

const floorGrid = new THREE.GridHelper(10, 10, 0x56d4ff, 0x2a5068);
scene.add(floorGrid);

const axesHelper = new THREE.AxesHelper(6);
scene.add(axesHelper);

const axisLabels = createAxisLabels();
axisLabels.forEach((label) => scene.add(label));

const cameraMarkerGroup = new THREE.Group();
scene.add(cameraMarkerGroup);

const trailMaterial = new THREE.LineBasicMaterial({
  color: 0xff6b6b,
  transparent: true,
  opacity: 0.75,
});
const trailGeometry = new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(0, 0, 0)]);
const trailLine = new THREE.Line(trailGeometry, trailMaterial);
scene.add(trailLine);

const pointGeometry = new THREE.SphereGeometry(0.18, 24, 24);
const pointMaterial = new THREE.MeshStandardMaterial({
  color: 0x8cff9e,
  emissive: 0x2d8f4a,
  emissiveIntensity: 1.5,
});
const livePoint = new THREE.Mesh(pointGeometry, pointMaterial);
livePoint.visible = false;
scene.add(livePoint);

const glowGeometry = new THREE.SphereGeometry(0.34, 24, 24);
const glowMaterial = new THREE.MeshBasicMaterial({
  color: 0x8cff9e,
  transparent: true,
  opacity: 0.18,
});
const glowPoint = new THREE.Mesh(glowGeometry, glowMaterial);
glowPoint.visible = false;
scene.add(glowPoint);

function createAxisLabels() {
  const labels = [
    { text: "X", color: "#ff7d7d", position: new THREE.Vector3(5.8, 0.1, 0) },
    { text: "Y", color: "#8cff9e", position: new THREE.Vector3(0, 0.1, 5.8) },
    { text: "Z", color: "#7db7ff", position: new THREE.Vector3(0, 5.8, 0) },
  ];

  return labels.map((entry) => {
    const sprite = new THREE.Sprite(
      new THREE.SpriteMaterial({ map: makeLabelTexture(entry.text, entry.color), transparent: true })
    );
    sprite.position.copy(entry.position);
    sprite.scale.set(0.9, 0.45, 1);
    return sprite;
  });
}

function makeLabelTexture(text, color) {
  const canvas = document.createElement("canvas");
  canvas.width = 256;
  canvas.height = 128;
  const ctx = canvas.getContext("2d");
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.font = "700 64px Space Grotesk";
  ctx.fillStyle = color;
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillText(text, canvas.width / 2, canvas.height / 2);
  const texture = new THREE.CanvasTexture(canvas);
  texture.needsUpdate = true;
  return texture;
}

function makeCameraMarker(labelText) {
  const group = new THREE.Group();

  const cone = new THREE.Mesh(
    new THREE.ConeGeometry(0.16, 0.48, 6),
    new THREE.MeshStandardMaterial({ color: 0x56d4ff, emissive: 0x144b5f, emissiveIntensity: 0.9 })
  );
  // Make the cone point along the group's local +Z axis.
  cone.rotation.x = Math.PI / 2;
  // Put the cone tip at the group origin so the tip marks the camera position.
  cone.position.set(0, 0, -0.24);
  group.add(cone);

  const sprite = new THREE.Sprite(
    new THREE.SpriteMaterial({ map: makeLabelTexture(labelText, "#9fe7ff"), transparent: true })
  );
  sprite.position.set(0.45, 0.35, 0);
  sprite.scale.set(1.2, 0.42, 1);
  group.add(sprite);

  return group;
}

function mapDirection(vector) {
  return new THREE.Vector3(vector[0], vector[2], vector[1]);
}

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

function mapPoint(point) {
  return new THREE.Vector3(point[0], point[2], point[1]);
}

function updateTrail(pathHistory) {
  if (!pathHistory || pathHistory.length === 0) {
    trailGeometry.setFromPoints([new THREE.Vector3(0, 0, 0)]);
    livePoint.visible = false;
    glowPoint.visible = false;
    return;
  }

  const vertices = pathHistory.map(mapPoint);
  trailGeometry.setFromPoints(vertices);

  const latest = vertices[vertices.length - 1];
  livePoint.position.copy(latest);
  glowPoint.position.copy(latest);
  livePoint.visible = true;
  glowPoint.visible = true;
}

function updateCameraMarkers(cameraPositions, cameraOrientations) {
  while (cameraMarkerGroup.children.length) {
    const child = cameraMarkerGroup.children[0];
    cameraMarkerGroup.remove(child);
  }

  (cameraPositions || []).forEach((cameraPosition, index) => {
    const marker = makeCameraMarker(`Cam ${index + 1}`);
    marker.position.copy(mapPoint(cameraPosition));
    const orientation = cameraOrientations?.[index];
    if (orientation?.forward && orientation?.up && orientation?.right) {
      const right = mapDirection(orientation.right).normalize();
      const forward = mapDirection(orientation.forward).normalize();
      const up = mapDirection(orientation.up).normalize();
      const basis = new THREE.Matrix4().makeBasis(right, up, forward);
      marker.quaternion.setFromRotationMatrix(basis);
    }
    cameraMarkerGroup.add(marker);
  });
}

function updateCameraBadges(cameras) {
  (cameras || []).forEach((cameraData) => {
    const badge = document.getElementById(`cam-${cameraData.camera_id}-badge`);
    if (!badge) {
      return;
    }

    if (cameraData.detected) {
      badge.textContent = "Locked";
      badge.className = "badge badge-live";
    } else {
      badge.textContent = "Scanning";
      badge.className = "badge badge-idle";
    }
  });
}

function resizeRenderer() {
  const width = trackerScene.clientWidth;
  const height = trackerScene.clientHeight;
  renderer.setSize(width, height, false);
  camera.aspect = width / height;
  camera.updateProjectionMatrix();
}

function animate() {
  requestAnimationFrame(animate);
  controls.update();
  renderer.render(scene, camera);
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
    updateCoordinates(state.current_point);
    updateCameraBadges(state.cameras);
    updateCameraMarkers(state.camera_positions, state.camera_orientations);
    updateTrail(state.path_history || []);
  } catch (_error) {
    setStatus("error");
    messageText.textContent = "Backend unavailable";
    updateCoordinates(null);
    updateCameraBadges([]);
    updateCameraMarkers([], []);
    updateTrail([]);
  }
}

window.addEventListener("resize", resizeRenderer);

resizeRenderer();
animate();
pollState();
window.setInterval(pollState, 120);
