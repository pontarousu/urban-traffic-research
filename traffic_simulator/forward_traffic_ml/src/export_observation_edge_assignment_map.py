#!/usr/bin/env python3
"""観測点と対応 directed_edge の地図ビューア用JSONを作る。"""

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
DEFAULT_ERROR_RATES_PATH = (
    PROJECT_ROOT
    / "results/observation_error_distribution_g150_iter40_warmup10"
    / "observation_error_rates.csv"
)
DEFAULT_OUTPUT_PATH = PROJECT_ROOT / "viewer/data/observation_edge_assignment_map.json"


def parse_args() -> argparse.Namespace:
    """コマンドライン引数を読む。"""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--alignment", type=Path, default=DEFAULT_ALIGNMENT_PATH)
    parser.add_argument("--geometry", type=Path, default=DEFAULT_GEOMETRY_PATH)
    parser.add_argument("--error-rates", type=Path, default=DEFAULT_ERROR_RATES_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    return parser.parse_args()


def main() -> None:
    """地図用JSONを書き出す。"""

    args = parse_args()
    alignment = load_json(args.alignment)
    geometry = load_json(args.geometry)
    error_by_id = load_error_rates(args.error_rates)
    observations = build_observations(alignment, geometry, error_by_id)
    directed_edges = build_directed_edges(observations)
    output = {
        "schema_version": "observation_edge_assignment_map.v1",
        "source": {
            "alignment": str(args.alignment),
            "geometry": str(args.geometry),
            "error_rates": str(args.error_rates),
        },
        "bounds": alignment["bounds"],
        "roads": alignment["roads"],
        "observations": observations,
        "directed_edges": directed_edges,
        "summary": build_summary(observations, directed_edges),
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
                "observed_total": int(float(row["observed_total"])),
                "simulated_total": int(float(row["simulated_total"])),
                "error_total": int(float(row["error_total"])),
                "error_rate": float(row["error_rate"]),
                "ratio": float(row["ratio"]),
            }
    return output


def build_observations(
    alignment: dict[str, Any],
    geometry: dict[str, Any],
    error_by_id: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """観測点と対応 directed_edge 情報を結合する。"""

    directed_geometry = geometry.get("directed_edge_geometries", {})
    output: list[dict[str, Any]] = []
    for item in alignment.get("observations", []):
        link = item.get("matched_link")
        if not link:
            continue
        directed_edge_id = link["directed_edge_id"]
        shape_points = directed_geometry.get(directed_edge_id, {}).get("shape_points") or link.get("shape_points", [])
        nearest_point = link.get("nearest_point") or interpolate_shape(shape_points, float(link.get("position_ratio") or 0.5))
        error = error_by_id.get(item["id"], {})
        output.append(
            {
                "observation_id": item["id"],
                "point_number": item.get("point_number"),
                "point_name": item.get("point_name"),
                "lat": item["lat"],
                "lon": item["lon"],
                "directed_edge_id": directed_edge_id,
                "topology_edge_id": link.get("topology_edge_id"),
                "road_type": link.get("road_type"),
                "lane_count_total": link.get("lane_count_total"),
                "speed_limit_kmh": link.get("speed_limit_kmh"),
                "length_meter": link.get("length_meter"),
                "position_ratio": link.get("position_ratio"),
                "nearest_point": nearest_point,
                "bearing_deg": link.get("bearing_deg"),
                "match_method": item.get("match_method"),
                "match_confidence": item.get("match_confidence"),
                "warning_flags": item.get("warning_flags", []),
                "shape_points": shape_points,
                "observed_total": error.get("observed_total"),
                "simulated_total": error.get("simulated_total"),
                "error_total": error.get("error_total"),
                "error_rate": error.get("error_rate"),
                "ratio": error.get("ratio"),
            }
        )
    return output


def build_directed_edges(observations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """観測点に対応している directed_edge を重複排除して返す。"""

    edges: dict[str, dict[str, Any]] = {}
    for obs in observations:
        edge = edges.setdefault(
            obs["directed_edge_id"],
            {
                "directed_edge_id": obs["directed_edge_id"],
                "topology_edge_id": obs.get("topology_edge_id"),
                "road_type": obs.get("road_type"),
                "lane_count_total": obs.get("lane_count_total"),
                "speed_limit_kmh": obs.get("speed_limit_kmh"),
                "length_meter": obs.get("length_meter"),
                "shape_points": obs.get("shape_points", []),
                "observation_ids": [],
                "point_numbers": [],
            },
        )
        edge["observation_ids"].append(obs["observation_id"])
        edge["point_numbers"].append(obs.get("point_number"))
    return list(edges.values())


def interpolate_shape(shape_points: list[dict[str, float]], ratio: float) -> dict[str, float] | None:
    """shape上の概算点を返す。"""

    if not shape_points:
        return None
    if len(shape_points) == 1:
        return shape_points[0]
    clamped = min(1.0, max(0.0, ratio))
    index = min(len(shape_points) - 2, int(clamped * (len(shape_points) - 1)))
    local = clamped * (len(shape_points) - 1) - index
    a = shape_points[index]
    b = shape_points[index + 1]
    return {
        "lat": a["lat"] + (b["lat"] - a["lat"]) * local,
        "lon": a["lon"] + (b["lon"] - a["lon"]) * local,
    }


def build_summary(observations: list[dict[str, Any]], directed_edges: list[dict[str, Any]]) -> dict[str, Any]:
    """summaryを作る。"""

    confidence_counts: dict[str, int] = {}
    for obs in observations:
        confidence = obs.get("match_confidence") or "unknown"
        confidence_counts[confidence] = confidence_counts.get(confidence, 0) + 1
    return {
        "observation_count": len(observations),
        "matched_directed_edge_count": len(directed_edges),
        "match_confidence_counts": confidence_counts,
    }


if __name__ == "__main__":
    main()
