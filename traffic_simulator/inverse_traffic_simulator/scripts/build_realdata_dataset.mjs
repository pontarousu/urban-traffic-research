import fs from "node:fs/promises";
import path from "node:path";

const ROOT_DIR = path.resolve("inverse_traffic_simulator");
const LOCATION_CSV_PATH = path.join(ROOT_DIR, "number_to_location.csv");
const TRAFFIC_DIR = path.join(ROOT_DIR, "TrafficVolume_Split_5min");
const OUTPUT_PATH = path.join(ROOT_DIR, "data", "realdata_all.json");

const SYNTHETIC_WAY_LENGTH_METER = 60;
const SYNTHETIC_LANE_COUNT = 1;
const SYNTHETIC_SPEED_LIMIT_KMH = 30;
const VIEW_WIDTH = 1000;
const VIEW_HEIGHT = 1000;
const VIEW_PADDING = 40;

async function main() {
  const locations = await readLocationMap(LOCATION_CSV_PATH);
  const trafficFiles = await listTrafficFiles(TRAFFIC_DIR);
  const trafficByPointKey = new Map();
  const missingLocationKeys = new Set();
  const fileTimes = [];

  for (const trafficFile of trafficFiles) {
    const timeMin = extractTimeMinFromFilename(trafficFile);
    if (timeMin === null) {
      continue;
    }

    fileTimes.push(timeMin);
    const rows = await readCsvFile(path.join(TRAFFIC_DIR, trafficFile));
    const header = rows[0] ?? [];
    const indexes = buildIndexMap(header);

    for (const row of rows.slice(1)) {
      const sourceCode = getCell(row, indexes, "情報源コード");
      const pointNumber = getCell(row, indexes, "計測地点番号");
      const volumeText = getCell(row, indexes, "断面交通量");
      const volume = Number(volumeText);

      if (!sourceCode || !pointNumber || !Number.isFinite(volume)) {
        continue;
      }

      const pointKey = makePointKey(sourceCode, pointNumber);
      if (!locations.has(pointKey)) {
        missingLocationKeys.add(pointKey);
        continue;
      }

      if (!trafficByPointKey.has(pointKey)) {
        trafficByPointKey.set(pointKey, []);
      }

      trafficByPointKey.get(pointKey).push({
        time_min: timeMin,
        volume_5min: volume
      });
    }
  }

  const usedLocations = [...trafficByPointKey.keys()].map((pointKey) => locations.get(pointKey));
  const bounds = computeBounds(usedLocations);
  const nodes = [];
  const ways = [];
  const observationPoints = [];

  for (const [pointKey, trafficVolume] of trafficByPointKey.entries()) {
    const location = locations.get(pointKey);
    const viewPoint = projectToView(location.lon, location.lat, bounds);
    const ids = buildSyntheticIds(location.source_code, location.point_number);

    trafficVolume.sort((left, right) => left.time_min - right.time_min);

    nodes.push(
      {
        id: ids.fromNodeId,
        lat: location.lat,
        lon: location.lon - 0.0001,
        view_x: viewPoint.view_x - 4,
        view_y: viewPoint.view_y,
        connected_way_ids: [ids.wayId],
        turn_permissions: []
      },
      {
        id: ids.toNodeId,
        lat: location.lat,
        lon: location.lon + 0.0001,
        view_x: viewPoint.view_x + 4,
        view_y: viewPoint.view_y,
        connected_way_ids: [ids.wayId],
        turn_permissions: []
      }
    );

    ways.push({
      id: ids.wayId,
      osm_way_id: null,
      from_node_id: ids.fromNodeId,
      to_node_id: ids.toNodeId,
      shape_points: [
        {
          lat: location.lat,
          lon: location.lon - 0.0001,
          view_x: viewPoint.view_x - 4,
          view_y: viewPoint.view_y
        },
        {
          lat: location.lat,
          lon: location.lon + 0.0001,
          view_x: viewPoint.view_x + 4,
          view_y: viewPoint.view_y
        }
      ],
      road_type: "synthetic_observation_link",
      lane_count: SYNTHETIC_LANE_COUNT,
      length_meter: SYNTHETIC_WAY_LENGTH_METER,
      speed_limit_kmh: SYNTHETIC_SPEED_LIMIT_KMH,
      storage_capacity_cars: Math.max(
        SYNTHETIC_LANE_COUNT,
        Math.floor(SYNTHETIC_WAY_LENGTH_METER / 4) * SYNTHETIC_LANE_COUNT
      )
    });

    observationPoints.push({
      id: ids.observationId,
      source_code: location.source_code,
      point_number: location.point_number,
      point_name: location.point_name,
      lat: location.lat,
      lon: location.lon,
      view_x: viewPoint.view_x,
      view_y: viewPoint.view_y,
      matched_way_id: ids.wayId,
      matched_position_ratio: 0.5,
      traffic_volume: trafficVolume
    });
  }

  observationPoints.sort((left, right) => {
    const sourceCompare = left.source_code.localeCompare(right.source_code);
    if (sourceCompare !== 0) {
      return sourceCompare;
    }
    return Number(left.point_number) - Number(right.point_number);
  });

  const scenario = {
    schema_version: "1.0",
    meta: {
      scenario_id: "realdata_all_synthetic_links",
      scenario_name: "Real Traffic Volume All Points Synthetic Links",
      start_time_min: Math.min(...fileTimes),
      source_date: "2026-02-02",
      note: "実観測点を個別の仮想単方向 Way に載せた取り込み検証用データ。実道路ネットワークではない。",
      view_box: {
        x_min: 0,
        y_min: 0,
        x_max: VIEW_WIDTH,
        y_max: VIEW_HEIGHT
      },
      summary: {
        traffic_file_count: trafficFiles.length,
        location_count: locations.size,
        observation_point_count: observationPoints.length,
        node_count: nodes.length,
        way_count: ways.length,
        missing_location_count: missingLocationKeys.size,
        first_time_min: Math.min(...fileTimes),
        last_time_min: Math.max(...fileTimes)
      }
    },
    graph: {
      nodes,
      ways
    },
    observation_points: observationPoints,
    simulation_config: {
      random_seed: 42,
      time_step_sec: 1,
      request_horizon_min: 20,
      request_window_min: 5,
      u_turn_allowed: false,
      score_model: {
        type: "discounted_sum",
        travel_decay_a: 0.12,
        slack_decay_b: 0.08
      },
      logging: {
        enabled: true
      }
    }
  };

  await fs.writeFile(OUTPUT_PATH, `${JSON.stringify(scenario, null, 2)}\n`, "utf-8");

  console.log("realdata_all.json を生成しました。");
  console.log(JSON.stringify(scenario.meta.summary, null, 2));
  if (missingLocationKeys.size > 0) {
    console.log(`緯度経度対応が見つからなかった地点キー例: ${[...missingLocationKeys].slice(0, 10).join(", ")}`);
  }
}

/**
 * 地点番号と緯度経度の対応表を読む。
 *
 * @param {string} csvPath
 * @returns {Promise<Map<string, {source_code: string, point_number: string, point_name: string, lon: number, lat: number}>>}
 */
async function readLocationMap(csvPath) {
  const rows = await readCsvFile(csvPath);
  const headerIndex = rows.findIndex((row) => row.includes("計測地点番号"));
  if (headerIndex < 0) {
    throw new Error("number_to_location.csv に計測地点番号のヘッダーが見つかりません。");
  }

  const indexes = buildIndexMap(rows[headerIndex]);
  const locationMap = new Map();

  for (const row of rows.slice(headerIndex + 1)) {
    const sourceCode = getCell(row, indexes, "情報源コード");
    const pointNumber = getCell(row, indexes, "計測地点番号");
    const pointName = getCell(row, indexes, "計測地点名");
    const lon = Number(getCell(row, indexes, "経度"));
    const lat = Number(getCell(row, indexes, "緯度"));

    if (!sourceCode || !pointNumber || !Number.isFinite(lon) || !Number.isFinite(lat)) {
      continue;
    }

    locationMap.set(makePointKey(sourceCode, pointNumber), {
      source_code: sourceCode,
      point_number: pointNumber,
      point_name: pointName,
      lon,
      lat
    });
  }

  return locationMap;
}

/**
 * 交通量ファイルを時刻順に列挙する。
 *
 * @param {string} trafficDir
 * @returns {Promise<string[]>}
 */
async function listTrafficFiles(trafficDir) {
  const dirents = await fs.readdir(trafficDir, { withFileTypes: true });
  return dirents
    .filter((dirent) => dirent.isFile() && /^TrafficVolume_\d{8}_\d{4}\.csv$/.test(dirent.name))
    .map((dirent) => dirent.name)
    .sort();
}

/**
 * CP932 の CSV を読む。
 *
 * @param {string} csvPath
 * @returns {Promise<string[][]>}
 */
async function readCsvFile(csvPath) {
  const buffer = await fs.readFile(csvPath);
  const decoder = new TextDecoder("shift_jis");
  const text = decoder.decode(buffer).replace(/\r\n/g, "\n").replace(/\r/g, "\n");
  return text
    .split("\n")
    .filter((line) => line.length > 0)
    .map(parseCsvLine);
}

/**
 * CSV 1行を分解する。
 *
 * @param {string} line
 * @returns {string[]}
 */
function parseCsvLine(line) {
  const cells = [];
  let current = "";
  let inQuote = false;

  for (let index = 0; index < line.length; index += 1) {
    const char = line[index];
    const nextChar = line[index + 1];

    if (char === '"' && inQuote && nextChar === '"') {
      current += '"';
      index += 1;
      continue;
    }

    if (char === '"') {
      inQuote = !inQuote;
      continue;
    }

    if (char === "," && !inQuote) {
      cells.push(current);
      current = "";
      continue;
    }

    current += char;
  }

  cells.push(current);
  return cells.map((cell) => cell.trim());
}

/**
 * ヘッダー名から列番号を引ける Map を作る。
 *
 * @param {string[]} header
 * @returns {Map<string, number>}
 */
function buildIndexMap(header) {
  const indexes = new Map();
  header.forEach((name, index) => {
    indexes.set(name, index);
  });
  return indexes;
}

/**
 * セル値を安全に取り出す。
 *
 * @param {string[]} row
 * @param {Map<string, number>} indexes
 * @param {string} name
 * @returns {string}
 */
function getCell(row, indexes, name) {
  const index = indexes.get(name);
  if (index === undefined) {
    return "";
  }
  return row[index] ?? "";
}

/**
 * ファイル名から開始分を返す。
 *
 * @param {string} filename
 * @returns {number | null}
 */
function extractTimeMinFromFilename(filename) {
  const match = filename.match(/^TrafficVolume_(\d{8})_(\d{2})(\d{2})\.csv$/);
  if (!match) {
    return null;
  }

  const hour = Number(match[2]);
  const minute = Number(match[3]);
  if (!Number.isFinite(hour) || !Number.isFinite(minute)) {
    return null;
  }

  return hour * 60 + minute;
}

/**
 * 地点キーを作る。
 *
 * @param {string} sourceCode
 * @param {string} pointNumber
 * @returns {string}
 */
function makePointKey(sourceCode, pointNumber) {
  return `${sourceCode}:${pointNumber}`;
}

/**
 * ID 群を作る。
 *
 * @param {string} sourceCode
 * @param {string} pointNumber
 * @returns {{observationId: string, wayId: string, fromNodeId: string, toNodeId: string}}
 */
function buildSyntheticIds(sourceCode, pointNumber) {
  const safeSource = sourceCode.replace(/[^A-Za-z0-9_]/g, "_");
  const safeNumber = pointNumber.replace(/[^A-Za-z0-9_]/g, "_");
  const base = `${safeSource}_${safeNumber}`;
  return {
    observationId: `obs_${base}`,
    wayId: `way_${base}`,
    fromNodeId: `node_${base}_from`,
    toNodeId: `node_${base}_to`
  };
}

/**
 * 表示範囲を計算する。
 *
 * @param {{lon: number, lat: number}[]} locations
 * @returns {{minLon: number, maxLon: number, minLat: number, maxLat: number}}
 */
function computeBounds(locations) {
  return {
    minLon: Math.min(...locations.map((location) => location.lon)),
    maxLon: Math.max(...locations.map((location) => location.lon)),
    minLat: Math.min(...locations.map((location) => location.lat)),
    maxLat: Math.max(...locations.map((location) => location.lat))
  };
}

/**
 * 緯度経度を表示座標に変換する。
 *
 * @param {number} lon
 * @param {number} lat
 * @param {{minLon: number, maxLon: number, minLat: number, maxLat: number}} bounds
 * @returns {{view_x: number, view_y: number}}
 */
function projectToView(lon, lat, bounds) {
  const lonRange = Math.max(1e-9, bounds.maxLon - bounds.minLon);
  const latRange = Math.max(1e-9, bounds.maxLat - bounds.minLat);

  return {
    view_x: VIEW_PADDING + (lon - bounds.minLon) / lonRange * (VIEW_WIDTH - VIEW_PADDING * 2),
    view_y: VIEW_HEIGHT - VIEW_PADDING - (lat - bounds.minLat) / latRange * (VIEW_HEIGHT - VIEW_PADDING * 2)
  };
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
