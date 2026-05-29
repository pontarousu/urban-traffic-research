#!/usr/bin/env python3
"""intersection ごとの theta 更新量をビューア用 JSON に変換する。"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path
from statistics import median
from typing import Any


DEFAULT_SNAPSHOT_DIR = Path("data/road_db_snapshots/road_db_prototype_tokyo_core_small_runtime_current")
DEFAULT_RESULT_DIR = Path("results/road_db_training_upstream_300_1000_distance1000_duration40")
DEFAULT_OUTPUT_PATH = Path("viewer/data/intersection_update_heatmap.json")


ROAD_TYPE_WEIGHT = {
    "motorway": 7,
    "trunk": 6,
    "trunk_link": 6,
    "primary": 5,
    "primary_link": 5,
    "secondary": 4,
    "secondary_link": 4,
    "tertiary": 3,
    "tertiary_link": 3,
    "unclassified": 2,
    "residential": 1,
    "living_street": 1,
    "service": 0,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="intersection 更新ヒートマップを出力する。")
    parser.add_argument("--snapshot-dir", type=Path, default=DEFAULT_SNAPSHOT_DIR)
    parser.add_argument("--result-dir", type=Path, default=DEFAULT_RESULT_DIR)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--padding-degree", type=float, default=0.004)
    parser.add_argument("--min-road-type-weight", type=int, default=2)
    return parser.parse_args()


def load_json(path: Path) -> Any:
    with path.open() as file:
        return json.load(file)


def quantile(values: list[float], ratio: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * ratio)))
    return ordered[index]


def aggregate_updates(result_dir: Path) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    by_node: dict[str, dict[str, Any]] = {}
    iteration_dirs = sorted(result_dir.glob("iteration_*"))
    diagnostics_paths = [path / "backtrace_diagnostics.csv" for path in iteration_dirs]
    diagnostics_paths = [path for path in diagnostics_paths if path.exists()]

    total_rows = 0
    mode_counts: Counter[str] = Counter()
    for path in diagnostics_paths:
        with path.open() as file:
            reader = csv.DictReader(file)
            for row in reader:
                total_rows += 1
                node_id = row["node_id"]
                delta = float(row["delta_theta_raw"])
                distance = float(row["distance_to_observation_meter"] or 0)
                mode_counts[row.get("backtrace_mode", "unknown")] += 1
                item = by_node.setdefault(
                    node_id,
                    {
                        "node_id": node_id,
                        "update_count": 0,
                        "abs_delta_sum": 0.0,
                        "signed_delta_sum": 0.0,
                        "positive_count": 0,
                        "negative_count": 0,
                        "theta_keys": set(),
                        "iterations": set(),
                        "distance_values": [],
                    },
                )
                item["update_count"] += 1
                item["abs_delta_sum"] += abs(delta)
                item["signed_delta_sum"] += delta
                item["positive_count"] += 1 if delta > 0 else 0
                item["negative_count"] += 1 if delta < 0 else 0
                item["theta_keys"].add(row["theta_key"])
                item["iterations"].add(row["iteration"])
                item["distance_values"].append(distance)

    for item in by_node.values():
        distances = item.pop("distance_values")
        item["unique_theta_count"] = len(item.pop("theta_keys"))
        item["iteration_count"] = len(item.pop("iterations"))
        item["mean_distance_meter"] = sum(distances) / len(distances) if distances else 0.0
        item["median_distance_meter"] = median(distances) if distances else 0.0

    summary = {
        "diagnostics_file_count": len(diagnostics_paths),
        "raw_update_row_count": total_rows,
        "updated_intersection_count": len(by_node),
        "backtrace_mode_counts": dict(mode_counts),
    }
    return by_node, summary


def build_edge_metadata(core: dict[str, Any]) -> dict[str, dict[str, Any]]:
    by_topology_edge: dict[str, dict[str, Any]] = {}
    for edge in core["graph"]["directed_edges"]:
        topology_edge_id = edge["topology_edge_id"]
        current = by_topology_edge.get(topology_edge_id)
        if current is None:
            by_topology_edge[topology_edge_id] = {
                "topology_edge_id": topology_edge_id,
                "road_type": edge.get("road_type"),
                "lane_count_total": edge.get("lane_count_total"),
                "speed_limit_kmh": edge.get("speed_limit_kmh"),
            }
            continue
        current_weight = ROAD_TYPE_WEIGHT.get(current.get("road_type"), -1)
        next_weight = ROAD_TYPE_WEIGHT.get(edge.get("road_type"), -1)
        if next_weight > current_weight:
            current["road_type"] = edge.get("road_type")
        current["lane_count_total"] = max(
            current.get("lane_count_total") or 0,
            edge.get("lane_count_total") or 0,
        )
        current["speed_limit_kmh"] = max(
            current.get("speed_limit_kmh") or 0,
            edge.get("speed_limit_kmh") or 0,
        )
    return by_topology_edge


def attach_locations(
    updates: dict[str, dict[str, Any]],
    core: dict[str, Any],
) -> list[dict[str, Any]]:
    intersections_by_node = {
        item["topology_node_id"]: item
        for item in core["intersections"]
    }
    output = []
    missing = 0
    for node_id, item in updates.items():
        intersection = intersections_by_node.get(node_id)
        if intersection is None:
            missing += 1
            continue
        output.append(
            {
                **item,
                "intersection_id": intersection["intersection_id"],
                "lat": intersection["lat"],
                "lon": intersection["lon"],
                "degree": intersection.get("degree"),
            }
        )
    output.sort(key=lambda item: item["abs_delta_sum"], reverse=True)
    return output, missing


def compute_bounds(points: list[dict[str, Any]], padding_degree: float) -> dict[str, float]:
    min_lat = min(item["lat"] for item in points)
    max_lat = max(item["lat"] for item in points)
    min_lon = min(item["lon"] for item in points)
    max_lon = max(item["lon"] for item in points)
    return {
        "min_lat": min_lat - padding_degree,
        "max_lat": max_lat + padding_degree,
        "min_lon": min_lon - padding_degree,
        "max_lon": max_lon + padding_degree,
    }


def point_in_bounds(point: dict[str, float], bounds: dict[str, float]) -> bool:
    return (
        bounds["min_lat"] <= point["lat"] <= bounds["max_lat"]
        and bounds["min_lon"] <= point["lon"] <= bounds["max_lon"]
    )


def build_roads(
    geometry: dict[str, Any],
    edge_metadata: dict[str, dict[str, Any]],
    bounds: dict[str, float],
    min_road_type_weight: int,
) -> list[dict[str, Any]]:
    roads = []
    for edge_id, geometry_item in geometry["topology_edge_geometries"].items():
        shape_points = geometry_item.get("shape_points") or []
        if not shape_points:
            continue
        meta = edge_metadata.get(edge_id, {})
        if ROAD_TYPE_WEIGHT.get(meta.get("road_type"), -1) < min_road_type_weight:
            continue
        if not any(point_in_bounds(point, bounds) for point in shape_points):
            continue
        roads.append(
            {
                "topology_edge_id": edge_id,
                "road_type": meta.get("road_type"),
                "lane_count_total": meta.get("lane_count_total"),
                "speed_limit_kmh": meta.get("speed_limit_kmh"),
                "shape_points": round_shape_points(shape_points),
            }
        )
    return roads


def round_shape_points(shape_points: list[dict[str, float]]) -> list[dict[str, float]]:
    """描画用に座標桁数を落として JSON を軽くする。"""

    return [
        {
            "lat": round(point["lat"], 7),
            "lon": round(point["lon"], 7),
        }
        for point in shape_points
    ]


def add_metric_summary(points: list[dict[str, Any]], summary: dict[str, Any]) -> None:
    for key in ["update_count", "abs_delta_sum", "unique_theta_count"]:
        values = [float(item[key]) for item in points]
        summary[f"{key}_min"] = min(values) if values else 0
        summary[f"{key}_median"] = median(values) if values else 0
        summary[f"{key}_p90"] = quantile(values, 0.9)
        summary[f"{key}_p99"] = quantile(values, 0.99)
        summary[f"{key}_max"] = max(values) if values else 0


def main() -> None:
    args = parse_args()
    core = load_json(args.snapshot_dir / "network_core.json")
    geometry = load_json(args.snapshot_dir / "network_geometry.json")
    updates, summary = aggregate_updates(args.result_dir)
    points, missing_location_count = attach_locations(updates, core)
    if not points:
        raise RuntimeError("位置付きの更新 intersection がありません。")

    bounds = compute_bounds(points, args.padding_degree)
    roads = build_roads(
        geometry,
        build_edge_metadata(core),
        bounds,
        args.min_road_type_weight,
    )
    add_metric_summary(points, summary)
    summary["missing_location_count"] = missing_location_count
    summary["road_line_count"] = len(roads)
    summary["min_road_type_weight"] = args.min_road_type_weight
    summary["result_dir"] = str(args.result_dir)

    output = {
        "schema_version": "intersection_update_heatmap.v1",
        "summary": summary,
        "bounds": bounds,
        "roads": roads,
        "intersections": points,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w") as file:
        json.dump(output, file, ensure_ascii=False, separators=(",", ":"))
    print(f"出力: {args.output}")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
