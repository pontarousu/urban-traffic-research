#!/usr/bin/env python3
"""順方向シミュレーション用の小領域データを作成する。"""

from __future__ import annotations

import argparse
import csv
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PROJECT_ROOT.parent

DEFAULT_SCENARIO_PATH = REPO_ROOT / "private_inputs/scenario.json"
DEFAULT_TRAFFIC_PATH = REPO_ROOT / "private_inputs/traffic_volume.json"
DEFAULT_LOCATION_PATH = REPO_ROOT / "private_inputs/observation_locations.csv"
DEFAULT_OUTPUT_PATH = PROJECT_ROOT / "data/processed/small_forward_dataset.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="小領域・短時間の順方向シミュレーション入力を作成します。")
    parser.add_argument("--scenario", type=Path, default=DEFAULT_SCENARIO_PATH)
    parser.add_argument("--traffic", type=Path, default=DEFAULT_TRAFFIC_PATH)
    parser.add_argument("--locations", type=Path, default=DEFAULT_LOCATION_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--center-observation-id", default=None)
    parser.add_argument("--start-min", type=int, default=480)
    parser.add_argument("--duration-min", type=int, default=30)
    parser.add_argument("--radius-meter", type=float, default=900.0)
    parser.add_argument("--target-observation-count", type=int, default=None)
    parser.add_argument("--radius-padding-meter", type=float, default=200.0)
    parser.add_argument("--max-observations", type=int, default=24)
    parser.add_argument("--max-ways", type=int, default=None)
    parser.add_argument("--generation-multiplier", type=float, default=1.5)
    parser.add_argument("--boundary-ratio", type=float, default=0.78)
    parser.add_argument(
        "--road-filter",
        choices=["current", "pattern_2_major_plus", "pattern_3_major_only"],
        default="current",
    )
    return parser.parse_args()


def load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as file:
        return json.load(file)


def load_location_lookup(path: Path) -> dict[tuple[str, str], dict[str, str]]:
    """地点番号 CSV を読み、シナリオ内の観測点と照合できる形にする。"""
    lookup: dict[tuple[str, str], dict[str, str]] = {}
    with path.open(newline="", encoding="cp932") as file:
        reader = csv.reader(file)
        rows = list(reader)
    if len(rows) < 2:
        return lookup

    header = rows[1]
    for row in rows[2:]:
        if len(row) < len(header):
            continue
        item = dict(zip(header, row))
        source_code = item.get("情報源コード")
        point_number = item.get("計測地点番号")
        if source_code and point_number:
            lookup[(source_code, point_number)] = item
    return lookup


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


def observed_by_bin(observation: dict[str, Any], start_min: int, end_min: int) -> dict[int, int]:
    values: dict[int, int] = {}
    for record in observation.get("traffic_volume", []):
        time_min = int(record["time_min"])
        if start_min <= time_min < end_min:
            values[time_min] = int(record["volume_5min"])
    return values


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


def decide_radius_by_observation_count(
    observations: list[dict[str, Any]],
    center: dict[str, Any],
    target_observation_count: int,
    radius_padding_meter: float,
) -> float:
    """目標観測点数を含む最小半径に余白を足して返す。"""
    if target_observation_count <= 0:
        raise ValueError("--target-observation-count は正の整数で指定してください。")
    center_lat = float(center["lat"])
    center_lon = float(center["lon"])
    distances = sorted(
        haversine_meter(center_lat, center_lon, float(observation["lat"]), float(observation["lon"]))
        for observation in observations
    )
    if not distances:
        raise ValueError("観測点がありません。")
    index = min(target_observation_count, len(distances)) - 1
    return distances[index] + max(0.0, radius_padding_meter)


def compact_way(way: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": way["id"],
        "from_node_id": way["from_node_id"],
        "to_node_id": way["to_node_id"],
        "road_type": way.get("road_type", "unknown"),
        "lane_count": int(way.get("lane_count") or 1),
        "length_meter": float(way.get("length_meter") or 50.0),
        "speed_limit_kmh": float(way.get("speed_limit_kmh") or 30.0),
        "storage_capacity_cars": int(way.get("storage_capacity_cars") or max(5, float(way.get("length_meter") or 50.0) // 6)),
        "shape_points": way.get("shape_points", []),
    }


def is_major_road(way: dict[str, Any]) -> bool:
    """OSM の道路種別と車線数から幹線道路かどうかを判定する。"""
    road_type = str(way.get("road_type") or "")
    lane_count = int(way.get("lane_count") or 1)
    if road_type in {"motorway", "trunk", "primary", "secondary"}:
        return True
    if lane_count >= 3:
        return True
    return road_type == "tertiary" and lane_count >= 2


def keep_way_by_filter(way: dict[str, Any], road_filter: str) -> bool:
    """道路選択パターンに応じて、シミュレーション対象 Way を残すか判定する。"""
    if road_filter == "current":
        return True

    road_type = str(way.get("road_type") or "")
    lane_count = int(way.get("lane_count") or 1)

    if road_filter == "pattern_2_major_plus":
        if road_type in {"motorway", "trunk", "primary", "secondary", "tertiary"}:
            return True
        return road_type in {"unclassified", "residential"} and lane_count >= 2

    if road_filter == "pattern_3_major_only":
        if road_type in {"motorway", "trunk", "primary", "secondary"}:
            return True
        if lane_count >= 3:
            return True
        return road_type == "tertiary" and lane_count >= 2

    raise ValueError(f"未対応の道路フィルタです: {road_filter}")


def road_priority_score(way: dict[str, Any]) -> float:
    """発生候補 Way の固定重みを作るための道路スコアを返す。"""
    road_type = str(way.get("road_type") or "")
    road_type_weight = {
        "motorway": 5.0,
        "trunk": 4.5,
        "primary": 4.0,
        "secondary": 3.0,
        "tertiary": 2.0,
        "unclassified": 1.2,
        "residential": 1.0,
        "service": 0.7,
        "living_street": 0.7,
    }.get(road_type, 1.0)
    lane_count = max(1, int(way.get("lane_count") or 1))
    speed_limit = max(10.0, float(way.get("speed_limit_kmh") or 30.0))
    return road_type_weight * math.sqrt(lane_count) * math.sqrt(speed_limit / 30.0)


def way_center(way: dict[str, Any], nodes_by_id: dict[str, dict[str, Any]]) -> tuple[float, float]:
    points = way.get("shape_points") or []
    if points:
        lat = sum(float(point["lat"]) for point in points) / len(points)
        lon = sum(float(point["lon"]) for point in points) / len(points)
        return lat, lon
    from_node = nodes_by_id[way["from_node_id"]]
    to_node = nodes_by_id[way["to_node_id"]]
    return (float(from_node["lat"]) + float(to_node["lat"])) / 2, (float(from_node["lon"]) + float(to_node["lon"])) / 2


def node_distance_from_center(node: dict[str, Any], center: dict[str, Any]) -> float:
    return haversine_meter(float(center["lat"]), float(center["lon"]), float(node["lat"]), float(node["lon"]))


def build_source_candidates(
    ways: list[dict[str, Any]],
    nodes: list[dict[str, Any]],
    center: dict[str, Any],
    radius_meter: float,
    boundary_ratio: float,
) -> dict[str, Any]:
    """固定ルールで車両発生候補をカテゴリ分けする。"""
    nodes_by_id = {node["id"]: node for node in nodes}
    categories: dict[str, list[dict[str, Any]]] = {
        "boundary_major": [],
        "boundary_minor": [],
        "internal_major": [],
        "internal_minor": [],
    }
    boundary_threshold = radius_meter * boundary_ratio

    for way in ways:
        from_node = nodes_by_id.get(way["from_node_id"])
        to_node = nodes_by_id.get(way["to_node_id"])
        if not from_node or not to_node:
            continue
        from_distance = node_distance_from_center(from_node, center)
        to_distance = node_distance_from_center(to_node, center)
        center_distance = (from_distance + to_distance) / 2
        is_boundary = max(from_distance, to_distance, center_distance) >= boundary_threshold
        inward_score = 1.4 if from_distance > to_distance else 0.8
        major = is_major_road(way)
        base_weight = road_priority_score(way)

        if is_boundary and major:
            category = "boundary_major"
            weight = base_weight * inward_score
        elif is_boundary:
            category = "boundary_minor"
            # minor は密度一様に近づけるため、道路属性の影響を弱める。
            weight = 1.0 * inward_score
        elif major:
            category = "internal_major"
            weight = base_weight
        else:
            category = "internal_minor"
            weight = 1.0

        categories[category].append(
            {
                "way_id": way["id"],
                "weight": max(0.05, weight),
                "road_type": way.get("road_type"),
                "lane_count": way.get("lane_count"),
                "speed_limit_kmh": way.get("speed_limit_kmh"),
                "from_distance_meter": round(from_distance, 2),
                "to_distance_meter": round(to_distance, 2),
            }
        )

    fallback = [{"way_id": way["id"], "weight": 1.0} for way in ways[: min(20, len(ways))]]
    for category, items in categories.items():
        if not items:
            categories[category] = fallback

    return {
        "category_ratios": {
            "boundary_major": 0.40,
            "boundary_minor": 0.10,
            "internal_major": 0.35,
            "internal_minor": 0.15,
        },
        "categories": categories,
        "note": "発生源カテゴリと重みは固定ルールによる近似であり、交通需要の正確な推定ではない。",
    }


def select_region(
    scenario: dict[str, Any],
    center: dict[str, Any],
    start_min: int,
    end_min: int,
    radius_meter: float,
    max_observations: int,
    max_ways: int | None,
    road_filter: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    nodes = scenario["graph"]["nodes"]
    ways = scenario["graph"]["ways"]
    observations = scenario["observation_points"]
    nodes_by_id = {node["id"]: node for node in nodes}

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

    candidate_ways = []
    for way in ways:
        lat, lon = way_center(way, nodes_by_id)
        distance = haversine_meter(center_lat, center_lon, lat, lon)
        if distance <= radius_meter or way["id"] in selected_way_ids:
            item = compact_way(way)
            item["_distance_meter"] = distance
            item["_is_observation_way"] = way["id"] in selected_way_ids
            candidate_ways.append(item)

    candidate_ways.sort(key=lambda item: (item["id"] not in selected_way_ids, item["_distance_meter"]))
    selected_ways = [
        way for way in candidate_ways
        if keep_way_by_filter(way, road_filter) or way.get("_is_observation_way")
    ]
    if max_ways is not None:
        selected_ways = selected_ways[:max_ways]
    selected_node_ids = {way["from_node_id"] for way in selected_ways} | {way["to_node_id"] for way in selected_ways}
    selected_nodes = [node for node in nodes if node["id"] in selected_node_ids]

    for way in selected_ways:
        way.pop("_distance_meter", None)
        way.pop("_is_observation_way", None)
    for observation in selected_observations:
        observation.pop("_distance_meter", None)
        observation.pop("_window_volume", None)

    return selected_nodes, selected_ways, selected_observations


def build_calibration(
    ways: list[dict[str, Any]],
    nodes: list[dict[str, Any]],
    observations: list[dict[str, Any]],
    center: dict[str, Any],
    start_min: int,
    end_min: int,
    generation_multiplier: float,
    radius_meter: float,
    boundary_ratio: float,
) -> dict[str, Any]:
    incoming_count: dict[str, int] = defaultdict(int)
    outgoing_count: dict[str, int] = defaultdict(int)
    for way in ways:
        incoming_count[way["to_node_id"]] += 1
        outgoing_count[way["from_node_id"]] += 1

    observation_by_way: dict[str, float] = {}
    for observation in observations:
        volume = observed_volume_in_window(observation, start_min, end_min)
        observation_by_way[observation["matched_way_id"]] = volume / max(1, (end_min - start_min) / 5)

    source_way_ids = [
        way["id"]
        for way in ways
        if incoming_count[way["from_node_id"]] == 0 and outgoing_count[way["from_node_id"]] > 0
    ]
    if not source_way_ids:
        source_way_ids = [way["id"] for way in ways[: min(20, len(ways))]]
    source_way_ids = source_way_ids[:30]

    way_score = {}
    for way in ways:
        base = 1.0
        observed_average = observation_by_way.get(way["id"])
        if observed_average is not None:
            base += math.log1p(observed_average)
        base += 0.15 * max(1, int(way.get("lane_count") or 1))
        way_score[way["id"]] = base

    source_weights = {way_id: way_score.get(way_id, 1.0) for way_id in source_way_ids}
    source_total = sum(source_weights.values()) or 1.0
    source_weights = {way_id: value / source_total for way_id, value in source_weights.items()}

    observed_total_by_bin: dict[int, int] = {}
    for time_min in range(start_min, end_min, 5):
        observed_total_by_bin[time_min] = 0
    for observation in observations:
        for time_min, count in observed_by_bin(observation, start_min, end_min).items():
            observed_total_by_bin[time_min] = observed_total_by_bin.get(time_min, 0) + count

    demand_profile = []
    for time_min in range(start_min, end_min, 5):
        observed_total = observed_total_by_bin.get(time_min, 0)
        demand_profile.append(
            {
                "time_min": time_min,
                "observed_total_5min": observed_total,
                "target_active_cars": max(1, round(observed_total * generation_multiplier)),
                "legacy_spawn_count_5min": max(1, round(observed_total * generation_multiplier)),
            }
        )

    return {
        "generation_multiplier": generation_multiplier,
        "source_way_ids": source_way_ids,
        "source_weights": source_weights,
        "source_candidates": build_source_candidates(ways, nodes, center, radius_meter, boundary_ratio),
        "way_score": way_score,
        "demand_profile": demand_profile,
        "note": "観測値は車両の直接生成命令ではなく、アクティブ車両数目標と固定発生源重みに変換して使う。",
    }


def build_observation_records(
    observations: list[dict[str, Any]],
    location_lookup: dict[tuple[str, str], dict[str, str]],
    start_min: int,
    end_min: int,
) -> list[dict[str, Any]]:
    records = []
    for observation in observations:
        location = location_lookup.get((observation.get("source_code", ""), observation.get("point_number", "")), {})
        records.append(
            {
                "id": observation["id"],
                "source_code": observation.get("source_code"),
                "point_number": observation.get("point_number"),
                "point_name": observation.get("point_name"),
                "lat": observation["lat"],
                "lon": observation["lon"],
                "matched_way_id": observation["matched_way_id"],
                "matched_position_ratio": observation.get("matched_position_ratio", 0.5),
                "location_link_number": location.get("交通管理リンク番号"),
                "observed_volume_5min": observed_by_bin(observation, start_min, end_min),
            }
        )
    return records


def main() -> None:
    args = parse_args()
    start_min = args.start_min
    end_min = args.start_min + args.duration_min

    scenario = load_json(args.scenario)
    # 再利用交通量データは、地点数などの出典情報を記録するために読む。
    traffic = load_json(args.traffic)
    location_lookup = load_location_lookup(args.locations)

    center = choose_center_observation(scenario["observation_points"], args.center_observation_id, start_min, end_min)
    effective_radius_meter = args.radius_meter
    effective_max_observations = args.max_observations
    if args.target_observation_count is not None:
        effective_radius_meter = decide_radius_by_observation_count(
            observations=scenario["observation_points"],
            center=center,
            target_observation_count=args.target_observation_count,
            radius_padding_meter=args.radius_padding_meter,
        )
        effective_max_observations = args.target_observation_count
    nodes, ways, observations = select_region(
        scenario=scenario,
        center=center,
        start_min=start_min,
        end_min=end_min,
        radius_meter=effective_radius_meter,
        max_observations=effective_max_observations,
        max_ways=args.max_ways,
        road_filter=args.road_filter,
    )
    calibration = build_calibration(
        ways=ways,
        nodes=nodes,
        observations=observations,
        center=center,
        start_min=start_min,
        end_min=end_min,
        generation_multiplier=args.generation_multiplier,
        radius_meter=effective_radius_meter,
        boundary_ratio=args.boundary_ratio,
    )
    observation_records = build_observation_records(observations, location_lookup, start_min, end_min)

    output = {
        "schema_version": "0.1",
        "meta": {
            "project": "forward_traffic_ml",
            "source_scenario": str(args.scenario),
            "source_traffic": str(args.traffic),
            "source_locations": str(args.locations),
            "source_traffic_summary": traffic.get("meta", {}).get("summary", {}),
            "center_observation_id": center["id"],
            "center_observation_name": center.get("point_name"),
            "start_min": start_min,
            "end_min": end_min,
            "duration_min": args.duration_min,
            "radius_meter": effective_radius_meter,
            "requested_radius_meter": args.radius_meter,
            "target_observation_count": args.target_observation_count,
            "radius_padding_meter": args.radius_padding_meter,
            "road_filter": args.road_filter,
            "note": "小領域・短時間の順方向シミュレーション検証用データ。",
        },
        "graph": {
            "nodes": nodes,
            "ways": ways,
        },
        "observations": observation_records,
        "calibration": calibration,
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as file:
        json.dump(output, file, ensure_ascii=False, indent=2)

    print(f"出力: {args.output}")
    print(f"ノード数: {len(nodes)}")
    print(f"Way数: {len(ways)}")
    print(f"観測点数: {len(observation_records)}")
    print(f"半径m: {effective_radius_meter:.2f}")
    print(f"中心観測点: {center['id']} {center.get('point_name')}")


if __name__ == "__main__":
    main()
