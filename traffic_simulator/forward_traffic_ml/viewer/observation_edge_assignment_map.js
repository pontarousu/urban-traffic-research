const canvas = document.getElementById("mapCanvas");
const ctx = canvas.getContext("2d");
const tooltip = document.getElementById("tooltip");
const summaryEl = document.getElementById("summary");
const zoomReadout = document.getElementById("zoomReadout");

const state = {
  data: null,
  hoverItems: [],
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
    const rate = Number(obs.error_rate || 0);
    if (filter === "under") return rate < 0;
    if (filter === "over") return rate > 0;
    if (filter === "large") return Math.abs(rate) >= 0.5;
    return true;
  });
}

function visibleEdgeIds() {
  return new Set(visibleObservations().map((obs) => obs.directed_edge_id));
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
    ctx.lineWidth = major ? 0.95 : 0.45;
    ctx.strokeStyle = major ? "rgba(70, 91, 109, 0.24)" : "rgba(91, 116, 139, 0.13)";
    ctx.stroke();
  });
}

function drawMatchedEdges() {
  const edgeIds = visibleEdgeIds();
  state.data.directed_edges
    .filter((edge) => edgeIds.has(edge.directed_edge_id))
    .forEach((edge) => {
      const points = edge.shape_points || [];
      if (points.length < 2) return;
      ctx.beginPath();
      points.forEach((point, index) => {
        const p = project(point.lat, point.lon);
        if (index === 0) ctx.moveTo(p.x, p.y);
        else ctx.lineTo(p.x, p.y);
      });
      ctx.lineWidth = 2.2;
      ctx.strokeStyle = "rgba(217, 72, 15, 0.78)";
      ctx.stroke();
      if (option("toggleArrows")) drawArrowOnShape(points, "rgba(217, 72, 15, 0.92)");
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
  const targets = total > 120 ? [0.35, 0.7] : [0.55];
  targets.forEach((ratio) => {
    let distance = total * ratio;
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
  });
}

function drawArrowHead(x, y, angle, color) {
  const size = 8;
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

function drawConnectors() {
  visibleObservations().forEach((obs) => {
    if (!obs.nearest_point) return;
    const a = project(obs.lat, obs.lon);
    const b = project(obs.nearest_point.lat, obs.nearest_point.lon);
    ctx.beginPath();
    ctx.moveTo(a.x, a.y);
    ctx.lineTo(b.x, b.y);
    ctx.lineWidth = 1.1;
    ctx.strokeStyle = "rgba(240, 140, 0, 0.58)";
    ctx.setLineDash([4, 4]);
    ctx.stroke();
    ctx.setLineDash([]);
  });
}

function drawPoints() {
  visibleObservations().forEach((obs) => {
    const p = project(obs.lat, obs.lon);
    const rate = Number(obs.error_rate || 0);
    const radius = 4 + Math.sqrt(Math.min(1.4, Math.abs(rate))) * 5;
    ctx.beginPath();
    ctx.arc(p.x, p.y, radius, 0, Math.PI * 2);
    ctx.fillStyle = colorFor(rate, 0.86);
    ctx.fill();
    ctx.strokeStyle = "rgba(255, 255, 255, 0.9)";
    ctx.lineWidth = 1.4;
    ctx.stroke();
    if (option("toggleLabels")) {
      ctx.font = "11px system-ui, sans-serif";
      ctx.fillStyle = "#1d252c";
      ctx.fillText(obs.point_number || obs.observation_id, p.x + radius + 4, p.y - radius - 1);
    }
    state.hoverItems.push({
      x: p.x,
      y: p.y,
      r: radius + 5,
      text:
        `${obs.point_name || obs.observation_id}\n` +
        `番号: ${obs.point_number || "-"}\n` +
        `directed_edge: ${obs.directed_edge_id}\n` +
        `topology_edge: ${obs.topology_edge_id || "-"}\n` +
        `road: ${obs.road_type || "-"} lane: ${obs.lane_count_total ?? "-"} speed: ${obs.speed_limit_kmh ?? "-"}\n` +
        `bearing: ${formatNumber(obs.bearing_deg)} deg\n` +
        `position_ratio: ${formatNumber(obs.position_ratio)}\n` +
        `match: ${obs.match_method || "-"} / ${obs.match_confidence || "-"}\n` +
        `error_rate: ${formatPercent(obs.error_rate)}\n` +
        `observed/sim: ${obs.observed_total ?? "-"} / ${obs.simulated_total ?? "-"}`,
    });
  });
}

function colorFor(errorRate, alpha) {
  if (errorRate < -0.1) return `rgba(25, 113, 194, ${alpha})`;
  if (errorRate > 0.1) return `rgba(224, 49, 49, ${alpha})`;
  return `rgba(240, 140, 0, ${alpha})`;
}

function draw() {
  if (!state.data) return;
  const rect = canvas.getBoundingClientRect();
  ctx.clearRect(0, 0, rect.width, rect.height);
  state.hoverItems = [];
  if (option("toggleRoads")) drawRoads();
  if (option("toggleMatchedEdges")) drawMatchedEdges();
  if (option("toggleConnectors")) drawConnectors();
  if (option("togglePoints")) drawPoints();
  updateSummary();
}

function updateSummary() {
  const s = state.data.summary;
  const visible = visibleObservations();
  const edgeCount = new Set(visible.map((obs) => obs.directed_edge_id)).size;
  const sameEdgeGroups = [...groupByEdge(visible).entries()].filter(([, items]) => items.length >= 2);
  summaryEl.textContent =
    `observations: ${s.observation_count}\n` +
    `matched directed_edges: ${s.matched_directed_edge_count}\n` +
    `visible observations: ${visible.length}\n` +
    `visible directed_edges: ${edgeCount}\n` +
    `same-edge groups: ${sameEdgeGroups.length}\n\n` +
    `confidence\n` +
    Object.entries(s.match_confidence_counts).map(([key, value]) => `${key}: ${value}`).join("\n") +
    `\n\nfilter: ${selectedFilter()}`;
}

function groupByEdge(observations) {
  const groups = new Map();
  observations.forEach((obs) => {
    if (!groups.has(obs.directed_edge_id)) groups.set(obs.directed_edge_id, []);
    groups.get(obs.directed_edge_id).push(obs);
  });
  return groups;
}

function formatNumber(value) {
  if (value === null || value === undefined) return "-";
  return Number(value).toFixed(3);
}

function formatPercent(value) {
  if (value === null || value === undefined) return "-";
  return `${(Number(value) * 100).toFixed(1)}%`;
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
  const factor = event.deltaY < 0 ? 1.15 : 1 / 1.15;
  zoomAt(x, y, state.view.scale * factor);
}, { passive: false });

document.getElementById("resetView").addEventListener("click", resetView);
document.getElementById("filterSelect").addEventListener("change", draw);
["toggleRoads", "toggleMatchedEdges", "toggleArrows", "toggleConnectors", "togglePoints", "toggleLabels"].forEach((id) => {
  document.getElementById(id).addEventListener("change", draw);
});

window.addEventListener("resize", resize);

fetch("./data/observation_edge_assignment_map.json")
  .then((response) => response.json())
  .then((data) => {
    state.data = data;
    updateZoomReadout();
    resize();
  })
  .catch((error) => {
    summaryEl.textContent = `読み込みに失敗しました: ${error.message}`;
  });
