#!/usr/bin/env python3
"""診断用ビューアで使う可視化 JSON を出力する。"""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET_PATH = PROJECT_ROOT / "data/processed/small_forward_dataset.json"
DEFAULT_COMPARISON_PATH = PROJECT_ROOT / "results/training/final_comparison.csv"
DEFAULT_TRACES_PATH = PROJECT_ROOT / "results/training/final_traces.json"
DEFAULT_OUTPUT_PATH = PROJECT_ROOT / "viewer/data/diagnostics.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="発生源・流量・誤差の可視化データを作成します。")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET_PATH)
    parser.add_argument("--comparison", type=Path, default=DEFAULT_COMPARISON_PATH)
    parser.add_argument("--traces", type=Path, default=DEFAULT_TRACES_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    return parser.parse_args()


def load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as file:
        return json.load(file)


def load_comparison(path: Path) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    by_obs: dict[str, dict[str, Any]] = {}
    totals = {"observed_total": 0, "simulated_total": 0, "absolute_error_total": 0}
    with path.open(newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)
        for row in reader:
            obs_id = row["obs_id"]
            item = by_obs.setdefault(
                obs_id,
                {
                    "obs_id": obs_id,
                    "point_number": row.get("point_number"),
                    "point_name": row.get("point_name"),
                    "matched_way_id": row.get("matched_way_id"),
                    "observed_total": 0,
                    "simulated_total": 0,
                    "absolute_error_total": 0,
                },
            )
            observed = int(row["observed_count_5min"])
            simulated = int(row["simulated_count_5min"])
            absolute_error = int(row["absolute_error"])
            item["observed_total"] += observed
            item["simulated_total"] += simulated
            item["absolute_error_total"] += absolute_error
            totals["observed_total"] += observed
            totals["simulated_total"] += simulated
            totals["absolute_error_total"] += absolute_error
    for item in by_obs.values():
        item["error_total"] = item["simulated_total"] - item["observed_total"]
    return by_obs, totals


def summarize_traces(traces: dict[str, Any]) -> dict[str, Any]:
    source_by_way: dict[str, int] = defaultdict(int)
    source_by_category: dict[str, int] = defaultdict(int)
    flow_by_way: dict[str, int] = defaultdict(int)
    final_status: dict[str, int] = defaultdict(int)

    for vehicle in traces.get("vehicle_traces", []):
        source_way_id = vehicle.get("source_way_id")
        source_category = vehicle.get("source_category", "unknown")
        if source_way_id:
            source_by_way[source_way_id] += 1
        source_by_category[source_category] += 1
        final_status[vehicle.get("final_status", "unknown")] += 1
        for branch in vehicle.get("branch_trace", []):
            flow_by_way[branch["incoming_way_id"]] += 1
            flow_by_way[branch["outgoing_way_id"]] += 1

    return {
        "source_by_way": dict(source_by_way),
        "source_by_category": dict(source_by_category),
        "flow_by_way": dict(flow_by_way),
        "final_status": dict(final_status),
    }


def way_center(way: dict[str, Any]) -> dict[str, float]:
    points = way.get("shape_points") or []
    if not points:
        return {"lat": 0.0, "lon": 0.0}
    return {
        "lat": sum(float(point["lat"]) for point in points) / len(points),
        "lon": sum(float(point["lon"]) for point in points) / len(points),
    }


def build_visualization(dataset: dict[str, Any], comparison_by_obs: dict[str, dict[str, Any]], comparison_totals: dict[str, Any], trace_summary: dict[str, Any]) -> dict[str, Any]:
    source_candidates = dataset["calibration"].get("source_candidates", {})
    source_category_by_way = {}
    for category, items in source_candidates.get("categories", {}).items():
        for item in items:
            source_category_by_way[item["way_id"]] = category

    ways = []
    source_by_way = trace_summary["source_by_way"]
    flow_by_way = trace_summary["flow_by_way"]
    for way in dataset["graph"]["ways"]:
        center = way_center(way)
        ways.append(
            {
                "id": way["id"],
                "from_node_id": way["from_node_id"],
                "to_node_id": way["to_node_id"],
                "road_type": way.get("road_type"),
                "lane_count": way.get("lane_count"),
                "speed_limit_kmh": way.get("speed_limit_kmh"),
                "shape_points": way.get("shape_points", []),
                "center": center,
                "source_category": source_category_by_way.get(way["id"]),
                "spawn_count": source_by_way.get(way["id"], 0),
                "flow_count": flow_by_way.get(way["id"], 0),
            }
        )

    observations = []
    for observation in dataset["observations"]:
        item = comparison_by_obs.get(observation["id"], {})
        observations.append(
            {
                "id": observation["id"],
                "point_number": observation.get("point_number"),
                "point_name": observation.get("point_name"),
                "lat": observation["lat"],
                "lon": observation["lon"],
                "matched_way_id": observation["matched_way_id"],
                "observed_total": item.get("observed_total", 0),
                "simulated_total": item.get("simulated_total", 0),
                "error_total": item.get("error_total", 0),
                "absolute_error_total": item.get("absolute_error_total", 0),
            }
        )

    return {
        "schema_version": "0.1",
        "meta": dataset["meta"],
        "summary": {
            **comparison_totals,
            "source_by_category": trace_summary["source_by_category"],
            "final_status": trace_summary["final_status"],
        },
        "ways": ways,
        "observations": observations,
    }


def main() -> None:
    args = parse_args()
    dataset = load_json(args.dataset)
    traces = load_json(args.traces)
    comparison_by_obs, comparison_totals = load_comparison(args.comparison)
    trace_summary = summarize_traces(traces)
    output = build_visualization(dataset, comparison_by_obs, comparison_totals, trace_summary)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as file:
        json.dump(output, file, ensure_ascii=False)
    print(f"出力: {args.output}")
    print(f"Way数: {len(output['ways'])}")
    print(f"観測点数: {len(output['observations'])}")


if __name__ == "__main__":
    main()
