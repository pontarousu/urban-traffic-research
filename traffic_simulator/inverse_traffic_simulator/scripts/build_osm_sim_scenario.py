#!/usr/bin/env python3
"""OSM道路網と実観測データを、シミュレーション用JSONへ統合する。"""

from __future__ import annotations

import argparse
import json
import math
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


ALLOWED_HIGHWAYS = {
    "motorway",
    "trunk",
    "primary",
    "secondary",
    "tertiary",
    "unclassified",
    "residential",
    "service",
    "living_street",
}

LARGE_ROAD_TYPES = {"motorway", "trunk", "primary", "secondary"}
VIEW_WIDTH = 1000
VIEW_HEIGHT = 1000
VIEW_PADDING = 40


def parse_args() -> argparse.Namespace:
    """コマンドライン引数を読む。"""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--osm",
        default="../data/tokyo_station_raw.osm",
        help="入力OSM XMLファイル",
    )
    parser.add_argument(
        "--realdata",
        default="../data/realdata_all.json",
        help="実観測データJSON",
    )
    parser.add_argument(
        "--output",
        default="../data/tokyo_station_realdata_osm.json",
        help="出力シナリオJSON",
    )
    parser.add_argument(
        "--max-match-distance-meter",
        type=float,
        default=80.0,
        help="観測点をWayへ対応付ける最大距離[m]",
    )
    parser.add_argument(
        "--spatial-grid-cell-meter",
        type=float,
        default=100.0,
        help="観測点マッチング用グリッド索引のセル幅[m]",
    )
    parser.add_argument(
        "--start-min",
        type=float,
        default=None,
        help="使用する最初の観測時刻[分]。未指定なら全時間帯を使う",
    )
    parser.add_argument(
        "--duration-min",
        type=float,
        default=None,
        help="使用する観測時間幅[分]。--start-min と併用する",
    )
    parser.add_argument(
        "--max-observation-points",
        type=int,
        default=None,
        help="交通量合計が大きい順に使う観測点数。未指定なら全マッチ点を使う",
    )
    return parser.parse_args()


def main() -> None:
    """変換を実行する。"""

    args = parse_args()
    osm_nodes, osm_ways = load_osm(Path(args.osm))
    used_node_ids = {node_ref for osm_way in osm_ways for node_ref in osm_way["node_refs"]}
    used_osm_nodes = {
        node_id: node
        for node_id, node in osm_nodes.items()
        if node_id in used_node_ids
    }
    bounds = compute_bounds(list(used_osm_nodes.values()))
    projected_nodes = project_nodes(used_osm_nodes, bounds)
    graph_nodes = build_graph_nodes(used_osm_nodes, projected_nodes)
    graph_ways = build_directed_segment_ways(osm_ways, projected_nodes)
    attach_node_connections_and_turns(graph_nodes, graph_ways)

    realdata = json.loads(Path(args.realdata).read_text(encoding="utf-8"))
    observation_points, matching_summary = match_observation_points(
        realdata["observation_points"],
        graph_ways,
        bounds,
        args.max_match_distance_meter,
        args.spatial_grid_cell_meter,
        args.start_min,
        args.duration_min,
        args.max_observation_points,
    )

    start_time_min = infer_start_time_min(observation_points)
    scenario = {
        "schema_version": "1.0",
        "meta": {
            "scenario_id": "tokyo_station_realdata_osm",
            "scenario_name": "Tokyo Station Real Traffic Volume on OSM",
            "start_time_min": start_time_min,
            "source_osm": str(args.osm),
            "source_realdata": str(args.realdata),
            "note": (
                "OSM道路網に実観測点を最近傍マッチングした初期統合データ。"
                "観測方向は元データ変換時点で未保持のため、最近傍の単方向Wayを仮採用している。"
            ),
            "view_box": {
                "x_min": 0,
                "y_min": 0,
                "x_max": VIEW_WIDTH,
                "y_max": VIEW_HEIGHT,
            },
            "osm_bounds": bounds,
            "matching_summary": matching_summary,
            "summary": {
                "node_count": len(graph_nodes),
                "way_count": len(graph_ways),
                "observation_point_count": len(observation_points),
                "request_record_count": sum(
                    len(observation_point["traffic_volume"])
                    for observation_point in observation_points
                ),
                "total_target_count": sum(
                    sum(record["volume_5min"] for record in observation_point["traffic_volume"])
                    for observation_point in observation_points
                ),
            },
        },
        "graph": {
            "nodes": graph_nodes,
            "ways": graph_ways,
        },
        "observation_points": observation_points,
        "simulation_config": {
            "random_seed": 42,
            "time_step_sec": 1,
            "request_horizon_min": 20,
            "request_window_min": 5,
            "u_turn_allowed": False,
            "score_model": {
                "type": "discounted_sum",
                "travel_decay_a": 0.12,
                "slack_decay_b": 0.08,
            },
            "logging": {
                "enabled": True,
            },
        },
    }

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(scenario, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"wrote {output_path}")
    print(json.dumps(scenario["meta"]["summary"], ensure_ascii=False, indent=2))
    print(json.dumps(matching_summary, ensure_ascii=False, indent=2))


def load_osm(path: Path) -> tuple[dict[str, dict[str, float]], list[dict[str, Any]]]:
    """OSM XMLからnodeと車道wayを読む。"""

    root = ET.parse(path).getroot()
    nodes: dict[str, dict[str, float]] = {}

    for node in root.findall("node"):
        nodes[node.attrib["id"]] = {
            "id": node.attrib["id"],
            "lat": float(node.attrib["lat"]),
            "lon": float(node.attrib["lon"]),
        }

    ways: list[dict[str, Any]] = []
    for way in root.findall("way"):
        tags = {tag.attrib["k"]: tag.attrib["v"] for tag in way.findall("tag")}
        highway = tags.get("highway")
        if highway not in ALLOWED_HIGHWAYS:
            continue
        if tags.get("access") == "no" or tags.get("area") == "yes":
            continue
        if tags.get("motor_vehicle") == "no" or tags.get("service") == "parking_aisle":
            continue

        node_refs = [nd.attrib["ref"] for nd in way.findall("nd")]
        node_refs = [node_ref for node_ref in node_refs if node_ref in nodes]
        if len(node_refs) < 2:
            continue

        ways.append(
            {
                "id": way.attrib["id"],
                "node_refs": node_refs,
                "tags": tags,
                "highway": highway,
                "oneway": parse_oneway(tags),
                "speed_limit_kmh": parse_speed_limit(tags.get("maxspeed"), highway),
            }
        )

    return nodes, ways


def build_graph_nodes(
    osm_nodes: dict[str, dict[str, float]],
    projected_nodes: dict[str, dict[str, float]],
) -> list[dict[str, Any]]:
    """シミュレーション用Nodeを作る。"""

    return [
        {
            "id": build_node_id(node_id),
            "lat": node["lat"],
            "lon": node["lon"],
            "view_x": projected_nodes[node_id]["view_x"],
            "view_y": projected_nodes[node_id]["view_y"],
            "connected_way_ids": [],
            "turn_permissions": [],
        }
        for node_id, node in sorted(osm_nodes.items(), key=lambda item: item[0])
        if node_id in projected_nodes
    ]


def build_directed_segment_ways(
    osm_ways: list[dict[str, Any]],
    projected_nodes: dict[str, dict[str, float]],
) -> list[dict[str, Any]]:
    """OSM wayを隣接node間の単方向Wayへ分割する。"""

    graph_ways: list[dict[str, Any]] = []

    for osm_way in osm_ways:
        node_refs = osm_way["node_refs"]
        direction = osm_way["oneway"]
        forward_lanes, backward_lanes = estimate_directional_lanes(osm_way["tags"], osm_way["highway"], direction)

        for segment_index, (from_ref, to_ref) in enumerate(zip(node_refs, node_refs[1:])):
            if from_ref not in projected_nodes or to_ref not in projected_nodes:
                continue

            if direction in {"forward", "both"}:
                graph_ways.append(
                    build_segment_way(
                        osm_way,
                        from_ref,
                        to_ref,
                        segment_index,
                        "fwd",
                        forward_lanes,
                        projected_nodes,
                    )
                )

            if direction in {"reverse", "both"}:
                graph_ways.append(
                    build_segment_way(
                        osm_way,
                        to_ref,
                        from_ref,
                        segment_index,
                        "rev",
                        backward_lanes,
                        projected_nodes,
                    )
                )

    return graph_ways


def build_segment_way(
    osm_way: dict[str, Any],
    from_ref: str,
    to_ref: str,
    segment_index: int,
    direction_suffix: str,
    lane_count: int,
    projected_nodes: dict[str, dict[str, float]],
) -> dict[str, Any]:
    """単方向の道路セグメントを作る。"""

    from_point = projected_nodes[from_ref]
    to_point = projected_nodes[to_ref]
    length_meter = haversine_meter(from_point["lat"], from_point["lon"], to_point["lat"], to_point["lon"])
    safe_lane_count = max(1, lane_count)

    return {
        "id": f"way_{osm_way['id']}_{segment_index}_{direction_suffix}",
        "osm_way_id": osm_way["id"],
        "from_node_id": build_node_id(from_ref),
        "to_node_id": build_node_id(to_ref),
        "shape_points": [
            {
                "lat": from_point["lat"],
                "lon": from_point["lon"],
                "view_x": from_point["view_x"],
                "view_y": from_point["view_y"],
            },
            {
                "lat": to_point["lat"],
                "lon": to_point["lon"],
                "view_x": to_point["view_x"],
                "view_y": to_point["view_y"],
            },
        ],
        "road_type": osm_way["highway"],
        "lane_count": safe_lane_count,
        "length_meter": length_meter,
        "speed_limit_kmh": osm_way["speed_limit_kmh"],
        "storage_capacity_cars": max(
            safe_lane_count,
            math.floor(length_meter / 4) * safe_lane_count,
        ),
    }


def attach_node_connections_and_turns(nodes: list[dict[str, Any]], ways: list[dict[str, Any]]) -> None:
    """Nodeへ接続Wayと右左折許可を付与する。"""

    nodes_by_id = {node["id"]: node for node in nodes}
    incoming_by_node_id: dict[str, list[dict[str, Any]]] = {}
    outgoing_by_node_id: dict[str, list[dict[str, Any]]] = {}

    for way in ways:
        for node_id in (way["from_node_id"], way["to_node_id"]):
            if node_id in nodes_by_id:
                nodes_by_id[node_id]["connected_way_ids"].append(way["id"])

        incoming_by_node_id.setdefault(way["to_node_id"], []).append(way)
        outgoing_by_node_id.setdefault(way["from_node_id"], []).append(way)

    for node in nodes:
        node["connected_way_ids"] = sorted(set(node["connected_way_ids"]))
        turn_permissions = []
        for incoming_way in incoming_by_node_id.get(node["id"], []):
            for outgoing_way in outgoing_by_node_id.get(node["id"], []):
                is_u_turn = incoming_way["from_node_id"] == outgoing_way["to_node_id"]
                turn_permissions.append(
                    {
                        "from_way_id": incoming_way["id"],
                        "to_way_id": outgoing_way["id"],
                        "allowed": not is_u_turn,
                    }
                )
        node["turn_permissions"] = turn_permissions


def match_observation_points(
    raw_observation_points: list[dict[str, Any]],
    graph_ways: list[dict[str, Any]],
    bounds: dict[str, float],
    max_distance_meter: float,
    spatial_grid_cell_meter: float,
    start_min: float | None,
    duration_min: float | None,
    max_observation_points: int | None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """観測点を最近傍Wayへ対応付ける。"""

    margin_degree = max_distance_meter / 111_000
    spatial_index = build_spatial_index(
        graph_ways,
        bounds,
        max_distance_meter,
        spatial_grid_cell_meter,
    )
    candidates = [
        observation_point
        for observation_point in raw_observation_points
        if is_in_bounds(observation_point, bounds, margin_degree)
    ]
    matched_candidates = []
    unmatched_examples = []
    candidate_way_counts = []

    for observation_point in candidates:
        traffic_volume = filter_traffic_volume(
            observation_point["traffic_volume"],
            start_min,
            duration_min,
        )
        if not traffic_volume:
            continue

        nearby_ways = query_nearby_ways(observation_point, spatial_index)
        candidate_way_counts.append(len(nearby_ways))
        match = find_nearest_way_match(observation_point, nearby_ways)
        if match is None or match["distance_meter"] > max_distance_meter:
            if len(unmatched_examples) < 10:
                unmatched_examples.append(
                    {
                        "id": observation_point["id"],
                        "point_number": observation_point.get("point_number"),
                        "point_name": observation_point.get("point_name"),
                        "nearest_distance_meter": None if match is None else round(match["distance_meter"], 2),
                    }
                )
            continue

        matched_observation = {
            "id": observation_point["id"],
            "source_code": observation_point.get("source_code"),
            "point_number": observation_point.get("point_number"),
            "point_name": observation_point.get("point_name"),
            "lat": observation_point["lat"],
            "lon": observation_point["lon"],
            "view_x": match["view_x"],
            "view_y": match["view_y"],
            "matched_way_id": match["way_id"],
            "matched_position_ratio": clamp(match["position_ratio"], 0.001, 0.999),
            "match_position_ratio_raw": match["position_ratio"],
            "match_distance_meter": match["distance_meter"],
            "traffic_volume": traffic_volume,
        }
        matched_candidates.append(
            {
                "observation_point": matched_observation,
                "total_target_count": sum(record["volume_5min"] for record in traffic_volume),
            }
        )

    matched_candidates.sort(
        key=lambda candidate: (
            -candidate["total_target_count"],
            candidate["observation_point"]["id"],
        )
    )
    if max_observation_points is not None:
        selected_matched_candidates = matched_candidates[:max_observation_points]
    else:
        selected_matched_candidates = matched_candidates

    observation_points = [
        candidate["observation_point"]
        for candidate in sorted(selected_matched_candidates, key=lambda candidate: candidate["observation_point"]["id"])
    ]
    distances = [observation_point["match_distance_meter"] for observation_point in observation_points]
    out_of_range_count = len(candidates) - len(matched_candidates)
    matching_summary = {
        "candidate_observation_count": len(candidates),
        "within_distance_matched_count": len(matched_candidates),
        "matched_observation_count": len(observation_points),
        "not_selected_matched_count": max(0, len(matched_candidates) - len(observation_points)),
        "unmatched_candidate_count": max(0, out_of_range_count),
        "max_match_distance_meter": max_distance_meter,
        "selected_max_observation_points": max_observation_points,
        "matched_distance_meter": {
            "min": round(min(distances), 2) if distances else None,
            "max": round(max(distances), 2) if distances else None,
            "avg": round(sum(distances) / len(distances), 2) if distances else None,
        },
        "spatial_index": {
            "type": "grid",
            "cell_meter": spatial_grid_cell_meter,
            "cell_count": spatial_index["cell_count"],
            "indexed_way_count": spatial_index["indexed_way_count"],
            "way_reference_count": spatial_index["way_reference_count"],
            "candidate_way_count": {
                "min": min(candidate_way_counts) if candidate_way_counts else None,
                "max": max(candidate_way_counts) if candidate_way_counts else None,
                "avg": round(sum(candidate_way_counts) / len(candidate_way_counts), 2) if candidate_way_counts else None,
            },
        },
        "unmatched_examples": unmatched_examples,
        "direction_assumption": "観測方向は未保持のため、最近傍の単方向Wayを仮採用する。",
    }

    return observation_points, matching_summary


def build_spatial_index(
    graph_ways: list[dict[str, Any]],
    bounds: dict[str, float],
    max_distance_meter: float,
    cell_meter: float,
) -> dict[str, Any]:
    """Way候補を絞るためのグリッド索引を作る。

    各Way線分のbboxを最大マッチ距離ぶん膨らませてセルへ登録する。
    これにより、観測点側は自分のセルを見るだけで候補Wayを取得できる。
    """

    safe_cell_meter = max(1.0, cell_meter)
    origin_lat = (bounds["minLat"] + bounds["maxLat"]) / 2
    grid: dict[tuple[int, int], list[dict[str, Any]]] = {}
    way_reference_count = 0

    for way in graph_ways:
        start = way["shape_points"][0]
        end = way["shape_points"][-1]
        start_x, start_y = lon_lat_to_local_meter(start["lon"], start["lat"], origin_lat)
        end_x, end_y = lon_lat_to_local_meter(end["lon"], end["lat"], origin_lat)
        min_x = min(start_x, end_x) - max_distance_meter
        max_x = max(start_x, end_x) + max_distance_meter
        min_y = min(start_y, end_y) - max_distance_meter
        max_y = max(start_y, end_y) + max_distance_meter

        min_cell_x, min_cell_y = grid_cell(min_x, min_y, safe_cell_meter)
        max_cell_x, max_cell_y = grid_cell(max_x, max_y, safe_cell_meter)

        for cell_x in range(min_cell_x, max_cell_x + 1):
            for cell_y in range(min_cell_y, max_cell_y + 1):
                grid.setdefault((cell_x, cell_y), []).append(way)
                way_reference_count += 1

    return {
        "grid": grid,
        "origin_lat": origin_lat,
        "cell_meter": safe_cell_meter,
        "cell_count": len(grid),
        "indexed_way_count": len(graph_ways),
        "way_reference_count": way_reference_count,
    }


def query_nearby_ways(observation_point: dict[str, Any], spatial_index: dict[str, Any]) -> list[dict[str, Any]]:
    """観測点の近傍候補Wayをグリッド索引から返す。"""

    point_x, point_y = lon_lat_to_local_meter(
        observation_point["lon"],
        observation_point["lat"],
        spatial_index["origin_lat"],
    )
    cell_key = grid_cell(point_x, point_y, spatial_index["cell_meter"])
    ways = spatial_index["grid"].get(cell_key, [])
    unique_ways = {}

    for way in ways:
        unique_ways[way["id"]] = way

    return list(unique_ways.values())


def find_nearest_way_match(observation_point: dict[str, Any], graph_ways: list[dict[str, Any]]) -> dict[str, Any] | None:
    """観測点に最も近いWay射影を返す。"""

    best_match: dict[str, Any] | None = None
    origin_lat = observation_point["lat"]
    origin_lon = observation_point["lon"]

    for way in graph_ways:
        start = way["shape_points"][0]
        end = way["shape_points"][-1]
        projection = project_point_to_segment_meter(
            origin_lat,
            origin_lon,
            start["lat"],
            start["lon"],
            end["lat"],
            end["lon"],
        )

        if best_match is None or projection["distance_meter"] < best_match["distance_meter"]:
            view_x = start["view_x"] + (end["view_x"] - start["view_x"]) * projection["position_ratio"]
            view_y = start["view_y"] + (end["view_y"] - start["view_y"]) * projection["position_ratio"]
            best_match = {
                "way_id": way["id"],
                "position_ratio": projection["position_ratio"],
                "distance_meter": projection["distance_meter"],
                "view_x": view_x,
                "view_y": view_y,
            }

    return best_match


def project_point_to_segment_meter(
    point_lat: float,
    point_lon: float,
    start_lat: float,
    start_lon: float,
    end_lat: float,
    end_lon: float,
) -> dict[str, float]:
    """緯度経度上の点を、局所平面上で線分へ射影する。"""

    origin_lat = (point_lat + start_lat + end_lat) / 3
    px, py = lon_lat_to_local_meter(point_lon, point_lat, origin_lat)
    ax, ay = lon_lat_to_local_meter(start_lon, start_lat, origin_lat)
    bx, by = lon_lat_to_local_meter(end_lon, end_lat, origin_lat)
    vx = bx - ax
    vy = by - ay
    wx = px - ax
    wy = py - ay
    segment_length_sq = vx * vx + vy * vy

    if segment_length_sq == 0:
        ratio = 0.0
    else:
        ratio = clamp((wx * vx + wy * vy) / segment_length_sq, 0.0, 1.0)

    closest_x = ax + vx * ratio
    closest_y = ay + vy * ratio
    distance_meter = math.hypot(px - closest_x, py - closest_y)

    return {
        "position_ratio": ratio,
        "distance_meter": distance_meter,
    }


def filter_traffic_volume(
    traffic_volume: list[dict[str, Any]],
    start_min: float | None,
    duration_min: float | None,
) -> list[dict[str, Any]]:
    """指定時間帯の交通量だけを返す。"""

    if start_min is None:
        return [
            {
                "time_min": record["time_min"],
                "volume_5min": record["volume_5min"],
            }
            for record in traffic_volume
        ]

    end_min = start_min + (duration_min if duration_min is not None else 5)
    return [
        {
            "time_min": record["time_min"],
            "volume_5min": record["volume_5min"],
        }
        for record in traffic_volume
        if start_min <= record["time_min"] < end_min
    ]


def infer_start_time_min(observation_points: list[dict[str, Any]]) -> float:
    """シナリオ開始時刻を推定する。"""

    if not observation_points:
        return 0

    first_time_min = min(
        record["time_min"]
        for observation_point in observation_points
        for record in observation_point["traffic_volume"]
    )
    return max(0, first_time_min - 5)


def parse_oneway(tags: dict[str, str]) -> str:
    """OSMタグから方向種別を返す。"""

    oneway = tags.get("oneway")
    if oneway in {"yes", "1", "true"} or tags.get("junction") == "roundabout":
        return "forward"
    if oneway == "-1":
        return "reverse"
    return "both"


def estimate_directional_lanes(tags: dict[str, str], highway: str, direction: str) -> tuple[int, int]:
    """方向別lane数を推定する。"""

    lanes_forward = parse_lane_count(tags.get("lanes:forward"))
    lanes_backward = parse_lane_count(tags.get("lanes:backward"))
    total_lanes = parse_lane_count(tags.get("lanes"))

    if direction == "forward":
        return lanes_forward or total_lanes or default_lane_count(highway), 0
    if direction == "reverse":
        return 0, lanes_backward or total_lanes or default_lane_count(highway)

    if lanes_forward or lanes_backward:
        return lanes_forward or 1, lanes_backward or 1
    if total_lanes:
        return max(1, math.ceil(total_lanes / 2)), max(1, math.floor(total_lanes / 2))

    default_lanes = default_lane_count(highway)
    return default_lanes, default_lanes


def parse_lane_count(raw_value: str | None) -> int | None:
    """lane数タグを整数へ寄せる。"""

    if not raw_value:
        return None

    first_value = raw_value.split(";")[0].strip()
    digits = "".join(char for char in first_value if char.isdigit())
    if not digits:
        return None

    return max(1, int(digits))


def default_lane_count(highway: str) -> int:
    """OSMにlane数がない場合の推定lane数を返す。"""

    if highway in {"motorway", "trunk", "primary", "secondary"}:
        return 2
    return 1


def parse_speed_limit(raw_value: str | None, highway: str) -> int:
    """OSM maxspeed から速度制限を推定する。"""

    if raw_value:
        number_text = ""
        for char in raw_value:
            if char.isdigit() or char == ".":
                number_text += char
            elif number_text:
                break

        if number_text:
            speed = float(number_text)
            if "mph" in raw_value.lower():
                speed *= 1.609344
            return max(1, round(speed))

    if highway in LARGE_ROAD_TYPES:
        return 60
    return 30


def compute_bounds(points: list[dict[str, float]]) -> dict[str, float]:
    """緯度経度の範囲を返す。"""

    return {
        "minLat": min(point["lat"] for point in points),
        "maxLat": max(point["lat"] for point in points),
        "minLon": min(point["lon"] for point in points),
        "maxLon": max(point["lon"] for point in points),
    }


def project_nodes(
    osm_nodes: dict[str, dict[str, float]],
    bounds: dict[str, float],
) -> dict[str, dict[str, float]]:
    """緯度経度を描画座標へ変換する。"""

    lon_range = max(1e-9, bounds["maxLon"] - bounds["minLon"])
    lat_range = max(1e-9, bounds["maxLat"] - bounds["minLat"])
    projected_nodes = {}

    for node_id, node in osm_nodes.items():
        projected_nodes[node_id] = {
            "lat": node["lat"],
            "lon": node["lon"],
            "view_x": VIEW_PADDING + (node["lon"] - bounds["minLon"]) / lon_range * (VIEW_WIDTH - VIEW_PADDING * 2),
            "view_y": VIEW_HEIGHT - VIEW_PADDING - (node["lat"] - bounds["minLat"]) / lat_range * (VIEW_HEIGHT - VIEW_PADDING * 2),
        }

    return projected_nodes


def is_in_bounds(point: dict[str, Any], bounds: dict[str, float], margin_degree: float) -> bool:
    """点が範囲内にあるか返す。"""

    return (
        bounds["minLat"] - margin_degree <= point["lat"] <= bounds["maxLat"] + margin_degree
        and bounds["minLon"] - margin_degree <= point["lon"] <= bounds["maxLon"] + margin_degree
    )


def haversine_meter(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """2点間の球面距離をメートルで返す。"""

    radius_meter = 6_371_000
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return radius_meter * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def lon_lat_to_local_meter(lon: float, lat: float, origin_lat: float) -> tuple[float, float]:
    """緯度経度を局所平面メートル座標へ近似変換する。"""

    x = math.radians(lon) * 6_371_000 * math.cos(math.radians(origin_lat))
    y = math.radians(lat) * 6_371_000
    return x, y


def grid_cell(x_meter: float, y_meter: float, cell_meter: float) -> tuple[int, int]:
    """局所平面座標からグリッドセル番号を返す。"""

    return math.floor(x_meter / cell_meter), math.floor(y_meter / cell_meter)


def build_node_id(osm_node_id: str) -> str:
    """OSM node IDからシミュレーション用IDを作る。"""

    return f"node_{osm_node_id}"


def clamp(value: float, min_value: float, max_value: float) -> float:
    """値を指定範囲に丸める。"""

    return min(max_value, max(min_value, value))


if __name__ == "__main__":
    main()
