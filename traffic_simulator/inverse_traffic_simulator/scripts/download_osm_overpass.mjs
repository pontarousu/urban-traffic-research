import fs from "node:fs/promises";
import https from "node:https";
import path from "node:path";

const DEFAULT_ENDPOINT = "https://overpass-api.de/api/interpreter";
const DEFAULT_PRESET = "tokyo_core_small";
const HIGHWAY_REGEX = "^(motorway|trunk|primary|secondary|tertiary|unclassified|residential|service|living_street)$";

const BBOX_PRESETS = {
  tokyo_station_wide: {
    south: 35.660,
    west: 139.735,
    north: 35.705,
    east: 139.795,
    output: "inverse_traffic_simulator/data/osm_tokyo_station_wide.osm",
    description: "東京駅、丸の内、日本橋、銀座周辺を含む広めの都心サンプル"
  },
  tokyo_core_small: {
    south: 35.640,
    west: 139.700,
    north: 35.720,
    east: 139.830,
    output: "inverse_traffic_simulator/data/osm_tokyo_core_small.osm",
    description: "千代田・中央・港北部・新宿東部・文京南部あたりを含む都心小領域"
  },
  tokyo_core_medium: {
    south: 35.600,
    west: 139.650,
    north: 35.760,
    east: 139.880,
    output: "inverse_traffic_simulator/data/osm_tokyo_core_medium.osm",
    description: "山手線周辺を大きめに含む中領域。Overpass負荷が高い可能性あり"
  }
};

async function main() {
  const options = parseOptions(process.argv.slice(2));
  const bbox = resolveBbox(options);
  const query = buildOverpassQuery(bbox, options.timeoutSec, options.includeRestrictions);
  const outputPath = path.resolve(options.output ?? bbox.output);
  const startedAt = Date.now();

  console.log("OSM取得を開始します。");
  console.log(JSON.stringify({
    endpoint: options.endpoint,
    output: outputPath,
    bbox: {
      south: bbox.south,
      west: bbox.west,
      north: bbox.north,
      east: bbox.east
    },
    timeout_sec: options.timeoutSec,
    include_restrictions: options.includeRestrictions,
    preset: options.preset,
    description: bbox.description ?? null
  }, null, 2));

  const responseText = await postOverpassQuery(options.endpoint, query);
  await fs.mkdir(path.dirname(outputPath), { recursive: true });
  await fs.writeFile(outputPath, responseText, "utf-8");

  const elapsedSec = (Date.now() - startedAt) / 1000;
  const stats = await fs.stat(outputPath);
  console.log("OSM取得が完了しました。");
  console.log(JSON.stringify({
    output: outputPath,
    size_mb: Math.round(stats.size / 1024 / 1024 * 100) / 100,
    elapsed_sec: Math.round(elapsedSec * 100) / 100
  }, null, 2));
}

/**
 * Overpass QLクエリを作る。
 *
 * @param {{south: number, west: number, north: number, east: number}} bbox
 * @param {number} timeoutSec
 * @returns {string}
 */
function buildOverpassQuery(bbox, timeoutSec, includeRestrictions = false) {
  const bboxText = `${bbox.south},${bbox.west},${bbox.north},${bbox.east}`;
  if (includeRestrictions) {
    return [
      `[out:xml][timeout:${timeoutSec}];`,
      "(",
      `  way["highway"~"${HIGHWAY_REGEX}"](${bboxText});`,
      ")->.roads;",
      "(",
      "  .roads;",
      "  node(w.roads);",
      "  rel(bw.roads)[\"type\"=\"restriction\"];",
      ")->.selected;",
      "(",
      "  .selected;",
      "  way(r.selected);",
      "  node(w);",
      ");",
      "out body;"
    ].join("\n");
  }
  return [
    `[out:xml][timeout:${timeoutSec}];`,
    "(",
    `  way["highway"~"${HIGHWAY_REGEX}"](${bboxText});`,
    ");",
    "(._;>;);",
    "out body;"
  ].join("\n");
}

/**
 * Overpass APIへPOSTする。
 *
 * @param {string} endpoint
 * @param {string} query
 * @returns {Promise<string>}
 */
function postOverpassQuery(endpoint, query) {
  const endpointUrl = new URL(endpoint);
  const body = new URLSearchParams({ data: query }).toString();

  return new Promise((resolve, reject) => {
    const request = https.request(
      {
        method: "POST",
        hostname: endpointUrl.hostname,
        path: `${endpointUrl.pathname}${endpointUrl.search}`,
        port: endpointUrl.port || 443,
        headers: {
          "Content-Type": "application/x-www-form-urlencoded; charset=utf-8",
          "Content-Length": Buffer.byteLength(body),
          "User-Agent": "traffic-simulator-research/0.1"
        }
      },
      (response) => {
        const chunks = [];
        response.on("data", (chunk) => chunks.push(chunk));
        response.on("end", () => {
          const responseText = Buffer.concat(chunks).toString("utf-8");
          if ((response.statusCode ?? 500) >= 400) {
            reject(new Error(`Overpass API error ${response.statusCode}: ${responseText.slice(0, 1000)}`));
            return;
          }
          resolve(responseText);
        });
      }
    );

    request.on("error", reject);
    request.write(body);
    request.end();
  });
}

/**
 * bbox指定を解決する。
 *
 * @param {{preset: string, bbox: string | null}} options
 * @returns {{south: number, west: number, north: number, east: number, output?: string, description?: string}}
 */
function resolveBbox(options) {
  if (options.bbox !== null) {
    const values = options.bbox.split(",").map((value) => Number(value.trim()));
    if (values.length !== 4 || values.some((value) => !Number.isFinite(value))) {
      throw new Error("--bbox は south,west,north,east の4数値で指定してください。");
    }
    const [south, west, north, east] = values;
    validateBbox({ south, west, north, east });
    return { south, west, north, east, description: "ユーザー指定bbox" };
  }

  const preset = BBOX_PRESETS[options.preset];
  if (!preset) {
    throw new Error(`未知のpresetです: ${options.preset}`);
  }
  validateBbox(preset);
  return preset;
}

/**
 * コマンドラインオプションを読む。
 *
 * @param {string[]} args
 * @returns {{endpoint: string, preset: string, bbox: string | null, output: string | null, timeoutSec: number, includeRestrictions: boolean}}
 */
function parseOptions(args) {
  const options = {
    endpoint: DEFAULT_ENDPOINT,
    preset: DEFAULT_PRESET,
    bbox: null,
    output: null,
    timeoutSec: 300,
    includeRestrictions: false
  };

  for (let index = 0; index < args.length; index += 1) {
    const name = args[index];
    const value = args[index + 1];

    if (name === "--endpoint") {
      options.endpoint = value;
      index += 1;
    } else if (name === "--preset") {
      options.preset = value;
      index += 1;
    } else if (name === "--bbox") {
      options.bbox = value;
      index += 1;
    } else if (name === "--output") {
      options.output = value;
      index += 1;
    } else if (name === "--timeout-sec") {
      options.timeoutSec = Number(value);
      index += 1;
    } else if (name === "--include-restrictions") {
      options.includeRestrictions = true;
    }
  }

  if (!Number.isFinite(options.timeoutSec) || options.timeoutSec <= 0) {
    throw new Error("--timeout-sec は正の数値にしてください。");
  }

  return options;
}

/**
 * bbox値を検証する。
 *
 * @param {{south: number, west: number, north: number, east: number}} bbox
 */
function validateBbox(bbox) {
  if (!(bbox.south < bbox.north) || !(bbox.west < bbox.east)) {
    throw new Error("bbox は south < north かつ west < east である必要があります。");
  }

  const latSpan = bbox.north - bbox.south;
  const lonSpan = bbox.east - bbox.west;
  if (latSpan > 0.3 || lonSpan > 0.3) {
    throw new Error("Overpass用bboxとして大きすぎます。広域全体はPBF取得へ切り替えてください。");
  }
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
