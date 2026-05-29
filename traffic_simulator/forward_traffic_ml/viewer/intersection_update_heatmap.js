const canvas = document.getElementById("mapCanvas");
const ctx = canvas.getContext("2d");
const tooltip = document.getElementById("tooltip");
const summaryEl = document.getElementById("summary");
const zoomReadout = document.getElementById("zoomReadout");

const state = {
  data: null,
  bounds: null,
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

function resize() {
  const rect = canvas.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  canvas.width = Math.max(1, Math.floor(rect.width * dpr));
  canvas.height = Math.max(1, Math.floor(rect.height * dpr));
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  draw();
}

function option(id) {
  return document.getElementById(id).checked;
}

function selectedMetric() {
  return document.getElementById("metricSelect").value;
}

function project(lat, lon) {
  const rect = canvas.getBoundingClientRect();
  const padding = 28;
  const b = state.bounds;
  const baseX = padding + ((lon - b.min_lon) / (b.max_lon - b.min_lon || 1)) * (rect.width - padding * 2);
  const baseY = padding + ((b.max_lat - lat) / (b.max_lat - b.min_lat || 1)) * (rect.height - padding * 2);
  return {
    x: baseX * state.view.scale + state.view.offsetX,
    y: baseY * state.view.scale + state.view.offsetY,
  };
}

function metricValue(item) {
  return Number(item[selectedMetric()] || 0);
}

function visibleIntersections() {
  const intersections = [...state.data.intersections];
  intersections.sort((a, b) => metricValue(b) - metricValue(a));
  if (option("toggleOnlyTop")) return intersections.slice(0, 250);
  return intersections;
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
    ctx.strokeStyle = major ? "rgba(70, 91, 109, 0.36)" : "rgba(91, 116, 139, 0.20)";
    ctx.stroke();
  });
}

function drawHeatmap() {
  const intersections = visibleIntersections();
  const values = intersections.map(metricValue);
  const maxValue = Math.max(1, ...values);
  const p90 = percentile(values, 0.9) || maxValue;
  const labelLimit = option("toggleTopLabels") ? 30 : 0;

  intersections.forEach((item, index) => {
    const value = metricValue(item);
    const normalized = Math.min(1, value / p90);
    const p = project(item.lat, item.lon);
    const radius = 2.3 + Math.sqrt(normalized) * 9.5;
    const alpha = 0.16 + normalized * 0.74;

    ctx.beginPath();
    ctx.arc(p.x, p.y, radius + 7 * normalized, 0, Math.PI * 2);
    ctx.fillStyle = `rgba(217, 72, 15, ${0.08 + normalized * 0.18})`;
    ctx.fill();

    ctx.beginPath();
    ctx.arc(p.x, p.y, radius, 0, Math.PI * 2);
    ctx.fillStyle = heatColor(normalized, alpha);
    ctx.fill();
    ctx.lineWidth = 1;
    ctx.strokeStyle = "rgba(255, 255, 255, 0.82)";
    ctx.stroke();

    if (index < labelLimit) {
      ctx.font = "11px system-ui, sans-serif";
      ctx.fillStyle = "#1d252c";
      ctx.fillText(`${index + 1}`, p.x + radius + 3, p.y - radius - 1);
    }

    state.hoverItems.push({
      x: p.x,
      y: p.y,
      r: radius + 6,
      text:
        `intersection\n${item.intersection_id}\n` +
        `node: ${item.node_id}\n` +
        `rank: ${index + 1}\n` +
        `update_count: ${item.update_count}\n` +
        `abs_delta_sum: ${item.abs_delta_sum.toFixed(4)}\n` +
        `signed_delta_sum: ${item.signed_delta_sum.toFixed(4)}\n` +
        `positive/negative: ${item.positive_count}/${item.negative_count}\n` +
        `unique_theta_count: ${item.unique_theta_count}\n` +
        `iteration_count: ${item.iteration_count}\n` +
        `mean_distance: ${item.mean_distance_meter.toFixed(1)}m\n` +
        `median_distance: ${item.median_distance_meter.toFixed(1)}m`,
    });
  });
}

function heatColor(value, alpha) {
  if (value < 0.35) return `rgba(25, 113, 194, ${alpha})`;
  if (value < 0.72) return `rgba(240, 140, 0, ${alpha})`;
  return `rgba(217, 72, 15, ${alpha})`;
}

function percentile(values, ratio) {
  if (!values.length) return 0;
  const ordered = [...values].sort((a, b) => a - b);
  const index = Math.max(0, Math.min(ordered.length - 1, Math.round((ordered.length - 1) * ratio)));
  return ordered[index];
}

function draw() {
  if (!state.data) return;
  const rect = canvas.getBoundingClientRect();
  ctx.clearRect(0, 0, rect.width, rect.height);
  state.hoverItems = [];
  if (option("toggleRoads")) drawRoads();
  if (option("toggleHeatmap")) drawHeatmap();
  updateSummary();
}

function updateSummary() {
  const metric = selectedMetric();
  const s = state.data.summary;
  const top = [...state.data.intersections]
    .sort((a, b) => metricValue(b) - metricValue(a))
    .slice(0, 12)
    .map((item, index) => {
      const value = metric === "abs_delta_sum" ? metricValue(item).toFixed(2) : metricValue(item);
      return `${index + 1}. ${item.node_id} ${value}`;
    })
    .join("\n");

  summaryEl.textContent =
    `result\n${s.result_dir}\n\n` +
    `updated intersections: ${s.updated_intersection_count}\n` +
    `raw update rows: ${s.raw_update_row_count}\n` +
    `roads: ${s.road_line_count}\n` +
    `mode: ${JSON.stringify(s.backtrace_mode_counts)}\n\n` +
    `metric: ${metric}\n` +
    `median: ${formatMetric(s[`${metric}_median`], metric)}\n` +
    `p90: ${formatMetric(s[`${metric}_p90`], metric)}\n` +
    `p99: ${formatMetric(s[`${metric}_p99`], metric)}\n` +
    `max: ${formatMetric(s[`${metric}_max`], metric)}\n\n` +
    `top\n${top}`;
}

function formatMetric(value, metric) {
  if (metric === "abs_delta_sum") return Number(value || 0).toFixed(2);
  return String(Math.round(Number(value || 0)));
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
  tooltip.textContent = hit.text;
  tooltip.style.left = `${x + 14}px`;
  tooltip.style.top = `${y + 14}px`;
  tooltip.style.display = "block";
});

canvas.addEventListener("mouseleave", () => {
  state.view.isDragging = false;
  canvas.classList.remove("dragging");
  tooltip.style.display = "none";
});

canvas.addEventListener("wheel", (event) => {
  event.preventDefault();
  const rect = canvas.getBoundingClientRect();
  const x = event.clientX - rect.left;
  const y = event.clientY - rect.top;
  const factor = event.deltaY < 0 ? 1.15 : 1 / 1.15;
  zoomAt(x, y, state.view.scale * factor);
}, { passive: false });

canvas.addEventListener("mousedown", (event) => {
  if (event.button !== 0) return;
  const rect = canvas.getBoundingClientRect();
  state.view.isDragging = true;
  state.view.lastX = event.clientX - rect.left;
  state.view.lastY = event.clientY - rect.top;
  canvas.classList.add("dragging");
  tooltip.style.display = "none";
});

window.addEventListener("mouseup", () => {
  state.view.isDragging = false;
  canvas.classList.remove("dragging");
});

["toggleRoads", "toggleHeatmap", "toggleTopLabels", "toggleOnlyTop"].forEach((id) => {
  document.getElementById(id).addEventListener("change", draw);
});
document.getElementById("metricSelect").addEventListener("change", draw);
document.getElementById("resetView").addEventListener("click", resetView);

fetch("./data/intersection_update_heatmap.json")
  .then((response) => response.json())
  .then((data) => {
    state.data = data;
    state.bounds = data.bounds;
    updateZoomReadout();
    resize();
  })
  .catch((error) => {
    summaryEl.textContent = `読み込みに失敗しました: ${error.message}`;
  });

window.addEventListener("resize", resize);
