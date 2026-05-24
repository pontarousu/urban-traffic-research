import fs from "node:fs/promises";
import path from "node:path";
import {
  createSimulationRuntime,
  stepSimulation
} from "../src/sim_core.mjs";

const DEFAULT_SCENARIO_PATH =
  "../data/current/tokyo_core_small_realdata_osm_300obs_allday.json";
const DEFAULT_OUTPUT_CSV_PATH =
  "../data/analysis/active_cars_0500_1500_current.csv";
const DEFAULT_OUTPUT_SVG_PATH =
  "../data/analysis/active_cars_0500_1500_current.svg";

async function main() {
  const options = parseOptions(process.argv.slice(2));
  const scenarioPath = path.resolve(options.scenario);
  const outputCsvPath = path.resolve(options.outputCsv);
  const outputSvgPath = path.resolve(options.outputSvg);

  const rawScenario = JSON.parse(await fs.readFile(scenarioPath, "utf-8"));
  const scenario = sliceScenarioByTimeRange(rawScenario, options.startMin, options.endMin);
  scenario.simulation_config = {
    ...scenario.simulation_config,
    logging: {
      ...(scenario.simulation_config?.logging ?? {}),
      enabled: false
    }
  };

  const runtime = createSimulationRuntime(scenario);
  if (runtime.request_windows.length === 0) {
    throw new Error("指定した時間範囲に request がありません。");
  }

  const endMin = options.endMin ?? inferEndMin(scenario);
  const timeStepMin = (scenario.simulation_config.time_step_sec ?? 1) / 60;
  const samples = [
    {
      time_min: round(runtime.now_min, 4),
      active_cars: runtime.active_cars.length
    }
  ];
  let maxActiveCars = runtime.active_cars.length;

  while (runtime.now_min < endMin - timeStepMin / 2) {
    stepSimulation(scenario, runtime);
    const activeCars = runtime.active_cars.length;
    maxActiveCars = Math.max(maxActiveCars, activeCars);
    samples.push({
      time_min: round(runtime.now_min, 4),
      active_cars: activeCars
    });
  }

  await fs.mkdir(path.dirname(outputCsvPath), { recursive: true });
  await fs.mkdir(path.dirname(outputSvgPath), { recursive: true });

  await fs.writeFile(outputCsvPath, buildCsv(samples), "utf-8");
  await fs.writeFile(
    outputSvgPath,
    buildSvg(samples, {
      title: "Active Cars (05:00-15:00)",
      maxActiveCars
    }),
    "utf-8"
  );

  console.log(JSON.stringify({
    output_csv: path.relative(process.cwd(), outputCsvPath),
    output_svg: path.relative(process.cwd(), outputSvgPath),
    samples: samples.length,
    max_active_cars: maxActiveCars,
    start_min: options.startMin,
    end_min: endMin
  }, null, 2));
}

function buildCsv(samples) {
  const lines = ["time_min,active_cars"];
  samples.forEach((sample) => {
    lines.push(`${sample.time_min},${sample.active_cars}`);
  });
  return `${lines.join("\n")}\n`;
}

function buildSvg(samples, options) {
  const width = 1280;
  const height = 720;
  const marginLeft = 72;
  const marginRight = 24;
  const marginTop = 52;
  const marginBottom = 60;
  const plotWidth = width - marginLeft - marginRight;
  const plotHeight = height - marginTop - marginBottom;
  const minTime = samples[0]?.time_min ?? 0;
  const maxTime = samples[samples.length - 1]?.time_min ?? minTime + 1;
  const maxActiveCars = Math.max(1, options.maxActiveCars);

  const xScale = (timeMin) => {
    const ratio = (timeMin - minTime) / Math.max(1e-9, maxTime - minTime);
    return marginLeft + ratio * plotWidth;
  };
  const yScale = (activeCars) => {
    const ratio = activeCars / maxActiveCars;
    return marginTop + plotHeight - ratio * plotHeight;
  };

  const polylinePoints = samples
    .map((sample) => `${round(xScale(sample.time_min), 2)},${round(yScale(sample.active_cars), 2)}`)
    .join(" ");

  const yTicks = 5;
  const yTickElements = [];
  for (let tickIndex = 0; tickIndex <= yTicks; tickIndex += 1) {
    const value = round(maxActiveCars * tickIndex / yTicks, 0);
    const y = round(yScale(value), 2);
    yTickElements.push(
      `<line x1="${marginLeft}" y1="${y}" x2="${width - marginRight}" y2="${y}" stroke="#e5e7eb" stroke-width="1" />`
    );
    yTickElements.push(
      `<text x="${marginLeft - 10}" y="${y + 4}" text-anchor="end" font-size="12" fill="#374151">${value}</text>`
    );
  }

  const hourTicks = [];
  const startHour = Math.ceil(minTime / 60);
  const endHour = Math.floor(maxTime / 60);
  for (let hour = startHour; hour <= endHour; hour += 1) {
    const timeMin = hour * 60;
    const x = round(xScale(timeMin), 2);
    const label = `${String(hour).padStart(2, "0")}:00`;
    hourTicks.push(
      `<line x1="${x}" y1="${marginTop}" x2="${x}" y2="${marginTop + plotHeight}" stroke="#f3f4f6" stroke-width="1" />`
    );
    hourTicks.push(
      `<text x="${x}" y="${height - marginBottom + 24}" text-anchor="middle" font-size="12" fill="#374151">${label}</text>`
    );
  }

  return `<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}">
  <rect width="${width}" height="${height}" fill="#ffffff" />
  <text x="${marginLeft}" y="28" font-size="20" font-weight="700" fill="#111827">${escapeXml(options.title)}</text>
  <text x="${marginLeft}" y="46" font-size="12" fill="#6b7280">max_active_cars=${options.maxActiveCars}, samples=${samples.length}</text>
  ${yTickElements.join("\n  ")}
  ${hourTicks.join("\n  ")}
  <line x1="${marginLeft}" y1="${marginTop + plotHeight}" x2="${width - marginRight}" y2="${marginTop + plotHeight}" stroke="#111827" stroke-width="1.5" />
  <line x1="${marginLeft}" y1="${marginTop}" x2="${marginLeft}" y2="${marginTop + plotHeight}" stroke="#111827" stroke-width="1.5" />
  <polyline fill="none" stroke="#d04d2f" stroke-width="2" points="${polylinePoints}" />
  <text x="${width / 2}" y="${height - 12}" text-anchor="middle" font-size="13" fill="#111827">time</text>
  <text x="18" y="${height / 2}" transform="rotate(-90 18 ${height / 2})" text-anchor="middle" font-size="13" fill="#111827">active cars</text>
</svg>`;
}

function sliceScenarioByTimeRange(scenario, startMin, endMin) {
  const slicedObservationPoints = scenario.observation_points
    .map((observationPoint) => {
      const trafficVolume = observationPoint.traffic_volume.filter((record) => {
        if (startMin !== null && record.time_min < startMin) {
          return false;
        }
        if (endMin !== null && record.time_min > endMin) {
          return false;
        }
        return true;
      });

      return {
        ...observationPoint,
        traffic_volume: trafficVolume
      };
    })
    .filter((observationPoint) => observationPoint.traffic_volume.length > 0);

  return {
    ...scenario,
    meta: {
      ...(scenario.meta ?? {}),
      start_time_min: startMin ?? scenario.meta?.start_time_min ?? 0,
      end_time_min: endMin ?? scenario.meta?.end_time_min ?? null
    },
    observation_points: slicedObservationPoints
  };
}

function inferEndMin(scenario) {
  const requestTimes = scenario.observation_points.flatMap((observationPoint) => (
    observationPoint.traffic_volume.map((record) => record.time_min)
  ));
  const lastRequestTime = Math.max(...requestTimes);
  const requestWindowMin = scenario.simulation_config.request_window_min ?? 5;
  return lastRequestTime + requestWindowMin;
}

function round(value, digits) {
  const scale = 10 ** digits;
  return Math.round(value * scale) / scale;
}

function escapeXml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll("\"", "&quot;")
    .replaceAll("'", "&apos;");
}

function parseOptions(args) {
  const options = {
    scenario: DEFAULT_SCENARIO_PATH,
    outputCsv: DEFAULT_OUTPUT_CSV_PATH,
    outputSvg: DEFAULT_OUTPUT_SVG_PATH,
    startMin: 300,
    endMin: 900
  };

  for (let index = 0; index < args.length; index += 1) {
    const name = args[index];
    const value = args[index + 1];

    if (name === "--scenario") {
      options.scenario = value;
      index += 1;
    } else if (name === "--output-csv") {
      options.outputCsv = value;
      index += 1;
    } else if (name === "--output-svg") {
      options.outputSvg = value;
      index += 1;
    } else if (name === "--start-min") {
      options.startMin = Number(value);
      index += 1;
    } else if (name === "--end-min") {
      options.endMin = Number(value);
      index += 1;
    }
  }

  if (!Number.isFinite(options.startMin) || !Number.isFinite(options.endMin)) {
    throw new Error("--start-min と --end-min は数値にしてください。");
  }
  if (options.startMin >= options.endMin) {
    throw new Error("--start-min は --end-min より小さくしてください。");
  }

  return options;
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
