// このビューアはローカル生成された ./data/no_next_edge_map.json を読む。
// 公開版リポジトリには、観測点位置や実験結果に由来する生成済みJSONを同梱しない。
// 利用時は src/export_no_next_edge_map.py で権利上問題のないデータからJSONを生成する。
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
const maxZoom = 35;

function option(id) {
  return document.getElementById(id).checked;
}

function selected(id) {
  return document.getElementById(id).value;
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

function visibleNoNextEdges() {
  const source = selected("sourceFilter");
  const final = selected("finalFilter");
  const roadType = selected("roadTypeFilter");
  const minWeight = Number(document.getElementById("minWeight").value || 0);
  return state.data.no_next_edges.filter((item) => {
    if (source !== "all" && item.source_quadrant !== source) return false;
    if (final !== "all" && item.final_quadrant !== final) return false;
    if (roadType !== "all" && item.road_type !== roadType) return false;
    if (item.weight < minWeight) return false;
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
    ctx.lineWidth = major ? 1.05 : 0.55;
    ctx.strokeStyle = major ? "rgba(70, 91, 109, 0.34)" : "rgba(91, 116, 139, 0.18)";
    ctx.stroke();
  });
}

function drawObservations() {
  state.data.observations.forEach((obs) => {
    const p = project(obs.lat, obs.lon);
    ctx.beginPath();
    ctx.arc(p.x, p.y, 2.2, 0, Math.PI * 2);
    ctx.fillStyle = "rgba(21, 31, 40, 0.34)";
    ctx.fill();
  });
}

function drawNoNextEdges() {
  const edges = visibleNoNextEdges();
  edges
    .slice()
    .sort((a, b) => a.weight - b.weight)
    .forEach((item) => {
      const p = project(item.lat, item.lon);
      const radius = 2.2 + Math.sqrt(item.weight) * 0.42;
      ctx.beginPath();
      ctx.arc(p.x, p.y, radius + 4, 0, Math.PI * 2);
      ctx.fillStyle = colorForSource(item.source_quadrant, 0.14);
      ctx.fill();
      ctx.beginPath();
      ctx.arc(p.x, p.y, radius, 0, Math.PI * 2);
      ctx.fillStyle = colorForSource(item.source_quadrant, 0.78);
      ctx.fill();
      ctx.lineWidth = item.without_observation_weight > item.with_observation_weight ? 1.4 : 0.8;
      ctx.strokeStyle = "rgba(255, 255, 255, 0.86)";
      ctx.stroke();

      state.hoverItems.push({
        x: p.x,
        y: p.y,
        r: radius + 6,
        text:
          `source: ${item.source_quadrant}\n` +
          `final: ${item.final_quadrant}\n` +
          `edge: ${item.final_edge_id}\n` +
          `road: ${item.road_type}\n` +
          `weight: ${item.weight}\n` +
          `without obs: ${item.without_observation_weight}\n` +
          `with obs: ${item.with_observation_weight}\n` +
          `boundary: ${item.boundary_distance_meter.toFixed(1)}m`,
      });
    });
}

function colorForSource(sourceQuadrant, alpha) {
  if (sourceQuadrant === "NW") return `rgba(103, 65, 217, ${alpha})`;
  if (sourceQuadrant === "NE") return `rgba(25, 113, 194, ${alpha})`;
  if (sourceQuadrant === "SW") return `rgba(240, 140, 0, ${alpha})`;
  return `rgba(224, 49, 49, ${alpha})`;
}

function draw() {
  if (!state.data) return;
  const rect = canvas.getBoundingClientRect();
  ctx.clearRect(0, 0, rect.width, rect.height);
  state.hoverItems = [];
  if (option("toggleRoads")) drawRoads();
  if (option("toggleObservations")) drawObservations();
  if (option("toggleNoNext")) drawNoNextEdges();
  updateSummary();
}

function updateSummary() {
  const edges = visibleNoNextEdges();
  const totalWeight = edges.reduce((sum, item) => sum + item.weight, 0);
  const withoutWeight = edges.reduce((sum, item) => sum + item.without_observation_weight, 0);
  const byRoad = countBy(edges, "road_type");
  const byFinal = countBy(edges, "final_quadrant");
  const sourceRows = state.data.source_summary
    .map((row) =>
      `${row.source_quadrant}: reach ${(row.reach_ratio * 100).toFixed(1)}%, ` +
      `no_next ${(row.no_next_ratio * 100).toFixed(1)}%, ` +
      `no_obs ${(row.no_next_without_observation_ratio * 100).toFixed(1)}%`
    )
    .join("\n");
  const topEdges = edges
    .slice()
    .sort((a, b) => b.weight - a.weight)
    .slice(0, 10)
    .map((item) => `${item.final_edge_id} ${item.road_type} ${item.weight} ${item.final_quadrant}`)
    .join("\n");
  summaryEl.textContent =
    `visible edges: ${edges.length}\n` +
    `visible weight: ${totalWeight}\n` +
    `without obs: ${withoutWeight} (${totalWeight ? (withoutWeight / totalWeight * 100).toFixed(1) : "-"}%)\n\n` +
    `source summary\n${sourceRows}\n\n` +
    `visible final quadrant\n${formatCounter(byFinal)}\n\n` +
    `visible road type\n${formatCounter(byRoad)}\n\n` +
    `top visible edges\n${topEdges}`;
}

function countBy(items, key) {
  const counts = {};
  items.forEach((item) => {
    counts[item[key]] = (counts[item[key]] || 0) + item.weight;
  });
  return counts;
}

function formatCounter(counter) {
  return Object.entries(counter)
    .sort((a, b) => b[1] - a[1])
    .map(([key, value]) => `${key}: ${value}`)
    .join("\n");
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
["toggleRoads", "toggleObservations", "toggleNoNext", "sourceFilter", "finalFilter", "roadTypeFilter", "minWeight"].forEach((id) => {
  document.getElementById(id).addEventListener("change", draw);
});
document.getElementById("minWeight").addEventListener("input", draw);
window.addEventListener("resize", resize);

fetch("./data/no_next_edge_map.json")
  .then((response) => {
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return response.json();
  })
  .then((data) => {
    state.data = data;
    updateZoomReadout();
    resize();
  })
  .catch((error) => {
    summaryEl.textContent = `読み込みに失敗しました: ${error.message}`;
  });
