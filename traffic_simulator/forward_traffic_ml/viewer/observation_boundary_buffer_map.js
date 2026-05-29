const canvas = document.getElementById("mapCanvas");
const ctx = canvas.getContext("2d");
const tooltip = document.getElementById("tooltip");
const summaryEl = document.getElementById("summary");
const zoomReadout = document.getElementById("zoomReadout");

const state = {
  data: null,
  hoverItems: [],
  hoverPointNumber: null,
  searchPointNumbers: new Set(),
  view: { scale: 1, offsetX: 0, offsetY: 0, isDragging: false, lastX: 0, lastY: 0 },
};

const minZoom = 0.5;
const maxZoom = 40;

function option(id) {
  return document.getElementById(id).checked;
}

function selectedFilter() {
  return document.getElementById("filterSelect").value;
}

function searchedPointNumbers() {
  const input = document.getElementById("pointSearchInput");
  return new Set(
    input.value
      .split(/[,\s]+/)
      .map((value) => value.trim())
      .filter(Boolean)
  );
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
  return { x: baseX * state.view.scale + state.view.offsetX, y: baseY * state.view.scale + state.view.offsetY };
}

function visibleObservations() {
  const filter = selectedFilter();
  return state.data.observations.filter((obs) => {
    if (state.searchPointNumbers.size > 0 && !state.searchPointNumbers.has(String(obs.point_number))) {
      return false;
    }
    const distance = Number(obs.boundary_distance_meter);
    if (filter === "lt500") return distance < 500;
    if (filter === "lt1000") return distance < 1000;
    if (filter === "eval") return obs.observed_total !== null && obs.observed_total !== undefined;
    if (filter === "simZero") return Number(obs.observed_total || 0) > 0 && Number(obs.simulated_total || 0) === 0;
    return true;
  });
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
    const major = ["motorway", "trunk", "primary", "secondary"].includes(road.road_type);
    ctx.lineWidth = major ? 0.9 : 0.4;
    ctx.strokeStyle = major ? "rgba(70, 91, 109, 0.22)" : "rgba(91, 116, 139, 0.11)";
    ctx.stroke();
  });
}

function drawBounds() {
  const b = state.data.map_bounds;
  drawShape(
    [
      { lat: b.min_lat, lon: b.min_lon },
      { lat: b.min_lat, lon: b.max_lon },
      { lat: b.max_lat, lon: b.max_lon },
      { lat: b.max_lat, lon: b.min_lon },
      { lat: b.min_lat, lon: b.min_lon },
    ],
    "rgba(33, 37, 41, 0.85)",
    2.2,
    []
  );
}

function drawBuffers() {
  state.data.buffer_lines.forEach((line) => {
    const threshold = Number(line.threshold_meter);
    const color = threshold === 500 ? "rgba(224, 49, 49, 0.88)" : "rgba(240, 140, 0, 0.88)";
    drawShape(line.shape_points, color, 2.0, threshold === 500 ? [8, 5] : [3, 5]);
    const labelPoint = project(line.shape_points[2].lat, line.shape_points[2].lon);
    ctx.font = "12px system-ui, sans-serif";
    ctx.fillStyle = color;
    ctx.fillText(`${threshold.toFixed(0)}m`, labelPoint.x - 44, labelPoint.y + 16);
  });
}

function visiblePointNumbers() {
  if (state.searchPointNumbers.size > 0) {
    return new Set(visibleObservations().map((obs) => obs.point_number).filter(Boolean));
  }
  if (option("toggleHoverEdges")) {
    return new Set(state.hoverPointNumber ? [state.hoverPointNumber] : []);
  }
  return new Set(visibleObservations().map((obs) => obs.point_number).filter(Boolean));
}

function drawMatchedEdges() {
  drawEdgeLayer({
    edges: state.data.matched_edges || [],
    color: "rgba(217, 72, 15, 0.86)",
    width: 2.4,
    dash: [],
    label: "matched",
  });
}

function drawConnectedEdges() {
  drawEdgeLayer({
    edges: state.data.connected_edges || [],
    color: "rgba(32, 120, 110, 0.52)",
    width: 1.8,
    dash: [6, 5],
    label: "connected",
  });
}

function drawEdgeLayer({ edges, color, width, dash, label }) {
  const pointNumbers = visiblePointNumbers();
  edges
    .filter((edge) => (edge.point_numbers || []).some((pointNumber) => pointNumbers.has(pointNumber)))
    .forEach((edge) => {
      const points = edge.shape_points || [];
      if (points.length < 2) return;
      drawShape(points, color, width, dash);
      if (option("toggleArrows")) drawArrowOnShape(points, color);
      const midpoint = project(points[Math.floor(points.length / 2)].lat, points[Math.floor(points.length / 2)].lon);
      state.hoverItems.push({
        kind: "edge",
        x: midpoint.x,
        y: midpoint.y,
        r: 8,
        text:
          `${label} edge\n` +
          `directed_edge: ${edge.directed_edge_id}\n` +
          `topology_edge: ${edge.topology_edge_id || "-"}\n` +
          `road: ${edge.road_type || "-"} lane: ${edge.lane_count_total ?? "-"} speed: ${edge.speed_limit_kmh ?? "-"}\n` +
          `length: ${formatNumber(edge.length_meter)} m\n` +
          `points: ${(edge.point_numbers || []).join(", ")}\n` +
          `relations: ${(edge.relations || []).join(", ") || "-"}`,
      });
    });
}

function drawArrowOnShape(points, color) {
  const segments = [];
  let total = 0;
  for (let index = 0; index < points.length - 1; index += 1) {
    const a = project(points[index].lat, points[index].lon);
    const b = project(points[index + 1].lat, points[index + 1].lon);
    const length = Math.hypot(b.x - a.x, b.y - a.y);
    if (length <= 0) continue;
    segments.push({ a, b, length });
    total += length;
  }
  if (!segments.length) return;
  const target = total * 0.55;
  let distance = target;
  let segment = segments[segments.length - 1];
  for (const candidate of segments) {
    if (distance <= candidate.length) {
      segment = candidate;
      break;
    }
    distance -= candidate.length;
  }
  const t = Math.max(0, Math.min(1, distance / segment.length));
  const x = segment.a.x + (segment.b.x - segment.a.x) * t;
  const y = segment.a.y + (segment.b.y - segment.a.y) * t;
  const angle = Math.atan2(segment.b.y - segment.a.y, segment.b.x - segment.a.x);
  drawArrowHead(x, y, angle, color);
}

function drawArrowHead(x, y, angle, color) {
  const size = 7;
  ctx.save();
  ctx.translate(x, y);
  ctx.rotate(angle);
  ctx.beginPath();
  ctx.moveTo(size, 0);
  ctx.lineTo(-size * 0.7, -size * 0.55);
  ctx.lineTo(-size * 0.7, size * 0.55);
  ctx.closePath();
  ctx.fillStyle = color;
  ctx.fill();
  ctx.restore();
}

function drawShape(points, color, width, dash) {
  if (!points.length) return;
  ctx.beginPath();
  points.forEach((point, index) => {
    const p = project(point.lat, point.lon);
    if (index === 0) ctx.moveTo(p.x, p.y);
    else ctx.lineTo(p.x, p.y);
  });
  ctx.lineWidth = width;
  ctx.strokeStyle = color;
  ctx.setLineDash(dash);
  ctx.stroke();
  ctx.setLineDash([]);
}

function drawPoints() {
  visibleObservations().forEach((obs) => {
    const p = project(obs.lat, obs.lon);
    const distance = Number(obs.boundary_distance_meter);
    const simZero = Number(obs.observed_total || 0) > 0 && Number(obs.simulated_total || 0) === 0;
    const searched = state.searchPointNumbers.has(String(obs.point_number));
    const radius = searched ? 9 : simZero ? 7 : distance < 500 ? 5.5 : distance < 1000 ? 4.7 : 3.7;
    ctx.beginPath();
    ctx.arc(p.x, p.y, radius, 0, Math.PI * 2);
    ctx.fillStyle = colorForObservation(obs);
    ctx.fill();
    ctx.strokeStyle = searched ? "rgba(250, 176, 5, 0.98)" : simZero ? "rgba(20, 20, 20, 0.95)" : "rgba(255, 255, 255, 0.88)";
    ctx.lineWidth = searched ? 3.0 : simZero ? 2.0 : 1.2;
    ctx.stroke();
    if (option("toggleLabels")) {
      ctx.font = "11px system-ui, sans-serif";
      ctx.fillStyle = "#1d252c";
      ctx.fillText(obs.point_number || obs.observation_id, p.x + radius + 4, p.y - radius - 1);
    }
    state.hoverItems.push({
      kind: "observation",
      pointNumber: obs.point_number,
      x: p.x,
      y: p.y,
      r: radius + 5,
      text:
        `${obs.point_name || obs.observation_id}\n` +
        `番号: ${obs.point_number || "-"}\n` +
        `boundary: ${formatNumber(obs.boundary_distance_meter)} m\n` +
        `directed_edge: ${obs.directed_edge_id || "-"}\n` +
        `position_ratio: ${formatNumber(obs.position_ratio)}\n` +
        `edge distance: ${formatNumber(obs.distance_meter)} m\n` +
        `match: ${obs.match_method || "-"} / ${obs.match_confidence || "-"} / ${obs.alignment_status || "-"}\n` +
        `observed/sim: ${obs.observed_total ?? "-"} / ${obs.simulated_total ?? "-"}\n` +
        `error_rate: ${formatPercent(obs.error_rate)}`,
    });
  });
}

function colorForObservation(obs) {
  const distance = Number(obs.boundary_distance_meter);
  const simZero = Number(obs.observed_total || 0) > 0 && Number(obs.simulated_total || 0) === 0;
  if (simZero) return "rgba(80, 43, 120, 0.9)";
  if (distance < 500) return "rgba(224, 49, 49, 0.86)";
  if (distance < 1000) return "rgba(240, 140, 0, 0.86)";
  return "rgba(25, 113, 194, 0.82)";
}

function draw() {
  if (!state.data) return;
  const rect = canvas.getBoundingClientRect();
  ctx.clearRect(0, 0, rect.width, rect.height);
  state.hoverItems = [];
  if (option("toggleRoads")) drawRoads();
  if (option("toggleBounds")) drawBounds();
  if (option("toggleBuffers")) drawBuffers();
  if (option("toggleConnectedEdges")) drawConnectedEdges();
  if (option("toggleMatchedEdges")) drawMatchedEdges();
  if (option("togglePoints")) drawPoints();
  updateSummary();
}

function updateSummary() {
  const s = state.data.summary;
  const visible = visibleObservations();
  const t500 = s.thresholds["500"];
  const t1000 = s.thresholds["1000"];
  const simZero = state.data.observations.filter(
    (obs) => Number(obs.observed_total || 0) > 0 && Number(obs.simulated_total || 0) === 0
  ).length;
  const missingSearches = [...state.searchPointNumbers].filter(
    (pointNumber) => !state.data.observations.some((obs) => String(obs.point_number) === pointNumber)
  );
  summaryEl.textContent =
    `observations: ${s.observation_count}\n` +
    `evaluation observations: ${s.evaluation_observation_count}\n` +
    `visible: ${visible.length}\n` +
    `search: ${[...state.searchPointNumbers].join(", ") || "-"}\n` +
    `missing search: ${missingSearches.join(", ") || "-"}\n` +
    `matched edges: ${s.matched_edge_count}\n` +
    `connected edges: ${s.connected_edge_count}\n` +
    `sim=0 observations: ${simZero}\n\n` +
    `boundary < 500m\n` +
    `  all: ${t500.excluded_all_count} excluded / ${t500.included_all_count} included\n` +
    `  eval: ${t500.excluded_evaluation_count} excluded / ${t500.included_evaluation_count} included\n\n` +
    `boundary < 1000m\n` +
    `  all: ${t1000.excluded_all_count} excluded / ${t1000.included_all_count} included\n` +
    `  eval: ${t1000.excluded_evaluation_count} excluded / ${t1000.included_evaluation_count} included`;
  zoomReadout.textContent = `${state.view.scale.toFixed(2)}x`;
}

function resetView() {
  state.view.scale = 1;
  state.view.offsetX = 0;
  state.view.offsetY = 0;
  draw();
}

function showPointSearch() {
  state.searchPointNumbers = searchedPointNumbers();
  state.hoverPointNumber = null;
  if (state.searchPointNumbers.size === 0) {
    resetView();
    return;
  }
  centerOnVisibleObservations();
  draw();
}

function clearPointSearch() {
  document.getElementById("pointSearchInput").value = "";
  state.searchPointNumbers = new Set();
  state.hoverPointNumber = null;
  resetView();
}

function centerOnVisibleObservations() {
  const observations = visibleObservations();
  if (!observations.length) return;
  const rect = canvas.getBoundingClientRect();
  const centerLat = observations.reduce((sum, obs) => sum + obs.lat, 0) / observations.length;
  const centerLon = observations.reduce((sum, obs) => sum + obs.lon, 0) / observations.length;
  const currentScale = Math.max(state.view.scale, observations.length <= 3 ? 14 : 8);
  state.view.scale = Math.min(maxZoom, currentScale);
  state.view.offsetX = 0;
  state.view.offsetY = 0;
  const projected = project(centerLat, centerLon);
  state.view.offsetX = rect.width / 2 - projected.x;
  state.view.offsetY = rect.height / 2 - projected.y;
}

function formatNumber(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "-";
  return Number(value).toFixed(2);
}

function formatPercent(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "-";
  return `${(Number(value) * 100).toFixed(1)}%`;
}

canvas.addEventListener("wheel", (event) => {
  if (!state.data) return;
  event.preventDefault();
  const rect = canvas.getBoundingClientRect();
  const mouseX = event.clientX - rect.left;
  const mouseY = event.clientY - rect.top;
  const oldScale = state.view.scale;
  const factor = event.deltaY < 0 ? 1.15 : 1 / 1.15;
  const newScale = Math.max(minZoom, Math.min(maxZoom, oldScale * factor));
  const baseX = (mouseX - state.view.offsetX) / oldScale;
  const baseY = (mouseY - state.view.offsetY) / oldScale;
  state.view.scale = newScale;
  state.view.offsetX = mouseX - baseX * newScale;
  state.view.offsetY = mouseY - baseY * newScale;
  draw();
});

canvas.addEventListener("mousedown", (event) => {
  state.view.isDragging = true;
  state.view.lastX = event.clientX;
  state.view.lastY = event.clientY;
});

window.addEventListener("mouseup", () => {
  state.view.isDragging = false;
});

window.addEventListener("mousemove", (event) => {
  if (state.view.isDragging) {
    state.view.offsetX += event.clientX - state.view.lastX;
    state.view.offsetY += event.clientY - state.view.lastY;
    state.view.lastX = event.clientX;
    state.view.lastY = event.clientY;
    draw();
    return;
  }
  const rect = canvas.getBoundingClientRect();
  const x = event.clientX - rect.left;
  const y = event.clientY - rect.top;
  const observationHit = state.hoverItems.find(
    (item) => item.kind === "observation" && Math.hypot(item.x - x, item.y - y) <= item.r
  );
  const hit = observationHit || state.hoverItems.find((item) => Math.hypot(item.x - x, item.y - y) <= item.r);
  const nextHoverPointNumber = observationHit?.pointNumber || null;
  if (option("toggleHoverEdges") && nextHoverPointNumber !== state.hoverPointNumber) {
    state.hoverPointNumber = nextHoverPointNumber;
    draw();
  }
  if (!hit) {
    tooltip.style.display = "none";
    return;
  }
  tooltip.style.display = "block";
  tooltip.style.left = `${x + 14}px`;
  tooltip.style.top = `${y + 14}px`;
  tooltip.textContent = hit.text;
});

document.getElementById("resetView").addEventListener("click", resetView);
document.getElementById("showPoint").addEventListener("click", showPointSearch);
document.getElementById("clearPoint").addEventListener("click", clearPointSearch);
document.getElementById("pointSearchInput").addEventListener("keydown", (event) => {
  if (event.key === "Enter") showPointSearch();
  if (event.key === "Escape") clearPointSearch();
});
document.querySelectorAll("input, select").forEach((item) => item.addEventListener("change", draw));
window.addEventListener("resize", resize);

fetch("./data/observation_boundary_buffer_map.json")
  .then((response) => {
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return response.json();
  })
  .then((data) => {
    state.data = data;
    resize();
  })
  .catch((error) => {
    summaryEl.textContent = `読み込みに失敗しました: ${error.message}`;
  });
