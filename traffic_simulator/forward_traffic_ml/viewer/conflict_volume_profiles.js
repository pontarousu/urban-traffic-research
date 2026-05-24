const pairList = document.getElementById("pairList");
const summary = document.getElementById("summary");
const pairTemplate = document.getElementById("pairTemplate");
const scaleMode = document.getElementById("scaleMode");
const sortMode = document.getElementById("sortMode");

let appData = null;

function formatNumber(value) {
  return Number(value || 0).toLocaleString("ja-JP");
}

function formatRatio(value) {
  return Number(value || 0).toFixed(3);
}

function maxVolume(profile) {
  return Math.max(1, ...(profile.hourly_volumes || [0]));
}

function drawProfile(canvas, profile, maxY, color) {
  const ctx = canvas.getContext("2d");
  const width = canvas.width;
  const height = canvas.height;
  const padLeft = 34;
  const padRight = 10;
  const padTop = 12;
  const padBottom = 24;
  const graphWidth = width - padLeft - padRight;
  const graphHeight = height - padTop - padBottom;
  const values = profile.hourly_volumes || [];

  ctx.clearRect(0, 0, width, height);
  ctx.strokeStyle = "#d7dee3";
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(padLeft, padTop);
  ctx.lineTo(padLeft, padTop + graphHeight);
  ctx.lineTo(padLeft + graphWidth, padTop + graphHeight);
  ctx.stroke();

  [0, 6, 12, 18, 23].forEach((hour) => {
    const x = padLeft + (hour / 23) * graphWidth;
    ctx.strokeStyle = "rgba(173, 181, 189, 0.28)";
    ctx.beginPath();
    ctx.moveTo(x, padTop);
    ctx.lineTo(x, padTop + graphHeight);
    ctx.stroke();
    ctx.fillStyle = "#6a747c";
    ctx.font = "10px system-ui";
    ctx.textAlign = "center";
    ctx.fillText(`${hour}`, x, height - 7);
  });

  const yFor = (value) => padTop + graphHeight - (value / maxY) * graphHeight;
  ctx.fillStyle = "rgba(25, 113, 194, 0.12)";
  const barWidth = graphWidth / 24;
  values.forEach((value, index) => {
    const x = padLeft + index * barWidth + 1;
    const y = yFor(value);
    ctx.fillRect(x, y, Math.max(1, barWidth - 2), padTop + graphHeight - y);
  });

  ctx.strokeStyle = color;
  ctx.lineWidth = 2;
  ctx.beginPath();
  values.forEach((value, index) => {
    const x = padLeft + (index / 23) * graphWidth;
    const y = yFor(value);
    if (index === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.stroke();

  ctx.fillStyle = "#495057";
  ctx.font = "10px system-ui";
  ctx.textAlign = "right";
  ctx.fillText(formatNumber(maxY), padLeft - 5, padTop + 4);
  ctx.fillText("0", padLeft - 5, padTop + graphHeight + 3);
}

function profileStats(profile) {
  return [
    `type ${profile.profile_type}`,
    `bias ${formatRatio(profile.direction_bias)}`,
    `朝 ${formatRatio(profile.morning_ratio)}`,
    `夕 ${formatRatio(profile.evening_ratio)}`,
    `合計 ${formatNumber(profile.total_all_day)}`,
  ].join(" / ");
}

function pairMax(pair) {
  const left = maxVolume(pair.left_volume_profile);
  const right = maxVolume(pair.right_volume_profile);
  if (scaleMode.value === "self") return { left, right };
  if (scaleMode.value === "global") {
    const globalMax = Math.max(
      1,
      ...appData.near_pair_diagnostics
        .filter((item) => item.pair_status === "direction_conflict")
        .flatMap((item) => [
          ...(item.left_volume_profile.hourly_volumes || []),
          ...(item.right_volume_profile.hourly_volumes || []),
        ]),
    );
    return { left: globalMax, right: globalMax };
  }
  const pairMaxValue = Math.max(left, right);
  return { left: pairMaxValue, right: pairMaxValue };
}

function sortedPairs() {
  const pairs = appData.near_pair_diagnostics
    .filter((pair) => pair.pair_status === "direction_conflict")
    .slice();
  if (sortMode.value === "bias") {
    pairs.sort((a, b) => {
      const aGap = Math.abs(a.left_volume_profile.direction_bias - a.right_volume_profile.direction_bias);
      const bGap = Math.abs(b.left_volume_profile.direction_bias - b.right_volume_profile.direction_bias);
      return bGap - aGap;
    });
  } else if (sortMode.value === "volume") {
    pairs.sort((a, b) => {
      const aTotal = a.left_volume_profile.total_all_day + a.right_volume_profile.total_all_day;
      const bTotal = b.left_volume_profile.total_all_day + b.right_volume_profile.total_all_day;
      return bTotal - aTotal;
    });
  } else {
    pairs.sort((a, b) => a.distance_meter - b.distance_meter);
  }
  return pairs;
}

function renderSummary(pairs) {
  const uniqueIds = new Set(pairs.flatMap((pair) => [pair.left_observation_id, pair.right_observation_id]));
  const oppositeProfiles = pairs.filter((pair) => pair.volume_profile_relation === "opposite_profile").length;
  const sameProfiles = pairs.filter((pair) => pair.volume_profile_relation === "same_profile").length;
  summary.innerHTML = [
    ["conflict pairs", pairs.length],
    ["conflict observations", uniqueIds.size],
    ["opposite profile", oppositeProfiles],
    ["same profile", sameProfiles],
  ].map(([label, value]) => `<div class="metric"><span>${label}</span><strong>${value}</strong></div>`).join("");
}

function render() {
  const pairs = sortedPairs();
  renderSummary(pairs);
  pairList.innerHTML = "";
  pairs.forEach((pair) => {
    const row = pairTemplate.content.firstElementChild.cloneNode(true);
    row.querySelector(".pair-meta").innerHTML = `
      <strong>${pair.left_point_number} / ${pair.right_point_number}</strong>
      距離 ${pair.distance_meter}m<br>
      方向差 ${pair.direction_diff_deg ?? "-"}deg<br>
      時間関係 ${pair.volume_profile_relation}<br>
      left edge ${pair.left_directed_edge_id}<br>
      right edge ${pair.right_directed_edge_id}
    `;

    const leftPanel = row.querySelector(".left");
    const rightPanel = row.querySelector(".right");
    leftPanel.querySelector(".chart-title").textContent = `${pair.left_point_number} ${pair.left_point_name || ""}`;
    rightPanel.querySelector(".chart-title").textContent = `${pair.right_point_number} ${pair.right_point_name || ""}`;
    leftPanel.querySelector(".chart-stats").textContent = profileStats(pair.left_volume_profile);
    rightPanel.querySelector(".chart-stats").textContent = profileStats(pair.right_volume_profile);

    const maxes = pairMax(pair);
    drawProfile(leftPanel.querySelector("canvas"), pair.left_volume_profile, maxes.left, "#6741d9");
    drawProfile(rightPanel.querySelector("canvas"), pair.right_volume_profile, maxes.right, "#0b7285");
    pairList.appendChild(row);
  });
}

async function init() {
  const response = await fetch("./data/observation_alignment.json");
  appData = await response.json();
  scaleMode.addEventListener("change", render);
  sortMode.addEventListener("change", render);
  render();
}

init().catch((error) => {
  summary.textContent = `読み込みに失敗しました: ${error.message}`;
});
