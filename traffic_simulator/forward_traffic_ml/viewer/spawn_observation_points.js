const canvas = document.getElementById("mapCanvas");
const ctx = canvas.getContext("2d");
const tooltip = document.getElementById("tooltip");
const summaryEl = document.getElementById("summary");
const zoomReadout = document.getElementById("zoomReadout");

const state = {
  data: null,
  hoverItems: [],
  view: {
    scale: 1,
    offsetX: 0,
    offsetY: 0,
    isDragging: false,
    lastX: 0,
    lastY: 0,
  },
};

const minZoom = 0.5;
const maxZoom = 30;

function option(id) {
  return document.getElementById(id).checked;
}

function resize() {
  const rect = canvas.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  canvas.width = Math.max(1, Math.floor(rect.width * dpr));
  canvas.height = Math.max(1, Math.floor(rect.height * dpr));
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  draw();
}

function project(lat, lon) {
  const rect = canvas.getBoundingClientRect();
  const padding = 28;
  const b = state.data.bounds;
  const baseX = padding + ((lon - b.min_lon) / (b.max_lon - b.min_lon || 1)) * (rect.width - padding * 2);
  const baseY = padding + ((b.max_lat - lat) / (b.max_lat - b.min_lat || 1)) * (rect.height - padding * 2);
  return {
    x: baseX * state.view.scale + state.view.offsetX,
    y: baseY * state.view.scale + state.view.offsetY,
  };
}

function jitteredPoint(point) {
  const p = project(point.lat, point.lon);
  const angle = (point.vehicle_id * 137.508) * Math.PI / 180;
  const ring = Math.sqrt((point.edge_spawn_index - 1) % 24);
  const radius = Math.min(14, 2.2 + ring * 2.2);
  return {
    x: p.x + Math.cos(angle) * radius,
    y: p.y + Math.sin(angle) * radius,
  };
}

function drawRoads() {
  state.data.roads.forEach((road) => {
    if (!road.shape_points.length) return;
    ctx.beginPath();
    road.shape_points.forEach((point, index) => {
      const p = project(point.lat, point.lon);
      if (index === 0) ctx.moveTo(p.x, p.y);
      else ctx.lineTo(p.x, p.y);
    });
    ctx.lineWidth = road.road_type === "motorway" || road.road_type === "trunk" ? 1.2 : 0.65;
    ctx.strokeStyle = road.road_type === "motorway" ? "rgba(91, 116, 139, 0.42)" : "rgba(91, 116, 139, 0.24)";
    ctx.stroke();
  });
}

function visibleSpawns() {
  if (!option("toggleOnlyHitSpawns")) return state.data.spawn_points;
  return state.data.spawn_points.filter((point) => point.observation_trace_count > 0);
}

function drawSpawns() {
  visibleSpawns().forEach((point) => {
    const p = jitteredPoint(point);
    const hasHit = point.observation_trace_count > 0;
    const radius = hasHit ? 3.3 : 2.5;
    ctx.beginPath();
    ctx.arc(p.x, p.y, radius, 0, Math.PI * 2);
    ctx.fillStyle = hasHit ? "rgba(217, 72, 15, 0.82)" : "rgba(92, 148, 13, 0.62)";
    ctx.fill();
    ctx.strokeStyle = "rgba(255, 255, 255, 0.8)";
    ctx.lineWidth = 0.8;
    ctx.stroke();
    state.hoverItems.push({
      x: p.x,
      y: p.y,
      r: radius + 4,
      text:
        `発生車両\nvehicle: ${point.vehicle_id}\n` +
        `source_edge: ${point.source_edge_id}\n` +
        `edge_spawn: ${point.edge_spawn_index}/${point.edge_spawn_count}\n` +
        `road: ${point.road_type || "-"} lane: ${point.lane_count_total ?? "-"} speed: ${point.speed_limit_kmh ?? "-"}\n` +
        `obs_trace: ${point.observation_trace_count}\n` +
        `branch_trace: ${point.branch_trace_count}\n` +
        `final: ${point.final_status}`,
    });
  });
}

function drawObservations() {
  const maxObserved = Math.max(1, ...state.data.observations.map((obs) => obs.observed_total || 0));
  state.data.observations.forEach((obs) => {
    const p = project(obs.lat, obs.lon);
    const radius = 3 + Math.sqrt((obs.observed_total || 0) / maxObserved) * 4;
    ctx.beginPath();
    ctx.arc(p.x, p.y, radius, 0, Math.PI * 2);
    ctx.fillStyle = obs.has_direction_conflict_pair ? "rgba(217, 72, 15, 0.72)" : "rgba(25, 113, 194, 0.72)";
    ctx.fill();
    ctx.strokeStyle = "#ffffff";
    ctx.lineWidth = 1.4;
    ctx.stroke();
    if (option("toggleLabels")) {
      ctx.font = "11px system-ui, sans-serif";
      ctx.fillStyle = "#1d252c";
      ctx.fillText(obs.point_number || obs.observation_id, p.x + radius + 3, p.y - radius - 1);
    }
    state.hoverItems.push({
      x: p.x,
      y: p.y,
      r: radius + 4,
      text:
        `観測点\n${obs.point_name || obs.observation_id}\n` +
        `番号: ${obs.point_number || "-"}\n` +
        `matched_edge: ${obs.directed_edge_id || "-"}\n` +
        `method: ${obs.match_method || "-"} confidence: ${obs.match_confidence || "-"}\n` +
        `observed_total: ${obs.observed_total}`,
    });
  });
}

function draw() {
  if (!state.data) return;
  const rect = canvas.getBoundingClientRect();
  ctx.clearRect(0, 0, rect.width, rect.height);
  state.hoverItems = [];
  if (option("toggleRoads")) drawRoads();
  if (option("toggleSpawns")) drawSpawns();
  if (option("toggleObservations")) drawObservations();
}

function updateSummary() {
  const summary = state.data.summary;
  const categories = summary.source_category_counts || {};
  const statuses = summary.final_status_counts || {};
  summaryEl.textContent =
    `observations: ${summary.observation_count}\n` +
    `spawn vehicles: ${summary.spawn_vehicle_count}\n` +
    `spawn edges: ${summary.spawn_edge_count}\n` +
    `vehicles with obs trace: ${summary.vehicles_with_observation_trace}\n\n` +
    `source categories\n` +
    Object.entries(categories).map(([key, value]) => `${key}: ${value}`).join("\n") +
    `\n\nfinal status\n` +
    Object.entries(statuses).map(([key, value]) => `${key}: ${value}`).join("\n");
}

function updateZoomReadout() {
  zoomReadout.textContent = `${state.view.scale.toFixed(2)}x`;
}

function resetView() {
  state.view.scale = 1;
  state.view.offsetX = 0;
  state.view.offsetY = 0;
  updateZoomReadout();
  draw();
}

function zoomAt(x, y, nextScale) {
  const currentScale = state.view.scale;
  const clampedScale = Math.max(minZoom, Math.min(maxZoom, nextScale));
  const ratio = clampedScale / currentScale;
  state.view.offsetX = x - (x - state.view.offsetX) * ratio;
  state.view.offsetY = y - (y - state.view.offsetY) * ratio;
  state.view.scale = clampedScale;
  updateZoomReadout();
  draw();
}

canvas.addEventListener("mousemove", (event) => {
  const rect = canvas.getBoundingClientRect();
  const x = event.clientX - rect.left;
  const y = event.clientY - rect.top;
  if (state.view.isDragging) {
    state.view.offsetX += x - state.view.lastX;
    state.view.offsetY += y - state.view.lastY;
    state.view.lastX = x;
    state.view.lastY = y;
    tooltip.style.display = "none";
    draw();
    return;
  }
  const hit = state.hoverItems.find((item) => Math.hypot(item.x - x, item.y - y) <= item.r);
  if (!hit) {
    tooltip.style.display = "none";
    return;
  }
  tooltip.style.display = "block";
  tooltip.style.left = `${x + 14}px`;
  tooltip.style.top = `${y + 14}px`;
  tooltip.textContent = hit.text;
});

canvas.addEventListener("mousedown", (event) => {
  const rect = canvas.getBoundingClientRect();
  state.view.isDragging = true;
  state.view.lastX = event.clientX - rect.left;
  state.view.lastY = event.clientY - rect.top;
  canvas.classList.add("dragging");
});

window.addEventListener("mouseup", () => {
  state.view.isDragging = false;
  canvas.classList.remove("dragging");
});

canvas.addEventListener("wheel", (event) => {
  event.preventDefault();
  const rect = canvas.getBoundingClientRect();
  const x = event.clientX - rect.left;
  const y = event.clientY - rect.top;
  const factor = event.deltaY < 0 ? 1.18 : 0.84;
  zoomAt(x, y, state.view.scale * factor);
}, { passive: false });

document.getElementById("resetView").addEventListener("click", resetView);
["toggleRoads", "toggleObservations", "toggleSpawns", "toggleOnlyHitSpawns", "toggleLabels"].forEach((id) => {
  document.getElementById(id).addEventListener("change", draw);
});

window.addEventListener("resize", resize);

fetch("./data/spawn_observation_points.json")
  .then((response) => response.json())
  .then((data) => {
    state.data = data;
    updateSummary();
    resize();
  })
  .catch((error) => {
    summaryEl.textContent = `読み込みに失敗しました: ${error.message}`;
  });
