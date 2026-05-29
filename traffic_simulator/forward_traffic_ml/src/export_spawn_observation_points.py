#!/usr/bin/env python3
"""観測点と車両発生位置を同じ地図で確認するビューア用JSONを出力する。"""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ALIGNMENT_PATH = PROJECT_ROOT / "viewer/data/observation_alignment.json"
DEFAULT_TRACE_PATH = PROJECT_ROOT / "results/road_db_phase3_observation_upstream_distributed_smoke/vehicle_traces.json"
DEFAULT_GEOMETRY_PATH = PROJECT_ROOT / "data/road_db_snapshots/road_db_prototype_tokyo_core_small_runtime_current/network_geometry.json"
DEFAULT_CORE_PATH = PROJECT_ROOT / "data/road_db_snapshots/road_db_prototype_tokyo_core_small_runtime_current/network_core.json"
DEFAULT_OUTPUT_PATH = PROJECT_ROOT / "viewer/data/spawn_observation_points.json"


def parse_args() -> argparse.Namespace:
    """コマンドライン引数を読む。"""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--alignment", type=Path, default=DEFAULT_ALIGNMENT_PATH)
    parser.add_argument("--traces", type=Path, default=DEFAULT_TRACE_PATH)
    parser.add_argument("--geometry", type=Path, default=DEFAULT_GEOMETRY_PATH)
    parser.add_argument("--core", type=Path, default=DEFAULT_CORE_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    return parser.parse_args()


def load_json(path: Path) -> Any:
    """JSONを読む。"""

    with path.open(encoding="utf-8") as file:
        return json.load(file)


def main() -> None:
    """ビューア用JSONを出力する。"""

    args = parse_args()
    alignment = load_json(args.alignment)
    traces = load_json(args.traces)
    geometry = load_json(args.geometry)
    core = load_json(args.core)
    edges_by_id = {
        edge["directed_edge_id"]: edge
        for edge in core["graph"]["directed_edges"]
    }
    directed_geometries = geometry["directed_edge_geometries"]

    observations = build_observations(alignment)
    spawn_points = build_spawn_points(
        traces=traces,
        directed_geometries=directed_geometries,
        edges_by_id=edges_by_id,
    )
    output = {
        "schema_version": "spawn_observation_points.v1",
        "source": {
            "alignment": str(args.alignment),
            "traces": str(args.traces),
            "geometry": str(args.geometry),
            "core": str(args.core),
        },
        "summary": summarize(observations, spawn_points),
        "bounds": combined_bounds(alignment.get("roads", []), observations, spawn_points),
        "roads": alignment.get("roads", []),
        "observations": observations,
        "spawn_points": spawn_points,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as file:
        json.dump(output, file, ensure_ascii=False)
    print(f"出力: {args.output}")
    print(json.dumps(output["summary"], ensure_ascii=False, indent=2))


def build_observations(alignment: dict[str, Any]) -> list[dict[str, Any]]:
    """観測点表示用データを作る。"""

    observations = []
    for obs in alignment.get("observations", []):
        link = obs.get("matched_link") or {}
        observations.append(
            {
                "observation_id": obs["id"],
                "point_number": obs.get("point_number"),
                "point_name": obs.get("point_name"),
                "lat": obs["lat"],
                "lon": obs["lon"],
                "observed_total": obs.get("observed_total", 0),
                "match_method": obs.get("match_method"),
                "match_confidence": obs.get("match_confidence"),
                "directed_edge_id": link.get("directed_edge_id"),
                "position_ratio": link.get("position_ratio"),
                "has_direction_conflict_pair": obs.get("has_direction_conflict_pair", False),
            }
        )
    return observations


def build_spawn_points(
    *,
    traces: dict[str, Any],
    directed_geometries: dict[str, dict[str, Any]],
    edges_by_id: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """車両traceから1台ごとの発生点を作る。"""

    edge_seen_count: dict[str, int] = defaultdict(int)
    spawn_points: list[dict[str, Any]] = []
    for trace in traces.get("vehicle_traces", []):
        edge_id = trace["source_edge_id"]
        shape_points = directed_geometries.get(edge_id, {}).get("shape_points", [])
        if not shape_points:
            continue
        edge = edges_by_id.get(edge_id, {})
        edge_seen_count[edge_id] += 1
        source_point = point_at_position(
            shape_points,
            float(edge.get("length_meter") or 1.0),
            float(trace.get("source_position_meter") or 0.0),
        )
        spawn_points.append(
            {
                "vehicle_id": trace["vehicle_id"],
                "source_edge_id": edge_id,
                "source_category": trace.get("source_category"),
                "source_mesh_id": trace.get("source_mesh_id"),
                "source_position_meter": trace.get("source_position_meter"),
                "lat": source_point["lat"],
                "lon": source_point["lon"],
                "edge_spawn_index": edge_seen_count[edge_id],
                "edge_spawn_count": None,
                "road_type": edge.get("road_type"),
                "lane_count_total": edge.get("lane_count_total"),
                "speed_limit_kmh": edge.get("speed_limit_kmh"),
                "observation_trace_count": len(trace.get("observation_trace", [])),
                "branch_trace_count": len(trace.get("branch_trace", [])),
                "final_status": trace.get("final_status"),
            }
        )

    counts_by_edge = Counter(point["source_edge_id"] for point in spawn_points)
    for point in spawn_points:
        point["edge_spawn_count"] = counts_by_edge[point["source_edge_id"]]
    return spawn_points


def point_at_position(
    shape_points: list[dict[str, float]],
    edge_length_meter: float,
    position_meter: float,
) -> dict[str, float]:
    """edge上の距離から表示用の緯度経度を概算する。"""

    if len(shape_points) <= 1:
        return shape_points[0]
    ratio = min(1.0, max(0.0, position_meter / max(1.0, edge_length_meter)))
    segments = []
    total = 0.0
    for index in range(len(shape_points) - 1):
        start = shape_points[index]
        end = shape_points[index + 1]
        length = math_hypot_lat_lon(start, end)
        segments.append((start, end, length))
        total += length
    target = total * ratio
    current = 0.0
    for start, end, length in segments:
        if current + length >= target:
            local_ratio = (target - current) / max(length, 1e-12)
            return {
                "lat": start["lat"] + (end["lat"] - start["lat"]) * local_ratio,
                "lon": start["lon"] + (end["lon"] - start["lon"]) * local_ratio,
            }
        current += length
    return shape_points[-1]


def math_hypot_lat_lon(start: dict[str, float], end: dict[str, float]) -> float:
    """表示用の簡易距離を返す。"""

    lat_scale = 111_320.0
    lon_scale = 111_320.0
    return math.hypot((end["lat"] - start["lat"]) * lat_scale, (end["lon"] - start["lon"]) * lon_scale)


def summarize(observations: list[dict[str, Any]], spawn_points: list[dict[str, Any]]) -> dict[str, Any]:
    """表示用サマリを作る。"""

    source_category_counts = Counter(point["source_category"] for point in spawn_points)
    source_mesh_counts = Counter(point["source_mesh_id"] for point in spawn_points if point.get("source_mesh_id"))
    final_status_counts = Counter(point["final_status"] for point in spawn_points)
    return {
        "observation_count": len(observations),
        "spawn_vehicle_count": len(spawn_points),
        "spawn_edge_count": len(set(point["source_edge_id"] for point in spawn_points)),
        "spawn_mesh_count": len(source_mesh_counts),
        "vehicles_with_observation_trace": sum(1 for point in spawn_points if point["observation_trace_count"] > 0),
        "source_category_counts": dict(source_category_counts),
        "top_spawn_meshes": source_mesh_counts.most_common(20),
        "final_status_counts": dict(final_status_counts),
    }


def combined_bounds(
    roads: list[dict[str, Any]],
    observations: list[dict[str, Any]],
    spawn_points: list[dict[str, Any]],
) -> dict[str, float]:
    """道路・観測点・発生点を含むbboxを返す。"""

    points: list[dict[str, float]] = []
    for road in roads:
        points.extend(road.get("shape_points", []))
    points.extend({"lat": obs["lat"], "lon": obs["lon"]} for obs in observations)
    points.extend({"lat": point["lat"], "lon": point["lon"]} for point in spawn_points)
    return {
        "min_lat": min(point["lat"] for point in points),
        "max_lat": max(point["lat"] for point in points),
        "min_lon": min(point["lon"] for point in points),
        "max_lon": max(point["lon"] for point in points),
    }


if __name__ == "__main__":
    main()
