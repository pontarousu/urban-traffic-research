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
  return {
    x: baseX * state.view.scale + state.view.offsetX,
    y: baseY * state.view.scale + state.view.offsetY,
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
    const major = ["motorway", "trunk", "primary", "secondary"].includes(road.road_type);
    ctx.lineWidth = major ? 1.05 : 0.55;
    ctx.strokeStyle = major ? "rgba(70, 91, 109, 0.34)" : "rgba(91, 116, 139, 0.18)";
    ctx.stroke();
  });
}

function visibleObservations() {
  const filter = selectedFilter();
  return state.data.observations.filter((obs) => {
    if (filter === "under") return obs.error_rate < 0;
    if (filter === "over") return obs.error_rate > 0;
    if (filter === "large") return Math.abs(obs.error_rate) >= 0.5;
    return true;
  });
}

function drawObservations() {
  const observations = visibleObservations();
  observations
    .slice()
    .sort((a, b) => Math.abs(a.error_rate) - Math.abs(b.error_rate))
    .forEach((obs) => {
      const p = project(obs.lat, obs.lon);
      const magnitude = Math.min(1.4, Math.abs(obs.error_rate));
      const radius = 3.2 + Math.sqrt(magnitude) * 7;
      ctx.beginPath();
      ctx.arc(p.x, p.y, radius + 3, 0, Math.PI * 2);
      ctx.fillStyle = colorFor(obs.error_rate, 0.16);
      ctx.fill();
      ctx.beginPath();
      ctx.arc(p.x, p.y, radius, 0, Math.PI * 2);
      ctx.fillStyle = colorFor(obs.error_rate, 0.82);
      ctx.fill();
      ctx.lineWidth = 1.3;
      ctx.strokeStyle = "rgba(255, 255, 255, 0.88)";
      ctx.stroke();

      if (option("toggleLabels") && Math.abs(obs.error_rate) >= 0.5) {
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
          `error_rate: ${(obs.error_rate * 100).toFixed(1)}%\n` +
          `ratio: ${(obs.ratio * 100).toFixed(1)}%\n` +
          `observed: ${obs.observed_total}\n` +
          `simulated: ${obs.simulated_total}\n` +
          `error: ${obs.error_total}\n` +
          `bins: ${obs.bin_count}\n` +
          `edge: ${obs.directed_edge_id || "-"}\n` +
          `match: ${obs.match_confidence || "-"}`,
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
  if (option("togglePoints")) drawObservations();
  updateSummary();
}

function updateSummary() {
  const s = state.data.summary;
  const observations = visibleObservations();
  const under = observations.filter((obs) => obs.error_rate < 0);
  const over = observations.filter((obs) => obs.error_rate > 0);
  const worstUnder = [...state.data.observations]
    .sort((a, b) => a.error_rate - b.error_rate)
    .slice(0, 8)
    .map((obs) => `${obs.point_number || "-"} ${obs.point_name || ""} ${(obs.error_rate * 100).toFixed(1)}%`)
    .join("\n");
  const worstOver = [...state.data.observations]
    .sort((a, b) => b.error_rate - a.error_rate)
    .slice(0, 8)
    .map((obs) => `${obs.point_number || "-"} ${obs.point_name || ""} +${(obs.error_rate * 100).toFixed(1)}%`)
    .join("\n");
  summaryEl.textContent =
    `time_min >= ${s.start_min}\n` +
    `observations: ${s.observation_count}\n` +
    `ratio: ${(s.simulated_total_ratio * 100).toFixed(1)}%\n` +
    `under/over: ${s.under_observation_count}/${s.over_observation_count}\n` +
    `visible under/over: ${under.length}/${over.length}\n` +
    `mean error_rate: ${(s.error_rate_mean * 100).toFixed(1)}%\n` +
    `min/max: ${(s.error_rate_min * 100).toFixed(1)}% / ${(s.error_rate_max * 100).toFixed(1)}%\n\n` +
    `worst under\n${worstUnder}\n\n` +
    `worst over\n${worstOver}`;
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
["toggleRoads", "togglePoints", "toggleLabels"].forEach((id) => {
  document.getElementById(id).addEventListener("change", draw);
});

window.addEventListener("resize", resize);

fetch("./data/observation_error_map.json")
  .then((response) => response.json())
  .then((data) => {
    state.data = data;
    updateZoomReadout();
    resize();
  })
  .catch((error) => {
    summaryEl.textContent = `読み込みに失敗しました: ${error.message}`;
  });
