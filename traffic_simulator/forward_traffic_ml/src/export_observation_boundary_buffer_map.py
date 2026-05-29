#!/usr/bin/env python3
"""道路DB境界からの距離と観測点除外候補を地図ビューア用JSONへ出力する。"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ALIGNMENT_PATH = PROJECT_ROOT / "viewer/data/observation_alignment.json"
DEFAULT_GEOMETRY_PATH = (
    PROJECT_ROOT
    / "data/road_db_snapshots/road_db_prototype_tokyo_core_small_runtime_current"
    / "network_geometry.json"
)
DEFAULT_CORE_PATH = (
    PROJECT_ROOT
    / "data/road_db_snapshots/road_db_prototype_tokyo_core_small_runtime_current"
    / "network_core.json"
)
DEFAULT_ERROR_RATES_PATH = (
    PROJECT_ROOT
    / "results/observation_error_distribution_g150_iter40_same_edge_pair_warmup10"
    / "observation_error_rates.csv"
)
DEFAULT_OUTPUT_PATH = PROJECT_ROOT / "viewer/data/observation_boundary_buffer_map.json"


def parse_args() -> argparse.Namespace:
    """コマンドライン引数を読む。"""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--alignment", type=Path, default=DEFAULT_ALIGNMENT_PATH)
    parser.add_argument("--geometry", type=Path, default=DEFAULT_GEOMETRY_PATH)
    parser.add_argument("--core", type=Path, default=DEFAULT_CORE_PATH)
    parser.add_argument("--error-rates", type=Path, default=DEFAULT_ERROR_RATES_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--thresholds", type=float, nargs="+", default=[500.0, 1000.0])
    return parser.parse_args()


def main() -> None:
    """境界距離データを書き出す。"""

    args = parse_args()
    alignment = load_json(args.alignment)
    geometry = load_json(args.geometry)
    core = load_json(args.core)
    error_by_id = load_error_rates(args.error_rates)
    map_bounds = bounds_from_geometry(geometry)
    center_lat = (map_bounds["min_lat"] + map_bounds["max_lat"]) / 2.0
    observations = build_observations(alignment["observations"], error_by_id, map_bounds, center_lat)
    edge_layers = build_observation_edge_layers(observations, core, geometry)
    buffer_lines = build_buffer_lines(map_bounds, args.thresholds, center_lat)
    output = {
        "schema_version": "observation_boundary_buffer_map.v1",
        "source": {
            "alignment": str(args.alignment),
            "geometry": str(args.geometry),
            "core": str(args.core),
            "error_rates": str(args.error_rates),
        },
        "map_bounds": map_bounds,
        "bounds": combined_bounds(map_bounds, observations),
        "thresholds_meter": args.thresholds,
        "roads": alignment["roads"],
        "buffer_lines": buffer_lines,
        "matched_edges": edge_layers["matched_edges"],
        "connected_edges": edge_layers["connected_edges"],
        "observations": observations,
        "summary": build_summary(observations, args.thresholds, edge_layers),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as file:
        json.dump(output, file, ensure_ascii=False, indent=2)
    print(json.dumps(output["summary"], ensure_ascii=False, indent=2))
    print(f"出力: {args.output}")


def load_json(path: Path) -> dict[str, Any]:
    """JSONを読む。"""

    with path.open(encoding="utf-8") as file:
        return json.load(file)


def load_error_rates(path: Path) -> dict[str, dict[str, Any]]:
    """観測点別の誤差率を読む。"""

    if not path.exists():
        return {}
    output: dict[str, dict[str, Any]] = {}
    with path.open(newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)
        for row in reader:
            output[row["observation_id"]] = {
                **row,
                "observed_total": int(float(row["observed_total"])),
                "simulated_total": int(float(row["simulated_total"])),
                "error_total": int(float(row["error_total"])),
                "error_rate": float(row["error_rate"]),
            }
    return output


def bounds_from_geometry(geometry: dict[str, Any]) -> dict[str, float]:
    """道路DB geometry 全体のbboxを返す。"""

    min_lat = 90.0
    max_lat = -90.0
    min_lon = 180.0
    max_lon = -180.0
    for item in geometry.get("topology_edge_geometries", {}).values():
        for point in item.get("shape_points", []):
            min_lat = min(min_lat, float(point["lat"]))
            max_lat = max(max_lat, float(point["lat"]))
            min_lon = min(min_lon, float(point["lon"]))
            max_lon = max(max_lon, float(point["lon"]))
    return {
        "min_lat": min_lat,
        "max_lat": max_lat,
        "min_lon": min_lon,
        "max_lon": max_lon,
    }


def build_observations(
    raw_observations: list[dict[str, Any]],
    error_by_id: dict[str, dict[str, Any]],
    map_bounds: dict[str, float],
    center_lat: float,
) -> list[dict[str, Any]]:
    """観測点に境界距離と誤差情報を付ける。"""

    observations: list[dict[str, Any]] = []
    for obs in raw_observations:
        link = obs.get("matched_link") or {}
        error = error_by_id.get(obs["id"], {})
        boundary_distance = distance_to_bbox_edge_meter(obs["lat"], obs["lon"], map_bounds, center_lat)
        observations.append(
            {
                "observation_id": obs["id"],
                "point_number": obs.get("point_number"),
                "point_name": obs.get("point_name"),
                "lat": obs["lat"],
                "lon": obs["lon"],
                "boundary_distance_meter": round(boundary_distance, 1),
                "directed_edge_id": link.get("directed_edge_id"),
                "position_ratio": link.get("position_ratio"),
                "distance_meter": link.get("distance_meter"),
                "match_method": obs.get("match_method"),
                "match_confidence": obs.get("match_confidence"),
                "alignment_status": obs.get("alignment_status"),
                "warning_flags": obs.get("warning_flags", []),
                "observed_total": error.get("observed_total"),
                "simulated_total": error.get("simulated_total"),
                "error_rate": error.get("error_rate"),
            }
        )
    return observations


def build_observation_edge_layers(
    observations: list[dict[str, Any]],
    core: dict[str, Any],
    geometry: dict[str, Any],
) -> dict[str, list[dict[str, Any]]]:
    """観測点の対応edgeと、その両端ノードに接続するedgeを作る。"""

    directed_edges = {
        edge["directed_edge_id"]: edge
        for edge in core["graph"]["directed_edges"]
    }
    by_from_node: dict[str, list[dict[str, Any]]] = {}
    by_to_node: dict[str, list[dict[str, Any]]] = {}
    for edge in directed_edges.values():
        by_from_node.setdefault(edge["from_node_id"], []).append(edge)
        by_to_node.setdefault(edge["to_node_id"], []).append(edge)

    matched_meta: dict[str, dict[str, Any]] = {}
    connected_meta: dict[str, dict[str, Any]] = {}
    for obs in observations:
        matched_edge_id = obs.get("directed_edge_id")
        if not matched_edge_id:
            continue
        matched_edge = directed_edges.get(matched_edge_id)
        if not matched_edge:
            continue
        add_edge_meta(matched_meta, matched_edge, obs, "matched")
        start_node_id = matched_edge["from_node_id"]
        end_node_id = matched_edge["to_node_id"]
        for edge in by_to_node.get(start_node_id, []):
            add_edge_meta(connected_meta, edge, obs, "incoming_to_start")
        for edge in by_from_node.get(start_node_id, []):
            add_edge_meta(connected_meta, edge, obs, "outgoing_from_start")
        for edge in by_to_node.get(end_node_id, []):
            add_edge_meta(connected_meta, edge, obs, "incoming_to_end")
        for edge in by_from_node.get(end_node_id, []):
            add_edge_meta(connected_meta, edge, obs, "outgoing_from_end")
        connected_meta.pop(matched_edge_id, None)

    return {
        "matched_edges": edge_meta_to_features(matched_meta, geometry),
        "connected_edges": edge_meta_to_features(connected_meta, geometry),
    }


def add_edge_meta(
    edge_map: dict[str, dict[str, Any]],
    edge: dict[str, Any],
    obs: dict[str, Any],
    relation: str,
) -> None:
    """edge表示用メタ情報を集約する。"""

    edge_id = edge["directed_edge_id"]
    item = edge_map.setdefault(
        edge_id,
        {
            "directed_edge_id": edge_id,
            "topology_edge_id": edge.get("topology_edge_id"),
            "from_node_id": edge.get("from_node_id"),
            "to_node_id": edge.get("to_node_id"),
            "road_type": edge.get("road_type"),
            "lane_count_total": edge.get("lane_count_total"),
            "speed_limit_kmh": edge.get("speed_limit_kmh"),
            "length_meter": edge.get("length_meter"),
            "observation_ids": [],
            "point_numbers": [],
            "relations": [],
        },
    )
    if obs["observation_id"] not in item["observation_ids"]:
        item["observation_ids"].append(obs["observation_id"])
    point_number = obs.get("point_number")
    if point_number and point_number not in item["point_numbers"]:
        item["point_numbers"].append(point_number)
    if relation not in item["relations"]:
        item["relations"].append(relation)


def edge_meta_to_features(
    edge_map: dict[str, dict[str, Any]],
    geometry: dict[str, Any],
) -> list[dict[str, Any]]:
    """edgeメタ情報にgeometryを付ける。"""

    output: list[dict[str, Any]] = []
    directed_geometries = geometry.get("directed_edge_geometries", {})
    for edge_id, item in sorted(edge_map.items()):
        shape_points = directed_geometries.get(edge_id, {}).get("shape_points", [])
        if len(shape_points) < 2:
            continue
        output.append({**item, "shape_points": shape_points})
    return output


def distance_to_bbox_edge_meter(lat: float, lon: float, bounds: dict[str, float], center_lat: float) -> float:
    """bbox境界までの最短距離を概算メートルで返す。"""

    north = max(0.0, bounds["max_lat"] - lat) * 111_320.0
    south = max(0.0, lat - bounds["min_lat"]) * 111_320.0
    east = max(0.0, bounds["max_lon"] - lon) * meters_per_lon_degree(center_lat)
    west = max(0.0, lon - bounds["min_lon"]) * meters_per_lon_degree(center_lat)
    return min(north, south, east, west)


def build_buffer_lines(
    map_bounds: dict[str, float],
    thresholds: list[float],
    center_lat: float,
) -> list[dict[str, Any]]:
    """bboxから内側へ指定距離だけ入った矩形を返す。"""

    lines: list[dict[str, Any]] = []
    for threshold in thresholds:
        lat_offset = threshold / 111_320.0
        lon_offset = threshold / meters_per_lon_degree(center_lat)
        inner = {
            "min_lat": map_bounds["min_lat"] + lat_offset,
            "max_lat": map_bounds["max_lat"] - lat_offset,
            "min_lon": map_bounds["min_lon"] + lon_offset,
            "max_lon": map_bounds["max_lon"] - lon_offset,
        }
        if inner["min_lat"] >= inner["max_lat"] or inner["min_lon"] >= inner["max_lon"]:
            continue
        lines.append(
            {
                "threshold_meter": threshold,
                "shape_points": [
                    {"lat": inner["min_lat"], "lon": inner["min_lon"]},
                    {"lat": inner["min_lat"], "lon": inner["max_lon"]},
                    {"lat": inner["max_lat"], "lon": inner["max_lon"]},
                    {"lat": inner["max_lat"], "lon": inner["min_lon"]},
                    {"lat": inner["min_lat"], "lon": inner["min_lon"]},
                ],
            }
        )
    return lines


def combined_bounds(map_bounds: dict[str, float], observations: list[dict[str, Any]]) -> dict[str, float]:
    """表示用bboxを返す。"""

    min_lat = min([map_bounds["min_lat"], *[obs["lat"] for obs in observations]])
    max_lat = max([map_bounds["max_lat"], *[obs["lat"] for obs in observations]])
    min_lon = min([map_bounds["min_lon"], *[obs["lon"] for obs in observations]])
    max_lon = max([map_bounds["max_lon"], *[obs["lon"] for obs in observations]])
    lat_padding = (max_lat - min_lat) * 0.03
    lon_padding = (max_lon - min_lon) * 0.03
    return {
        "min_lat": min_lat - lat_padding,
        "max_lat": max_lat + lat_padding,
        "min_lon": min_lon - lon_padding,
        "max_lon": max_lon + lon_padding,
    }


def build_summary(
    observations: list[dict[str, Any]],
    thresholds: list[float],
    edge_layers: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    """境界距離による除外候補数を集計する。"""

    eval_observations = [obs for obs in observations if obs.get("observed_total") is not None]
    summary: dict[str, Any] = {
        "observation_count": len(observations),
        "evaluation_observation_count": len(eval_observations),
        "matched_edge_count": len(edge_layers["matched_edges"]),
        "connected_edge_count": len(edge_layers["connected_edges"]),
        "thresholds": {},
    }
    for threshold in thresholds:
        excluded_all = [obs for obs in observations if obs["boundary_distance_meter"] < threshold]
        excluded_eval = [obs for obs in eval_observations if obs["boundary_distance_meter"] < threshold]
        summary["thresholds"][str(int(threshold))] = {
            "excluded_all_count": len(excluded_all),
            "included_all_count": len(observations) - len(excluded_all),
            "excluded_evaluation_count": len(excluded_eval),
            "included_evaluation_count": len(eval_observations) - len(excluded_eval),
            "excluded_evaluation_points": [
                {
                    "point_number": obs.get("point_number"),
                    "point_name": obs.get("point_name"),
                    "boundary_distance_meter": obs["boundary_distance_meter"],
                    "observed_total": obs.get("observed_total"),
                    "simulated_total": obs.get("simulated_total"),
                    "error_rate": obs.get("error_rate"),
                }
                for obs in sorted(excluded_eval, key=lambda item: item["boundary_distance_meter"])
            ],
        }
    return summary


def meters_per_lon_degree(lat: float) -> float:
    """指定緯度における経度1度あたりの距離を返す。"""

    import math

    return 111_320.0 * math.cos(math.radians(lat))


if __name__ == "__main__":
    main()
