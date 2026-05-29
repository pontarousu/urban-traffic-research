#!/usr/bin/env python3
"""道路選択条件の違いを比較するための可視化 JSON を出力する。"""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any, Callable


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PROJECT_ROOT.parent

DEFAULT_SCENARIO_PATH = REPO_ROOT / "private_inputs/scenario.json"
DEFAULT_OUTPUT_PATH = PROJECT_ROOT / "viewer/data/road_variants.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="道路フィルタ別の地図可視化データを作成します。")
    parser.add_argument("--scenario", type=Path, default=DEFAULT_SCENARIO_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--center-observation-id", default=None)
    parser.add_argument("--start-min", type=int, default=480)
    parser.add_argument("--duration-min", type=int, default=60)
    parser.add_argument("--radius-meter", type=float, default=900.0)
    parser.add_argument("--max-observations", type=int, default=24)
    parser.add_argument("--max-ways", type=int, default=5000)
    return parser.parse_args()


def load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as file:
        return json.load(file)


def haversine_meter(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    earth_radius_meter = 6_371_000.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    a = math.sin(delta_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    return earth_radius_meter * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def observed_volume_in_window(observation: dict[str, Any], start_min: int, end_min: int) -> int:
    total = 0
    for record in observation.get("traffic_volume", []):
        time_min = int(record["time_min"])
        if start_min <= time_min < end_min:
            total += int(record["volume_5min"])
    return total


def choose_center_observation(
    observations: list[dict[str, Any]],
    center_observation_id: str | None,
    start_min: int,
    end_min: int,
) -> dict[str, Any]:
    if center_observation_id:
        for observation in observations:
            if observation["id"] == center_observation_id:
                return observation
        raise ValueError(f"指定された観測点が見つかりません: {center_observation_id}")
    return max(observations, key=lambda item: observed_volume_in_window(item, start_min, end_min))


def way_center(way: dict[str, Any], nodes_by_id: dict[str, dict[str, Any]]) -> tuple[float, float]:
    points = way.get("shape_points") or []
    if points:
        lat = sum(float(point["lat"]) for point in points) / len(points)
        lon = sum(float(point["lon"]) for point in points) / len(points)
        return lat, lon
    from_node = nodes_by_id[way["from_node_id"]]
    to_node = nodes_by_id[way["to_node_id"]]
    return (float(from_node["lat"]) + float(to_node["lat"])) / 2, (float(from_node["lon"]) + float(to_node["lon"])) / 2


def compact_way(way: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": way["id"],
        "from_node_id": way["from_node_id"],
        "to_node_id": way["to_node_id"],
        "road_type": way.get("road_type", "unknown"),
        "lane_count": int(way.get("lane_count") or 1),
        "length_meter": float(way.get("length_meter") or 0.0),
        "speed_limit_kmh": float(way.get("speed_limit_kmh") or 0.0),
        "shape_points": way.get("shape_points", []),
    }


def road_type(way: dict[str, Any]) -> str:
    return str(way.get("road_type") or "unknown")


def lane_count(way: dict[str, Any]) -> int:
    return int(way.get("lane_count") or 1)


def keep_current(way: dict[str, Any]) -> bool:
    return True


def keep_major_plus(way: dict[str, Any]) -> bool:
    road = road_type(way)
    lanes = lane_count(way)
    if road in {"motorway", "trunk", "primary", "secondary", "tertiary"}:
        return True
    if road in {"unclassified", "residential"} and lanes >= 2:
        return True
    return False


def keep_major_only(way: dict[str, Any]) -> bool:
    road = road_type(way)
    lanes = lane_count(way)
    if road in {"motorway", "trunk", "primary", "secondary"}:
        return True
    if lanes >= 3:
        return True
    return road == "tertiary" and lanes >= 2


FILTERS: list[tuple[str, str, Callable[[dict[str, Any]], bool]]] = [
    ("pattern_1_current", "現状相当: 半径内の道路を広く採用", keep_current),
    ("pattern_2_major_plus", "主要道路+準主要道路: tertiary 以上と一部2車線道路", keep_major_plus),
    ("pattern_3_major_only", "主要道路のみ: secondary 以上、または多車線道路", keep_major_only),
]


def select_base_candidates(
    scenario: dict[str, Any],
    center: dict[str, Any],
    start_min: int,
    end_min: int,
    radius_meter: float,
    max_observations: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    observations = scenario["observation_points"]
    center_lat = float(center["lat"])
    center_lon = float(center["lon"])

    nearby_observations = []
    for observation in observations:
        distance = haversine_meter(center_lat, center_lon, float(observation["lat"]), float(observation["lon"]))
        if distance <= radius_meter:
            item = dict(observation)
            item["_distance_meter"] = distance
            item["_window_volume"] = observed_volume_in_window(observation, start_min, end_min)
            nearby_observations.append(item)

    nearby_observations.sort(key=lambda item: (-item["_window_volume"], item["_distance_meter"]))
    selected_observations = nearby_observations[:max_observations]
    selected_way_ids = {observation["matched_way_id"] for observation in selected_observations}

    nodes_by_id = {node["id"]: node for node in scenario["graph"]["nodes"]}
    candidate_ways = []
    for way in scenario["graph"]["ways"]:
        lat, lon = way_center(way, nodes_by_id)
        distance = haversine_meter(center_lat, center_lon, lat, lon)
        if distance <= radius_meter or way["id"] in selected_way_ids:
            item = compact_way(way)
            item["_distance_meter"] = distance
            item["_is_observation_way"] = way["id"] in selected_way_ids
            candidate_ways.append(item)

    candidate_ways.sort(key=lambda item: (item["id"] not in selected_way_ids, item["_distance_meter"]))
    return candidate_ways, selected_observations


def build_variant(
    name: str,
    description: str,
    keep: Callable[[dict[str, Any]], bool],
    candidate_ways: list[dict[str, Any]],
    max_ways: int,
) -> dict[str, Any]:
    kept = []
    for way in candidate_ways:
        if keep(way) or way.get("_is_observation_way"):
            item = dict(way)
            item.pop("_distance_meter", None)
            kept.append(item)
        if len(kept) >= max_ways:
            break

    road_type_counts = Counter(road_type(way) for way in kept)
    lane_counts = Counter(str(lane_count(way)) for way in kept)
    observation_way_count = sum(1 for way in kept if way.get("_is_observation_way"))
    for way in kept:
        way.pop("_is_observation_way", None)

    return {
        "name": name,
        "description": description,
        "summary": {
            "way_count": len(kept),
            "observation_way_count": observation_way_count,
            "road_type_counts": dict(sorted(road_type_counts.items())),
            "lane_counts": dict(sorted(lane_counts.items())),
        },
        "ways": kept,
    }


def build_observations(observations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output = []
    for observation in observations:
        item = dict(observation)
        item.pop("traffic_volume", None)
        item.pop("_distance_meter", None)
        item.pop("_window_volume", None)
        output.append(item)
    return output


def main() -> None:
    args = parse_args()
    start_min = args.start_min
    end_min = args.start_min + args.duration_min
    scenario = load_json(args.scenario)
    center = choose_center_observation(scenario["observation_points"], args.center_observation_id, start_min, end_min)
    candidate_ways, observations = select_base_candidates(
        scenario=scenario,
        center=center,
        start_min=start_min,
        end_min=end_min,
        radius_meter=args.radius_meter,
        max_observations=args.max_observations,
    )
    variants = [
        build_variant(name, description, keep, candidate_ways, args.max_ways)
        for name, description, keep in FILTERS
    ]

    output = {
        "schema_version": "0.1",
        "meta": {
            "source_scenario": str(args.scenario),
            "center_observation_id": center["id"],
            "center_observation_name": center.get("point_name"),
            "start_min": start_min,
            "end_min": end_min,
            "radius_meter": args.radius_meter,
            "candidate_way_count_before_filter": len(candidate_ways),
        },
        "observations": build_observations(observations),
        "variants": variants,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as file:
        json.dump(output, file, ensure_ascii=False)

    print(f"出力: {args.output}")
    print(f"中心観測点: {center['id']} {center.get('point_name')}")
    print(f"フィルタ前Way数: {len(candidate_ways)}")
    for variant in variants:
        print(f"{variant['name']}: {variant['summary']['way_count']} ways")


if __name__ == "__main__":
    main()
