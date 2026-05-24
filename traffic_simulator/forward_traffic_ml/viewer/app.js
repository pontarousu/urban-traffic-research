const canvas = document.getElementById("mapCanvas");
const ctx = canvas.getContext("2d");
const tooltip = document.getElementById("tooltip");
const summaryEl = document.getElementById("summary");

const state = {
  data: null,
  bounds: null,
  hoverItems: [],
};

const categoryColor = {
  boundary_major: "#d9480f",
  boundary_minor: "#f08c00",
  internal_major: "#1971c2",
  internal_minor: "#5c940d",
};

function resize() {
  const rect = canvas.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  canvas.width = Math.max(1, Math.floor(rect.width * dpr));
  canvas.height = Math.max(1, Math.floor(rect.height * dpr));
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  draw();
}

function computeBounds(data) {
  const points = [];
  data.ways.forEach((way) => {
    way.shape_points.forEach((point) => points.push(point));
  });
  data.observations.forEach((obs) => points.push(obs));
  return {
    minLat: Math.min(...points.map((p) => p.lat)),
    maxLat: Math.max(...points.map((p) => p.lat)),
    minLon: Math.min(...points.map((p) => p.lon)),
    maxLon: Math.max(...points.map((p) => p.lon)),
  };
}

function project(lat, lon) {
  const rect = canvas.getBoundingClientRect();
  const padding = 28;
  const b = state.bounds;
  const x = padding + ((lon - b.minLon) / (b.maxLon - b.minLon || 1)) * (rect.width - padding * 2);
  const y = padding + ((b.maxLat - lat) / (b.maxLat - b.minLat || 1)) * (rect.height - padding * 2);
  return { x, y };
}

function option(id) {
  return document.getElementById(id).checked;
}

function drawRoads() {
  const maxFlow = Math.max(1, ...state.data.ways.map((way) => way.flow_count || 0));
  state.data.ways.forEach((way) => {
    if (!way.shape_points.length) return;
    ctx.beginPath();
    way.shape_points.forEach((point, index) => {
      const p = project(point.lat, point.lon);
      if (index === 0) ctx.moveTo(p.x, p.y);
      else ctx.lineTo(p.x, p.y);
    });
    const flowWidth = option("toggleFlow") ? Math.sqrt((way.flow_count || 0) / maxFlow) * 5 : 0;
    ctx.lineWidth = Math.max(0.4, 0.7 + flowWidth);
    ctx.strokeStyle = option("toggleFlow") && way.flow_count > 0 ? "rgba(36, 93, 145, 0.55)" : "rgba(113, 126, 138, 0.24)";
    ctx.stroke();
  });
}

function drawSources() {
  const maxSpawn = Math.max(1, ...state.data.ways.map((way) => way.spawn_count || 0));
  state.data.ways.forEach((way) => {
    if (!way.spawn_count) return;
    const p = project(way.center.lat, way.center.lon);
    const radius = 3 + Math.sqrt(way.spawn_count / maxSpawn) * 14;
    ctx.beginPath();
    ctx.arc(p.x, p.y, radius, 0, Math.PI * 2);
    ctx.fillStyle = categoryColor[way.source_category] || "#495057";
    ctx.globalAlpha = 0.58;
    ctx.fill();
    ctx.globalAlpha = 1;
    state.hoverItems.push({
      x: p.x,
      y: p.y,
      r: radius + 4,
      text: `発生源\nway: ${way.id}\ncategory: ${way.source_category}\nspawn: ${way.spawn_count}\nflow: ${way.flow_count}\nroad: ${way.road_type}\nlane: ${way.lane_count}`,
    });
  });
}

function drawObservations() {
  const maxAbs = Math.max(1, ...state.data.observations.map((obs) => Math.abs(obs.error_total || 0)));
  state.data.observations.forEach((obs) => {
    const p = project(obs.lat, obs.lon);
    const error = obs.error_total || 0;
    const radius = 6 + Math.sqrt(Math.abs(error) / maxAbs) * 20;
    ctx.beginPath();
    ctx.arc(p.x, p.y, radius, 0, Math.PI * 2);
    ctx.fillStyle = error < 0 ? "rgba(224,49,49,0.72)" : "rgba(24,100,171,0.72)";
    ctx.fill();
    ctx.lineWidth = 1.5;
    ctx.strokeStyle = "#ffffff";
    ctx.stroke();
    state.hoverItems.push({
      x: p.x,
      y: p.y,
      r: radius + 5,
      text: `観測点\n${obs.point_name || obs.id}\nobs: ${obs.observed_total}\nsim: ${obs.simulated_total}\nerror: ${obs.error_total}`,
    });
  });
}

function draw() {
  if (!state.data) return;
  const rect = canvas.getBoundingClientRect();
  ctx.clearRect(0, 0, rect.width, rect.height);
  state.hoverItems = [];
  if (option("toggleRoads")) drawRoads();
  if (option("toggleSources")) drawSources();
  if (option("toggleObservations")) drawObservations();
}

function updateSummary(data) {
  const sourceLines = Object.entries(data.summary.source_by_category || {})
    .map(([key, value]) => `${key}: ${value}`)
    .join("\n");
  const statusLines = Object.entries(data.summary.final_status || {})
    .map(([key, value]) => `${key}: ${value}`)
    .join("\n");
  summaryEl.textContent =
    `observed_total: ${data.summary.observed_total}\n` +
    `simulated_total: ${data.summary.simulated_total}\n` +
    `absolute_error_total: ${data.summary.absolute_error_total}\n\n` +
    `source_by_category\n${sourceLines}\n\n` +
    `final_status\n${statusLines}`;
}

canvas.addEventListener("mousemove", (event) => {
  const rect = canvas.getBoundingClientRect();
  const x = event.clientX - rect.left;
  const y = event.clientY - rect.top;
  const hit = state.hoverItems.find((item) => Math.hypot(item.x - x, item.y - y) <= item.r);
  if (!hit) {
    tooltip.style.display = "none";
    return;
  }
  tooltip.textContent = hit.text;
  tooltip.style.left = `${x + 14}px`;
  tooltip.style.top = `${y + 14}px`;
  tooltip.style.display = "block";
});

canvas.addEventListener("mouseleave", () => {
  tooltip.style.display = "none";
});

["toggleRoads", "toggleSources", "toggleFlow", "toggleObservations"].forEach((id) => {
  document.getElementById(id).addEventListener("change", draw);
});

fetch("./data/diagnostics.json")
  .then((response) => response.json())
  .then((data) => {
    state.data = data;
    state.bounds = computeBounds(data);
    updateSummary(data);
    resize();
  });

window.addEventListener("resize", resize);
