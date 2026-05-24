const canvas = document.getElementById("mapCanvas");
const ctx = canvas.getContext("2d");
const tooltip = document.getElementById("tooltip");
const summaryEl = document.getElementById("summary");
const patternSelect = document.getElementById("patternSelect");

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
  data.roads.forEach((way) => way.shape_points.forEach((point) => points.push(point)));
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

function selectedPattern() {
  const name = patternSelect.value;
  return state.data.source_patterns.find((pattern) => pattern.name === name) || state.data.source_patterns[0];
}

function drawRoads() {
  if (!document.getElementById("toggleRoads").checked) return;
  state.data.roads.forEach((way) => {
    if (!way.shape_points.length) return;
    ctx.beginPath();
    way.shape_points.forEach((point, index) => {
      const p = project(point.lat, point.lon);
      if (index === 0) ctx.moveTo(p.x, p.y);
      else ctx.lineTo(p.x, p.y);
    });
    ctx.lineWidth = Math.max(0.45, Math.min(3.5, 0.35 + (way.lane_count || 1) * 0.5));
    ctx.strokeStyle = "rgba(90, 102, 112, 0.26)";
    ctx.stroke();
  });
}

function drawSources(pattern) {
  if (!document.getElementById("toggleSources").checked) return;
  const maxSpawn = Math.max(1, ...pattern.sources.map((source) => source.spawn_count || 0));
  pattern.sources.forEach((source) => {
    const p = project(source.center.lat, source.center.lon);
    const radius = 2.5 + Math.sqrt(source.spawn_count / maxSpawn) * 14;
    ctx.beginPath();
    ctx.arc(p.x, p.y, radius, 0, Math.PI * 2);
    ctx.fillStyle = categoryColor[source.source_category] || "#495057";
    ctx.globalAlpha = 0.58;
    ctx.fill();
    ctx.globalAlpha = 1;
    state.hoverItems.push({
      x: p.x,
      y: p.y,
      r: radius + 4,
      text:
        `発生候補\nway: ${source.way_id}\n` +
        `category: ${source.source_category}\n` +
        `spawn_count: ${source.spawn_count}\n` +
        `road: ${source.road_type}\n` +
        `lane: ${source.lane_count}\n` +
        `speed: ${source.speed_limit_kmh}`,
    });
  });
}

function drawObservations() {
  if (!document.getElementById("toggleObservations").checked) return;
  state.data.observations.forEach((obs) => {
    const p = project(obs.lat, obs.lon);
    ctx.beginPath();
    ctx.arc(p.x, p.y, 7, 0, Math.PI * 2);
    ctx.fillStyle = "rgba(224, 49, 49, 0.8)";
    ctx.fill();
    ctx.lineWidth = 1.4;
    ctx.strokeStyle = "#fff";
    ctx.stroke();
    state.hoverItems.push({
      x: p.x,
      y: p.y,
      r: 12,
      text: `観測点\n${obs.point_name || obs.id}\nmatched_way: ${obs.matched_way_id}`,
    });
  });
}

function updateSummary(pattern) {
  const ratioLines = Object.entries(pattern.ratios)
    .map(([key, value]) => `${key}: ${value}`)
    .join("\n");
  const spawnLines = Object.entries(pattern.summary.category_spawn_counts)
    .map(([key, value]) => `${key}: ${value}`)
    .join("\n");
  const candidateLines = Object.entries(pattern.summary.category_candidate_counts)
    .map(([key, value]) => `${key}: ${value}`)
    .join("\n");
  summaryEl.textContent =
    `${pattern.name}\n${pattern.description}\n\n` +
    `road_pattern: ${state.data.meta.road_pattern}\n` +
    `target_active_cars: ${pattern.summary.target_active_cars}\n` +
    `source_way_count: ${pattern.summary.source_way_count}\n\n` +
    `ratios\n${ratioLines}\n\n` +
    `spawn counts\n${spawnLines}\n\n` +
    `candidate counts\n${candidateLines}`;
}

function draw() {
  if (!state.data) return;
  const pattern = selectedPattern();
  updateSummary(pattern);
  const rect = canvas.getBoundingClientRect();
  ctx.clearRect(0, 0, rect.width, rect.height);
  state.hoverItems = [];
  drawRoads();
  drawSources(pattern);
  drawObservations();
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

patternSelect.addEventListener("change", draw);
document.getElementById("toggleRoads").addEventListener("change", draw);
document.getElementById("toggleSources").addEventListener("change", draw);
document.getElementById("toggleObservations").addEventListener("change", draw);

fetch("./data/source_variants.json")
  .then((response) => response.json())
  .then((data) => {
    state.data = data;
    state.bounds = computeBounds(data);
    data.source_patterns.forEach((pattern) => {
      const option = document.createElement("option");
      option.value = pattern.name;
      option.textContent = pattern.name;
      patternSelect.appendChild(option);
    });
    resize();
  });

window.addEventListener("resize", resize);
