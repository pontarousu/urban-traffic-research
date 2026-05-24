import fs from "node:fs/promises";
import path from "node:path";

const DEFAULT_INPUT_PATH =
  "../data/current/tokyo_core_small_realdata_osm_300obs_allday.json";
const DEFAULT_OUTPUT_PATH =
  "../data/current/tokyo_core_small_render_map.json";

async function main() {
  const options = parseOptions(process.argv.slice(2));
  const inputPath = path.resolve(options.input);
  const outputPath = path.resolve(options.output);
  const scenario = JSON.parse(await fs.readFile(inputPath, "utf-8"));

  const renderMap = {
    schema_version: "render_map_v1",
    meta: {
      title: scenario.meta?.scenario_name ?? "Render Map",
      source_scenario_id: scenario.meta?.scenario_id ?? null,
      view_box: scenario.meta?.view_box ?? null
    },
    roads: scenario.graph.ways.map((way) => ({
      id: way.id,
      road_type: way.road_type,
      lane_count: way.lane_count,
      shape_points: (way.shape_points ?? []).map((point) => ({
        view_x: point.view_x,
        view_y: point.view_y
      }))
    }))
  };

  await fs.writeFile(outputPath, JSON.stringify(renderMap));
  console.log(JSON.stringify({
    output: path.relative(process.cwd(), outputPath),
    road_count: renderMap.roads.length
  }, null, 2));
}

function parseOptions(args) {
  const options = {
    input: DEFAULT_INPUT_PATH,
    output: DEFAULT_OUTPUT_PATH
  };

  for (let index = 0; index < args.length; index += 1) {
    const name = args[index];
    const value = args[index + 1];

    if (name === "--input") {
      options.input = value;
      index += 1;
    } else if (name === "--output") {
      options.output = value;
      index += 1;
    }
  }

  return options;
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
