const canvas = document.getElementById("mapCanvas");
const ctx = canvas.getContext("2d");
const tooltip = document.getElementById("tooltip");
const summaryEl = document.getElementById("summary");
const variantSelect = document.getElementById("variantSelect");

const state = {
  data: null,
  variant: null,
  bounds: null,
  hoverItems: [],
};

function roadColor(roadType) {
  if (roadType === "motorway" || roadType === "trunk") return "#7b2cbf";
  if (roadType === "primary") return "#1971c2";
  if (roadType === "secondary") return "#2b8a3e";
  if (roadType === "tertiary") return "#f08c00";
  return "#868e96";
}

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
  data.variants.forEach((variant) => {
    variant.ways.forEach((way) => way.shape_points.forEach((point) => points.push(point)));
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

function selectedVariant() {
  const name = variantSelect.value;
  return state.data.variants.find((variant) => variant.name === name) || state.data.variants[0];
}

function drawRoads(variant) {
  const colorEnabled = document.getElementById("toggleRoadColors").checked;
  variant.ways.forEach((way) => {
    if (!way.shape_points.length) return;
    ctx.beginPath();
    way.shape_points.forEach((point, index) => {
      const p = project(point.lat, point.lon);
      if (index === 0) ctx.moveTo(p.x, p.y);
      else ctx.lineTo(p.x, p.y);
    });
    ctx.lineWidth = Math.max(0.5, Math.min(4, 0.4 + (way.lane_count || 1) * 0.55));
    ctx.strokeStyle = colorEnabled ? roadColor(way.road_type) : "rgba(72,82,92,0.42)";
    ctx.globalAlpha = 0.72;
    ctx.stroke();
    ctx.globalAlpha = 1;

    if (way.shape_points.length) {
      const mid = way.shape_points[Math.floor(way.shape_points.length / 2)];
      const p = project(mid.lat, mid.lon);
      state.hoverItems.push({
        x: p.x,
        y: p.y,
        r: 5,
        text: `way: ${way.id}\nroad_type: ${way.road_type}\nlane: ${way.lane_count}\nspeed: ${way.speed_limit_kmh}\nlength: ${Math.round(way.length_meter)}m`,
      });
    }
  });
}

function drawObservations() {
  if (!document.getElementById("toggleObservations").checked) return;
  state.data.observations.forEach((obs) => {
    const p = project(obs.lat, obs.lon);
    ctx.beginPath();
    ctx.arc(p.x, p.y, 7, 0, Math.PI * 2);
    ctx.fillStyle = "rgba(224,49,49,0.82)";
    ctx.fill();
    ctx.lineWidth = 1.5;
    ctx.strokeStyle = "#ffffff";
    ctx.stroke();
    state.hoverItems.push({
      x: p.x,
      y: p.y,
      r: 12,
      text: `観測点\n${obs.point_name || obs.id}\nmatched_way: ${obs.matched_way_id}`,
    });
  });
}

function updateSummary(variant) {
  const typeLines = Object.entries(variant.summary.road_type_counts)
    .sort((a, b) => b[1] - a[1])
    .map(([key, value]) => `${key}: ${value}`)
    .join("\n");
  const laneLines = Object.entries(variant.summary.lane_counts)
    .map(([key, value]) => `${key} lane: ${value}`)
    .join("\n");
  summaryEl.textContent =
    `${variant.name}\n${variant.description}\n\n` +
    `center: ${state.data.meta.center_observation_name}\n` +
    `candidate before filter: ${state.data.meta.candidate_way_count_before_filter}\n` +
    `way_count: ${variant.summary.way_count}\n` +
    `observation_way_count: ${variant.summary.observation_way_count}\n\n` +
    `road_type\n${typeLines}\n\n` +
    `lane_count\n${laneLines}`;
}

function draw() {
  if (!state.data) return;
  const variant = selectedVariant();
  state.variant = variant;
  updateSummary(variant);
  const rect = canvas.getBoundingClientRect();
  ctx.clearRect(0, 0, rect.width, rect.height);
  state.hoverItems = [];
  drawRoads(variant);
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

variantSelect.addEventListener("change", draw);
document.getElementById("toggleObservations").addEventListener("change", draw);
document.getElementById("toggleRoadColors").addEventListener("change", draw);

fetch("./data/road_variants.json")
  .then((response) => response.json())
  .then((data) => {
    state.data = data;
    state.bounds = computeBounds(data);
    data.variants.forEach((variant) => {
      const option = document.createElement("option");
      option.value = variant.name;
      option.textContent = variant.name;
      variantSelect.appendChild(option);
    });
    resize();
  });

window.addEventListener("resize", resize);
