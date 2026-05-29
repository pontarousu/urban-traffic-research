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
const maxZoom = 20;

const statusStyle = {
  near: { fill: "rgba(24,100,171,0.82)", stroke: "#ffffff" },
  moderate: { fill: "rgba(240,140,0,0.82)", stroke: "#ffffff" },
  far: { fill: "rgba(224,49,49,0.84)", stroke: "#ffffff" },
  unknown: { fill: "rgba(73,80,87,0.75)", stroke: "#ffffff" },
};

const profileStyle = {
  morning_heavy: "rgba(103, 65, 217, 0.95)",
  evening_heavy: "rgba(11, 114, 133, 0.95)",
  flat: "rgba(73, 80, 87, 0.72)",
  low_volume_or_missing: "rgba(134, 142, 150, 0.62)",
};

const observationRadiusMeter = 1000;

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

function visibleObservations() {
  let observations = option("toggleExcludedObservations")
    ? state.data.observations
    : state.data.observations.filter((obs) => obs.usable_for_initial_matching);
  if (option("toggleOnlyPairConflicts")) {
    observations = observations.filter((obs) => obs.has_direction_conflict_pair);
  }
  return observations;
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
    ctx.strokeStyle = road.road_type === "motorway" ? "rgba(91, 116, 139, 0.45)" : "rgba(91, 116, 139, 0.28)";
    ctx.stroke();
  });
}

function drawObservationRadiusCircles() {
  const observations = visibleObservations();
  observations.forEach((obs) => {
    const circlePoints = circleLatLonPoints(obs.lat, obs.lon, observationRadiusMeter, 96);
    ctx.beginPath();
    circlePoints.forEach((point, index) => {
      const p = project(point.lat, point.lon);
      if (index === 0) ctx.moveTo(p.x, p.y);
      else ctx.lineTo(p.x, p.y);
    });
    ctx.closePath();
    ctx.fillStyle = "rgba(25, 113, 194, 0.055)";
    ctx.fill();
    ctx.lineWidth = Math.max(0.65, 1.1 / Math.sqrt(state.view.scale));
    ctx.strokeStyle = "rgba(25, 113, 194, 0.22)";
    ctx.stroke();
  });
}

function circleLatLonPoints(centerLat, centerLon, radiusMeter, stepCount) {
  const earthRadiusMeter = 6371008.8;
  const latRad = toRadians(centerLat);
  const lonRad = toRadians(centerLon);
  const angularDistance = radiusMeter / earthRadiusMeter;
  const points = [];
  for (let index = 0; index < stepCount; index += 1) {
    const bearing = (Math.PI * 2 * index) / stepCount;
    const pointLatRad = Math.asin(
      Math.sin(latRad) * Math.cos(angularDistance) +
        Math.cos(latRad) * Math.sin(angularDistance) * Math.cos(bearing),
    );
    const pointLonRad = lonRad + Math.atan2(
      Math.sin(bearing) * Math.sin(angularDistance) * Math.cos(latRad),
      Math.cos(angularDistance) - Math.sin(latRad) * Math.sin(pointLatRad),
    );
    points.push({
      lat: toDegrees(pointLatRad),
      lon: toDegrees(pointLonRad),
    });
  }
  return points;
}

function toRadians(degrees) {
  return degrees * Math.PI / 180;
}

function toDegrees(radians) {
  return radians * 180 / Math.PI;
}

function drawConnectors() {
  const visibleIds = new Set(visibleObservations().map((obs) => obs.id));
  state.data.connector_lines.forEach((line) => {
    if (!visibleIds.has(line.observation_id)) return;
    const start = project(line.points[0].lat, line.points[0].lon);
    const end = project(line.points[1].lat, line.points[1].lon);
    const style = statusStyle[line.alignment_status] || statusStyle.unknown;
    ctx.beginPath();
    ctx.moveTo(start.x, start.y);
    ctx.lineTo(end.x, end.y);
    ctx.lineWidth = 1;
    ctx.setLineDash([4, 4]);
    ctx.strokeStyle = style.fill.replace("0.82", "0.45").replace("0.84", "0.45");
    ctx.stroke();
    ctx.setLineDash([]);
  });
}

function drawLinkedEdges() {
  visibleObservations().forEach((obs) => {
    const link = obs.matched_link || obs.provisional_link;
    if (!link || !link.shape_points || !link.shape_points.length) return;
    ctx.beginPath();
    link.shape_points.forEach((point, index) => {
      const p = project(point.lat, point.lon);
      if (index === 0) ctx.moveTo(p.x, p.y);
      else ctx.lineTo(p.x, p.y);
    });
    ctx.lineWidth = Math.max(2.2, 3.2 / Math.sqrt(state.view.scale));
    ctx.strokeStyle = obs.usable_for_initial_matching ? "rgba(25, 113, 194, 0.82)" : "rgba(224, 49, 49, 0.62)";
    ctx.stroke();
    if (option("toggleDirectionArrows")) drawDirectionArrow(link.shape_points, obs.usable_for_initial_matching);
  });
}

function drawNearPairs() {
  const visibleIds = new Set(visibleObservations().map((obs) => obs.id));
  state.data.near_pair_diagnostics.forEach((pair) => {
    if (!visibleIds.has(pair.left_observation_id) || !visibleIds.has(pair.right_observation_id)) return;
    const start = project(pair.points[0].lat, pair.points[0].lon);
    const end = project(pair.points[1].lat, pair.points[1].lon);
    const isConflict = pair.pair_status === "direction_conflict";
    const isOppositeProfile = pair.volume_profile_relation === "opposite_profile";
    ctx.beginPath();
    ctx.moveTo(start.x, start.y);
    ctx.lineTo(end.x, end.y);
    ctx.lineWidth = isConflict ? 2.2 : 1.1;
    ctx.setLineDash(isConflict ? [] : [3, 4]);
    ctx.strokeStyle = isConflict
      ? "rgba(217, 72, 15, 0.88)"
      : isOppositeProfile
        ? "rgba(46, 125, 50, 0.68)"
        : "rgba(73, 80, 87, 0.38)";
    ctx.stroke();
    ctx.setLineDash([]);

    const midX = (start.x + end.x) / 2;
    const midY = (start.y + end.y) / 2;
    state.hoverItems.push({
      x: midX,
      y: midY,
      r: isConflict ? 10 : 7,
      text:
        `近接ペア\n${pair.left_point_number} ${pair.left_point_name || ""}\n` +
        `${pair.right_point_number} ${pair.right_point_name || ""}\n` +
        `距離: ${pair.distance_meter}m\n` +
        `状態: ${pair.pair_status}\n` +
        `時間関係: ${pair.volume_profile_relation}\n` +
        `方向差: ${pair.direction_diff_deg ?? "-"}deg\n` +
        `left_profile: ${pair.left_volume_profile.profile_type} bias ${pair.left_volume_profile.direction_bias}\n` +
        `left_day: ${sparkline(pair.left_volume_profile.hourly_ratios)}\n` +
        `right_profile: ${pair.right_volume_profile.profile_type} bias ${pair.right_volume_profile.direction_bias}\n` +
        `right_day: ${sparkline(pair.right_volume_profile.hourly_ratios)}\n` +
        `left_edge: ${pair.left_directed_edge_id}\n` +
        `right_edge: ${pair.right_directed_edge_id}\n` +
        `resolution: ${pair.pair_resolution?.status || "-"} ${pair.pair_resolution?.reason || ""}\n` +
        `selected: ${pair.pair_resolution?.left_selected_edge || "-"} / ${pair.pair_resolution?.right_selected_edge || "-"}\n` +
        `same_edge: ${pair.same_directed_edge}\n` +
        `left_alt: ${formatAlternativeEdges(pair.left_alternative_opposite_edges)}\n` +
        `right_alt: ${formatAlternativeEdges(pair.right_alternative_opposite_edges)}`,
    });
  });
}

function formatAlternativeEdges(edges) {
  if (!edges || !edges.length) return "-";
  return edges.map((edge) => `${edge.directed_edge_id} ${edge.distance_meter}m ${edge.bearing_deg}deg`).join(", ");
}

function sparkline(values) {
  if (!values || !values.length) return "-";
  const bars = "▁▂▃▄▅▆▇█";
  return values.map((value) => {
    const index = Math.max(0, Math.min(bars.length - 1, Math.round(value * (bars.length - 1))));
    return bars[index];
  }).join("");
}

function drawDirectionArrow(shapePoints, isUsable) {
  if (shapePoints.length < 2) return;
  const ratio = 0.58;
  const sample = pointAlongPolyline(shapePoints, ratio);
  if (!sample) return;
  const p = project(sample.lat, sample.lon);
  const next = project(sample.nextLat, sample.nextLon);
  const angle = Math.atan2(next.y - p.y, next.x - p.x);
  const size = Math.max(7, 10 / Math.sqrt(state.view.scale));
  ctx.save();
  ctx.translate(p.x, p.y);
  ctx.rotate(angle);
  ctx.beginPath();
  ctx.moveTo(size, 0);
  ctx.lineTo(-size * 0.55, -size * 0.45);
  ctx.lineTo(-size * 0.25, 0);
  ctx.lineTo(-size * 0.55, size * 0.45);
  ctx.closePath();
  ctx.fillStyle = isUsable ? "rgba(24, 100, 171, 0.96)" : "rgba(224, 49, 49, 0.82)";
  ctx.fill();
  ctx.restore();
}

function pointAlongPolyline(shapePoints, ratio) {
  const segments = [];
  let total = 0;
  for (let i = 0; i < shapePoints.length - 1; i += 1) {
    const a = shapePoints[i];
    const b = shapePoints[i + 1];
    const length = Math.hypot(b.lon - a.lon, b.lat - a.lat);
    segments.push({ a, b, length });
    total += length;
  }
  if (!segments.length || total === 0) return null;
  const target = total * ratio;
  let current = 0;
  for (const segment of segments) {
    if (current + segment.length >= target) {
      const t = (target - current) / segment.length;
      return {
        lat: segment.a.lat + (segment.b.lat - segment.a.lat) * t,
        lon: segment.a.lon + (segment.b.lon - segment.a.lon) * t,
        nextLat: segment.b.lat,
        nextLon: segment.b.lon,
      };
    }
    current += segment.length;
  }
  const last = segments[segments.length - 1];
  return {
    lat: last.b.lat,
    lon: last.b.lon,
    nextLat: last.b.lat,
    nextLon: last.b.lon,
  };
}

function drawObservations() {
  const observations = visibleObservations();
  const maxVolume = Math.max(1, ...observations.map((obs) => obs.observed_total || 0));
  observations.forEach((obs) => {
    const p = project(obs.lat, obs.lon);
    const style = statusStyle[obs.alignment_status] || statusStyle.unknown;
    const radius = 3 + Math.sqrt((obs.observed_total || 0) / maxVolume) * 4;
    ctx.beginPath();
    ctx.arc(p.x, p.y, radius, 0, Math.PI * 2);
    ctx.fillStyle = observationFillStyle(obs, style);
    ctx.fill();
    ctx.lineWidth = obs.has_direction_conflict_pair ? 2.2 : 1.4;
    ctx.strokeStyle = style.stroke;
    ctx.stroke();

    if (option("toggleLabels")) {
      ctx.font = "11px system-ui, sans-serif";
      ctx.fillStyle = "#1d252c";
      ctx.fillText(obs.point_number || obs.id, p.x + radius + 3, p.y - radius - 1);
    }

    const nearestLines = (obs.nearest_candidates || [])
      .map((candidate, index) => {
        return `${index + 1}. ${candidate.directed_edge_id} ${candidate.distance_meter}m ${candidate.road_type || ""}`;
      })
      .join("\n");
    const oldMatchLine = option("toggleOldMatches")
      ? `\nold_way: ${obs.old_matched_way_id || "-"}\nold_dist: ${obs.old_match_distance_meter ?? "-"}`
      : "";
    const link = obs.matched_link || obs.provisional_link;
    const provisional = obs.provisional_link;
    const linkLine = link
      ? `\nmatched_edge: ${link.directed_edge_id}\nmethod: ${obs.match_method || "-"} confidence: ${obs.match_confidence || "-"}\nflags: ${(obs.warning_flags || []).join(", ") || "-"}\nprovisional_edge: ${provisional?.directed_edge_id || "-"}\nroad: ${link.road_type || "-"} lane: ${link.lane_count_total ?? "-"} speed: ${link.speed_limit_kmh ?? "-"}\nfrom: ${link.from_node_id || "-"}\nto: ${link.to_node_id || "-"}\npos: ${link.position_ratio}`
      : "\nlinked_edge: -";
    state.hoverItems.push({
      x: p.x,
      y: p.y,
      r: radius + 4,
      text:
        `観測点\n${obs.point_name || obs.id}\n` +
        `番号: ${obs.point_number || "-"}\n` +
        `近傍距離: ${obs.nearest_distance_meter ?? "-"}m\n` +
        `状態: ${obs.alignment_status}\n` +
        `初期対象: ${obs.usable_for_initial_matching ? "yes" : "no"}\n` +
        `近接conflict: ${obs.has_direction_conflict_pair ? "yes" : "no"}\n` +
        `near_pairs: ${(obs.near_pair_ids || []).join(", ") || "-"}\n` +
        `profile: ${obs.volume_profile.profile_type}\n` +
        `bias: ${obs.volume_profile.direction_bias}\n` +
        `morning: ${obs.volume_profile.morning_ratio}\n` +
        `evening: ${obs.volume_profile.evening_ratio}\n` +
        `day: ${sparkline(obs.volume_profile.hourly_ratios)}\n` +
        `all_day: ${obs.volume_profile.total_all_day}\n` +
        `観測合計: ${obs.observed_total}\n` +
        linkLine +
        oldMatchLine +
        `\nnearest\n${nearestLines}`,
    });
  });
}

function observationFillStyle(obs, fallbackStyle) {
  if (obs.has_direction_conflict_pair) return "rgba(217, 72, 15, 0.9)";
  if (option("toggleVolumeProfile")) {
    return profileStyle[obs.volume_profile?.profile_type] || fallbackStyle.fill;
  }
  return fallbackStyle.fill;
}

function draw() {
  if (!state.data) return;
  const rect = canvas.getBoundingClientRect();
  ctx.clearRect(0, 0, rect.width, rect.height);
  state.hoverItems = [];
  if (option("toggleRoads")) drawRoads();
  if (option("toggleObservationRadius")) drawObservationRadiusCircles();
  if (option("toggleLinkedEdges")) drawLinkedEdges();
  if (option("toggleConnectors")) drawConnectors();
  if (option("toggleNearPairs")) drawNearPairs();
  if (option("toggleObservations")) drawObservations();
}

function updateSummary(data) {
  const counts = data.summary.alignment_status_counts || {};
  const profileCounts = data.summary.volume_profile_counts || {};
  const matchMethodCounts = data.summary.match_method_counts || {};
  const matchConfidenceCounts = data.summary.match_confidence_counts || {};
  summaryEl.textContent =
    `observations: ${data.summary.observation_count}\n` +
    `initial usable: ${data.summary.usable_for_initial_matching_count}\n` +
    `excluded: ${data.summary.excluded_for_initial_matching_count}\n` +
    `pair conflict obs: ${data.summary.pair_conflict_observation_count}\n` +
    `near pairs: ${data.near_pair_diagnostics.length}\n` +
    `roads: ${data.summary.road_line_count}\n\n` +
    `nearest distance\n` +
    `min: ${data.summary.nearest_distance_min_meter}m\n` +
    `median: ${data.summary.nearest_distance_median_meter}m\n` +
    `p90: ${data.summary.nearest_distance_p90_meter}m\n` +
    `max: ${data.summary.nearest_distance_max_meter}m\n\n` +
    `status\n` +
    `near: ${counts.near || 0}\n` +
    `moderate: ${counts.moderate || 0}\n` +
    `far: ${counts.far || 0}\n\n` +
    `profiles\n` +
    `morning: ${profileCounts.morning_heavy || 0}\n` +
    `evening: ${profileCounts.evening_heavy || 0}\n` +
    `flat: ${profileCounts.flat || 0}\n` +
    `low/missing: ${profileCounts.low_volume_or_missing || 0}\n\n` +
    `matching\n` +
    `nearest: ${matchMethodCounts.nearest || 0}\n` +
    `pair_constrained: ${matchMethodCounts.pair_constrained || 0}\n` +
    `unresolved obs: ${data.summary.pair_constraint_unresolved_observation_count || 0}\n` +
    `high: ${matchConfidenceCounts.high || 0}\n` +
    `medium: ${matchConfidenceCounts.medium || 0}\n` +
    `low: ${matchConfidenceCounts.low || 0}`;
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

["toggleRoads", "toggleObservations", "toggleConnectors", "toggleLinkedEdges", "toggleDirectionArrows", "toggleNearPairs", "toggleObservationRadius", "toggleOnlyPairConflicts", "toggleVolumeProfile", "toggleExcludedObservations", "toggleLabels", "toggleOldMatches"].forEach((id) => {
  document.getElementById(id).addEventListener("change", draw);
});

document.getElementById("resetView").addEventListener("click", resetView);

fetch("./data/observation_alignment.json")
  .then((response) => response.json())
  .then((data) => {
    state.data = data;
    state.bounds = data.bounds;
    updateSummary(data);
    updateZoomReadout();
    resize();
  });

window.addEventListener("resize", resize);
