#!/usr/bin/env python3
"""発生位置パターンを比較するための可視化 JSON を出力する。"""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ROAD_VARIANTS_PATH = PROJECT_ROOT / "viewer/data/road_variants.json"
DEFAULT_OUTPUT_PATH = PROJECT_ROOT / "viewer/data/source_variants.json"


SOURCE_PATTERNS = [
    (
        "source_pattern_1_balanced",
        "バランス型: 境界流入と内部発生を両方入れる",
        {
            "boundary_major": 0.40,
            "boundary_minor": 0.10,
            "internal_major": 0.35,
            "internal_minor": 0.15,
        },
    ),
    (
        "source_pattern_2_internal_major",
        "内部幹線重視: 都心部内側の幹線道路から多く発生",
        {
            "boundary_major": 0.35,
            "boundary_minor": 0.05,
            "internal_major": 0.55,
            "internal_minor": 0.05,
        },
    ),
    (
        "source_pattern_3_boundary_major",
        "境界幹線重視: 領域外から主要道路で流入",
        {
            "boundary_major": 0.60,
            "boundary_minor": 0.10,
            "internal_major": 0.25,
            "internal_minor": 0.05,
        },
    ),
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="発生位置パターンの可視化データを作成します。")
    parser.add_argument("--road-variants", type=Path, default=DEFAULT_ROAD_VARIANTS_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--road-pattern", default="pattern_2_major_plus")
    parser.add_argument("--target-active-cars", type=int, default=3000)
    parser.add_argument("--boundary-ratio", type=float, default=0.78)
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


def road_type(way: dict[str, Any]) -> str:
    return str(way.get("road_type") or "unknown")


def lane_count(way: dict[str, Any]) -> int:
    return int(way.get("lane_count") or 1)


def is_major_road(way: dict[str, Any]) -> bool:
    road = road_type(way)
    lanes = lane_count(way)
    if road in {"motorway", "trunk", "primary", "secondary"}:
        return True
    if lanes >= 3:
        return True
    return road == "tertiary" and lanes >= 2


def road_priority_score(way: dict[str, Any]) -> float:
    road = road_type(way)
    road_type_weight = {
        "motorway": 5.0,
        "trunk": 4.5,
        "primary": 4.0,
        "secondary": 3.0,
        "tertiary": 2.0,
        "unclassified": 1.2,
        "residential": 1.0,
    }.get(road, 1.0)
    lanes = max(1, lane_count(way))
    speed_limit = max(10.0, float(way.get("speed_limit_kmh") or 30.0))
    return road_type_weight * math.sqrt(lanes) * math.sqrt(speed_limit / 30.0)


def way_center(way: dict[str, Any]) -> dict[str, float]:
    points = way.get("shape_points") or []
    if not points:
        return {"lat": 0.0, "lon": 0.0}
    return {
        "lat": sum(float(point["lat"]) for point in points) / len(points),
        "lon": sum(float(point["lon"]) for point in points) / len(points),
    }


def classify_sources(ways: list[dict[str, Any]], center: dict[str, float], radius_meter: float, boundary_ratio: float) -> dict[str, list[dict[str, Any]]]:
    categories: dict[str, list[dict[str, Any]]] = {
        "boundary_major": [],
        "boundary_minor": [],
        "internal_major": [],
        "internal_minor": [],
    }
    boundary_threshold = radius_meter * boundary_ratio

    for way in ways:
        points = way.get("shape_points") or []
        if not points:
            continue
        first = points[0]
        last = points[-1]
        from_distance = haversine_meter(center["lat"], center["lon"], float(first["lat"]), float(first["lon"]))
        to_distance = haversine_meter(center["lat"], center["lon"], float(last["lat"]), float(last["lon"]))
        center_distance = (from_distance + to_distance) / 2
        is_boundary = max(from_distance, to_distance, center_distance) >= boundary_threshold
        inward_score = 1.4 if from_distance > to_distance else 0.8
        major = is_major_road(way)

        if is_boundary and major:
            category = "boundary_major"
            weight = road_priority_score(way) * inward_score
        elif is_boundary:
            category = "boundary_minor"
            weight = 1.0 * inward_score
        elif major:
            category = "internal_major"
            weight = road_priority_score(way)
        else:
            category = "internal_minor"
            weight = 1.0

        item = dict(way)
        item["center"] = way_center(way)
        item["source_category"] = category
        item["source_weight"] = max(0.05, weight)
        item["from_distance_meter"] = round(from_distance, 2)
        item["to_distance_meter"] = round(to_distance, 2)
        categories[category].append(item)
    return categories


def distribute_counts(categories: dict[str, list[dict[str, Any]]], ratios: dict[str, float], target_active_cars: int) -> dict[str, int]:
    counts_by_way: dict[str, int] = {}
    for category, ratio in ratios.items():
        items = categories.get(category, [])
        if not items:
            continue
        category_total = round(target_active_cars * ratio)
        total_weight = sum(float(item.get("source_weight", 1.0)) for item in items) or 1.0
        remaining = category_total
        for index, item in enumerate(items):
            if index == len(items) - 1:
                count = remaining
            else:
                count = round(category_total * float(item.get("source_weight", 1.0)) / total_weight)
                count = min(count, remaining)
            counts_by_way[item["id"]] = counts_by_way.get(item["id"], 0) + max(0, count)
            remaining -= max(0, count)
    return counts_by_way


def build_source_pattern(
    name: str,
    description: str,
    ratios: dict[str, float],
    categories: dict[str, list[dict[str, Any]]],
    target_active_cars: int,
) -> dict[str, Any]:
    counts_by_way = distribute_counts(categories, ratios, target_active_cars)
    sources = []
    category_counts = Counter()
    for category, items in categories.items():
        for item in items:
            spawn_count = counts_by_way.get(item["id"], 0)
            if spawn_count <= 0:
                continue
            category_counts[category] += spawn_count
            sources.append(
                {
                    "way_id": item["id"],
                    "source_category": category,
                    "spawn_count": spawn_count,
                    "source_weight": item["source_weight"],
                    "road_type": item.get("road_type"),
                    "lane_count": item.get("lane_count"),
                    "speed_limit_kmh": item.get("speed_limit_kmh"),
                    "shape_points": item.get("shape_points", []),
                    "center": item["center"],
                }
            )
    return {
        "name": name,
        "description": description,
        "ratios": ratios,
        "summary": {
            "target_active_cars": target_active_cars,
            "source_way_count": len(sources),
            "category_spawn_counts": dict(category_counts),
            "category_candidate_counts": {key: len(value) for key, value in categories.items()},
        },
        "sources": sources,
    }


def main() -> None:
    args = parse_args()
    road_data = load_json(args.road_variants)
    variant = next((item for item in road_data["variants"] if item["name"] == args.road_pattern), None)
    if not variant:
        raise ValueError(f"道路パターンが見つかりません: {args.road_pattern}")

    # road_variants は中心点の緯度経度を直接持たないため、観測点の重心を近似中心として使う。
    observations = road_data["observations"]
    center = {
        "lat": sum(float(item["lat"]) for item in observations) / len(observations),
        "lon": sum(float(item["lon"]) for item in observations) / len(observations),
    }
    categories = classify_sources(
        ways=variant["ways"],
        center=center,
        radius_meter=float(road_data["meta"]["radius_meter"]),
        boundary_ratio=args.boundary_ratio,
    )
    source_patterns = [
        build_source_pattern(name, description, ratios, categories, args.target_active_cars)
        for name, description, ratios in SOURCE_PATTERNS
    ]
    output = {
        "schema_version": "0.1",
        "meta": {
            "road_pattern": args.road_pattern,
            "target_active_cars": args.target_active_cars,
            "boundary_ratio": args.boundary_ratio,
            "center": center,
            "note": "発生位置は固定ルールによる比較用の仮配置。シミュレーション結果ではない。",
        },
        "roads": variant["ways"],
        "observations": observations,
        "source_patterns": source_patterns,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as file:
        json.dump(output, file, ensure_ascii=False)

    print(f"出力: {args.output}")
    print(f"道路パターン: {args.road_pattern}")
    for pattern in source_patterns:
        print(pattern["name"], pattern["summary"])


if __name__ == "__main__":
    main()
