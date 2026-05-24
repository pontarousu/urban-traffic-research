#!/usr/bin/env python3
"""観測点の緯度経度と道路DB geometry のズレ確認用データを出力する。"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PROJECT_ROOT.parent
DEFAULT_SCENARIO_PATH = REPO_ROOT / "inverse_traffic_simulator/data/current/tokyo_core_small_realdata_osm_300obs_allday.json"
DEFAULT_SNAPSHOT_DIR = PROJECT_ROOT / "data/road_db_snapshots/road_db_prototype_tokyo_core_small_runtime_current"
DEFAULT_OUTPUT_PATH = PROJECT_ROOT / "viewer/data/observation_alignment.json"


def parse_args() -> argparse.Namespace:
    """コマンドライン引数を読む。"""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", type=Path, default=DEFAULT_SCENARIO_PATH)
    parser.add_argument("--snapshot-dir", type=Path, default=DEFAULT_SNAPSHOT_DIR)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--start-min", type=int, default=480)
    parser.add_argument("--duration-min", type=int, default=60)
    parser.add_argument("--nearest-count", type=int, default=5)
    parser.add_argument("--road-padding-meter", type=float, default=250.0)
    parser.add_argument("--candidate-radius-meter", type=float, default=120.0)
    return parser.parse_args()


def main() -> None:
    """可視化用 JSON を作る。"""

    args = parse_args()
    scenario = load_json(args.scenario)
    core = load_json(args.snapshot_dir / "network_core.json")
    geometry = load_json(args.snapshot_dir / "network_geometry.json")

    observations = convert_observations(
        scenario.get("observation_points", []),
        start_min=args.start_min,
        end_min=args.start_min + args.duration_min,
    )
    directed_edges = {
        edge["directed_edge_id"]: edge
        for edge in core["graph"]["directed_edges"]
    }
    topology_edges = {
        edge["topology_edge_id"]: edge
        for edge in load_reference_topology_edges(args.snapshot_dir)
    }

    road_bounds = bounds_for_observations(observations, args.road_padding_meter)
    road_lines = build_road_lines(
        geometry=geometry,
        topology_edges=topology_edges,
        road_bounds=road_bounds,
    )
    directed_geometries = geometry["directed_edge_geometries"]
    edge_index = build_edge_index(directed_edges, directed_geometries)
    edge_lookup = {
        edge["directed_edge_id"]: edge
        for edge in edge_index
    }
    observations_with_candidates = attach_nearest_candidates(
        observations=observations,
        edge_index=edge_index,
        nearest_count=args.nearest_count,
        candidate_radius_meter=args.candidate_radius_meter,
    )
    pair_diagnostics = build_near_pair_diagnostics(observations_with_candidates)
    apply_pair_constrained_matching(
        observations=observations_with_candidates,
        pairs=pair_diagnostics,
        edge_lookup=edge_lookup,
    )
    attach_pair_diagnostics(observations_with_candidates, pair_diagnostics)
    connector_lines = build_connector_lines(observations_with_candidates)

    output = {
        "schema_version": "observation_alignment.v1",
        "source": {
            "scenario": str(args.scenario),
            "snapshot_dir": str(args.snapshot_dir),
            "network_core": "network_core.json",
            "network_geometry": "network_geometry.json",
        },
        "config": {
            "start_min": args.start_min,
            "duration_min": args.duration_min,
            "nearest_count": args.nearest_count,
            "road_padding_meter": args.road_padding_meter,
            "candidate_radius_meter": args.candidate_radius_meter,
            "near_pair_threshold_meter": 25.0,
            "direction_conflict_angle_threshold_deg": 45.0,
            "opposite_direction_angle_threshold_deg": 135.0,
            "pair_constraint_max_candidate_distance_meter": 30.0,
        },
        "summary": summarize(observations_with_candidates, road_lines),
        "bounds": combined_bounds(road_lines, observations_with_candidates),
        "roads": road_lines,
        "observations": observations_with_candidates,
        "connector_lines": connector_lines,
        "near_pair_diagnostics": pair_diagnostics,
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as file:
        json.dump(output, file, ensure_ascii=False)
    print(f"出力: {args.output}")
    print(json.dumps(output["summary"], ensure_ascii=False, indent=2))


def load_json(path: Path) -> Any:
    """JSON ファイルを読む。"""

    with path.open(encoding="utf-8") as file:
        return json.load(file)


def load_reference_topology_edges(snapshot_dir: Path) -> list[dict[str, Any]]:
    """参照用 topology edge を読む。"""

    reference_path = snapshot_dir / "network_reference.json"
    if reference_path.exists():
        reference = load_json(reference_path)
        return reference["graph"]["topology_edges"]
    core = load_json(snapshot_dir / "network_core.json")
    return core["graph"].get("topology_edges", [])


def convert_observations(raw_observations: list[dict[str, Any]], start_min: int, end_min: int) -> list[dict[str, Any]]:
    """観測点を可視化用に変換する。"""

    observations: list[dict[str, Any]] = []
    for obs in raw_observations:
        volume_profile = build_volume_profile(obs.get("traffic_volume", []))
        total = 0
        for record in obs.get("traffic_volume", []):
            time_min = int(record["time_min"])
            if start_min <= time_min < end_min:
                total += int(record["volume_5min"])
        observations.append(
            {
                "id": obs["id"],
                "source_code": obs.get("source_code"),
                "point_number": obs.get("point_number"),
                "point_name": obs.get("point_name"),
                "lat": float(obs["lat"]),
                "lon": float(obs["lon"]),
                "old_matched_way_id": obs.get("matched_way_id"),
                "old_match_distance_meter": obs.get("match_distance_meter"),
                "observed_total": total,
                "volume_profile": volume_profile,
            }
        )
    return observations


def build_volume_profile(records: list[dict[str, Any]]) -> dict[str, Any]:
    """全日の時間別観測量から方向推定用のプロファイルを作る。"""

    bins = {
        "morning": {"start": 420, "end": 600, "volume": 0},
        "midday": {"start": 600, "end": 960, "volume": 0},
        "evening": {"start": 960, "end": 1140, "volume": 0},
        "night": {"start": 1140, "end": 1440, "volume": 0},
        "other": {"start": 0, "end": 420, "volume": 0},
    }
    hourly_volumes = [0 for _ in range(24)]
    total = 0
    nonzero_slots = 0
    for record in records:
        time_min = int(record["time_min"])
        volume = int(record["volume_5min"])
        total += volume
        hour = min(23, max(0, time_min // 60))
        hourly_volumes[hour] += volume
        if volume > 0:
            nonzero_slots += 1
        for item in bins.values():
            if item["start"] <= time_min < item["end"]:
                item["volume"] += volume
                break

    if total <= 0 or nonzero_slots < 12:
        profile_type = "low_volume_or_missing"
    else:
        morning_ratio = bins["morning"]["volume"] / total
        evening_ratio = bins["evening"]["volume"] / total
        direction_bias = morning_ratio - evening_ratio
        if direction_bias >= 0.15:
            profile_type = "morning_heavy"
        elif direction_bias <= -0.15:
            profile_type = "evening_heavy"
        else:
            profile_type = "flat"

    ratios = {
        name: round(item["volume"] / total, 4) if total else 0.0
        for name, item in bins.items()
    }
    max_hourly = max(hourly_volumes) if hourly_volumes else 0
    hourly_ratios = [
        round(value / max_hourly, 4) if max_hourly else 0.0
        for value in hourly_volumes
    ]
    return {
        "total_all_day": total,
        "nonzero_slots": nonzero_slots,
        "hourly_volumes": hourly_volumes,
        "hourly_ratios": hourly_ratios,
        "morning_volume": bins["morning"]["volume"],
        "midday_volume": bins["midday"]["volume"],
        "evening_volume": bins["evening"]["volume"],
        "night_volume": bins["night"]["volume"],
        "other_volume": bins["other"]["volume"],
        "morning_ratio": ratios["morning"],
        "midday_ratio": ratios["midday"],
        "evening_ratio": ratios["evening"],
        "night_ratio": ratios["night"],
        "direction_bias": round(ratios["morning"] - ratios["evening"], 4),
        "profile_type": profile_type,
    }


def bounds_for_observations(observations: list[dict[str, Any]], padding_meter: float) -> dict[str, float]:
    """観測点群の bbox に余白を付ける。"""

    min_lat = min(obs["lat"] for obs in observations)
    max_lat = max(obs["lat"] for obs in observations)
    min_lon = min(obs["lon"] for obs in observations)
    max_lon = max(obs["lon"] for obs in observations)
    center_lat = (min_lat + max_lat) / 2
    lat_padding = padding_meter / 111_320.0
    lon_padding = padding_meter / meters_per_lon_degree(center_lat)
    return {
        "min_lat": min_lat - lat_padding,
        "max_lat": max_lat + lat_padding,
        "min_lon": min_lon - lon_padding,
        "max_lon": max_lon + lon_padding,
    }


def build_road_lines(
    *,
    geometry: dict[str, Any],
    topology_edges: dict[str, dict[str, Any]],
    road_bounds: dict[str, float],
) -> list[dict[str, Any]]:
    """bbox 内にかかる topology edge を描画用に作る。"""

    roads: list[dict[str, Any]] = []
    for topology_edge_id, item in geometry["topology_edge_geometries"].items():
        shape_points = item.get("shape_points", [])
        if not shape_points or not line_intersects_bounds(shape_points, road_bounds):
            continue
        edge = topology_edges.get(topology_edge_id, {})
        roads.append(
            {
                "topology_edge_id": topology_edge_id,
                "road_type": edge.get("road_type"),
                "lane_count_total": edge.get("lane_count_total"),
                "speed_limit_kmh": edge.get("speed_limit_kmh"),
                "length_meter": edge.get("length_meter"),
                "shape_points": shape_points,
            }
        )
    return roads


def line_intersects_bounds(shape_points: list[dict[str, float]], bounds: dict[str, float]) -> bool:
    """線分の bbox が指定 bbox と交差するかを返す。"""

    min_lat = min(point["lat"] for point in shape_points)
    max_lat = max(point["lat"] for point in shape_points)
    min_lon = min(point["lon"] for point in shape_points)
    max_lon = max(point["lon"] for point in shape_points)
    return not (
        max_lat < bounds["min_lat"]
        or min_lat > bounds["max_lat"]
        or max_lon < bounds["min_lon"]
        or min_lon > bounds["max_lon"]
    )


def build_edge_index(
    directed_edges: dict[str, dict[str, Any]],
    directed_geometries: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """最近傍探索用の edge index を作る。"""

    index: list[dict[str, Any]] = []
    for edge_id, geometry in directed_geometries.items():
        shape_points = geometry.get("shape_points", [])
        if len(shape_points) < 2:
            continue
        edge = directed_edges.get(edge_id, {})
        from_point = shape_points[0]
        to_point = shape_points[-1]
        index.append(
            {
                "directed_edge_id": edge_id,
                "topology_edge_id": edge.get("topology_edge_id"),
                "road_type": edge.get("road_type"),
                "lane_count_total": edge.get("lane_count_total"),
                "speed_limit_kmh": edge.get("speed_limit_kmh"),
                "length_meter": edge.get("length_meter"),
                "from_node_id": edge.get("from_node_id"),
                "to_node_id": edge.get("to_node_id"),
                "from_point": from_point,
                "to_point": to_point,
                "bbox": line_bounds(shape_points),
                "shape_points": shape_points,
            }
        )
    return index


def attach_nearest_candidates(
    *,
    observations: list[dict[str, Any]],
    edge_index: list[dict[str, Any]],
    nearest_count: int,
    candidate_radius_meter: float,
) -> list[dict[str, Any]]:
    """各観測点に近傍 directed edge 候補を付ける。"""

    output: list[dict[str, Any]] = []
    for obs in observations:
        candidates = nearest_edges(
            lat=obs["lat"],
            lon=obs["lon"],
            edge_index=edge_index,
            nearest_count=nearest_count,
            candidate_radius_meter=candidate_radius_meter,
        )
        item = dict(obs)
        item["nearest_candidates"] = [without_shape_points(candidate) for candidate in candidates]
        item["nearest_distance_meter"] = candidates[0]["distance_meter"] if candidates else None
        item["alignment_status"] = classify_alignment(item["nearest_distance_meter"])
        item["usable_for_initial_matching"] = item["alignment_status"] == "near"
        item["provisional_link"] = build_provisional_link(candidates[0]) if candidates else None
        item["matched_link"] = build_provisional_link(candidates[0]) if candidates else None
        item["match_method"] = "nearest" if candidates else "no_candidate"
        item["match_confidence"] = initial_match_confidence(item["alignment_status"])
        item["warning_flags"] = initial_warning_flags(item)
        output.append(item)
    return output


def nearest_edges(
    *,
    lat: float,
    lon: float,
    edge_index: list[dict[str, Any]],
    nearest_count: int,
    candidate_radius_meter: float,
) -> list[dict[str, Any]]:
    """点から近い directed edge を返す。"""

    rough_candidates = [
        edge
        for edge in edge_index
        if bbox_distance_lower_bound_meter(lat, lon, edge["bbox"]) <= candidate_radius_meter
    ]
    if len(rough_candidates) < nearest_count:
        rough_candidates = edge_index

    scored: list[dict[str, Any]] = []
    for edge in rough_candidates:
        nearest = nearest_point_on_polyline(lat, lon, edge["shape_points"])
        scored.append(
            {
                "directed_edge_id": edge["directed_edge_id"],
                "topology_edge_id": edge.get("topology_edge_id"),
                "road_type": edge.get("road_type"),
                "lane_count_total": edge.get("lane_count_total"),
                "speed_limit_kmh": edge.get("speed_limit_kmh"),
                "length_meter": edge.get("length_meter"),
                "from_node_id": edge.get("from_node_id"),
                "to_node_id": edge.get("to_node_id"),
                "from_point": edge.get("from_point"),
                "to_point": edge.get("to_point"),
                "distance_meter": round(nearest["distance_meter"], 2),
                "nearest_point": {
                    "lat": nearest["lat"],
                    "lon": nearest["lon"],
                },
                "position_ratio": round(nearest["position_ratio"], 4),
                "shape_points": edge["shape_points"],
            }
        )

    scored.sort(key=lambda item: item["distance_meter"])
    return scored[:nearest_count]


def without_shape_points(candidate: dict[str, Any]) -> dict[str, Any]:
    """tooltip 用候補から重い形状点を外す。"""

    return {
        key: value
        for key, value in candidate.items()
        if key != "shape_points"
    }


def build_provisional_link(candidate: dict[str, Any]) -> dict[str, Any]:
    """最近傍 directed edge を暫定リンクとして返す。"""

    return {
        "directed_edge_id": candidate["directed_edge_id"],
        "topology_edge_id": candidate.get("topology_edge_id"),
        "road_type": candidate.get("road_type"),
        "lane_count_total": candidate.get("lane_count_total"),
        "speed_limit_kmh": candidate.get("speed_limit_kmh"),
        "length_meter": candidate.get("length_meter"),
        "from_node_id": candidate.get("from_node_id"),
        "to_node_id": candidate.get("to_node_id"),
        "from_point": candidate.get("from_point"),
        "to_point": candidate.get("to_point"),
        "distance_meter": candidate["distance_meter"],
        "nearest_point": candidate["nearest_point"],
        "position_ratio": candidate["position_ratio"],
        "bearing_deg": bearing_between_points(candidate.get("from_point"), candidate.get("to_point")),
        "shape_points": candidate["shape_points"],
    }


def initial_match_confidence(alignment_status: str) -> str:
    """最近傍距離だけを使った初期信頼度を返す。"""

    if alignment_status == "near":
        return "high"
    if alignment_status == "moderate":
        return "medium"
    return "low"


def initial_warning_flags(observation: dict[str, Any]) -> list[str]:
    """初期マッチング時点の警告フラグを返す。"""

    if observation.get("alignment_status") == "far":
        return ["far_from_edge"]
    if observation.get("alignment_status") == "moderate":
        return ["moderate_distance_from_edge"]
    if observation.get("alignment_status") == "unknown":
        return ["no_candidate"]
    return []


def build_near_pair_diagnostics(observations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """近接観測点ペアの方向診断を作る。"""

    usable_observations = [
        obs
        for obs in observations
        if obs.get("usable_for_initial_matching") and obs.get("provisional_link")
    ]
    pairs: list[dict[str, Any]] = []
    pair_index = 0
    for index, left in enumerate(usable_observations):
        for right in usable_observations[index + 1:]:
            distance_meter = haversine_meter(left["lat"], left["lon"], right["lat"], right["lon"])
            if distance_meter > 25.0:
                continue
            pair_index += 1
            left_link = left["provisional_link"]
            right_link = right["provisional_link"]
            left_bearing = left_link.get("bearing_deg")
            right_bearing = right_link.get("bearing_deg")
            diff = angle_diff_deg(left_bearing, right_bearing)
            volume_profile_relation = compare_volume_profiles(left["volume_profile"], right["volume_profile"])
            same_directed_edge = left_link["directed_edge_id"] == right_link["directed_edge_id"]
            same_topology_edge = left_link["topology_edge_id"] == right_link["topology_edge_id"]
            is_opposite = diff is not None and diff >= 135.0
            is_conflict = same_directed_edge or (diff is not None and diff <= 45.0)
            pairs.append(
                {
                    "pair_id": f"near_pair_{pair_index:04d}",
                    "left_observation_id": left["id"],
                    "right_observation_id": right["id"],
                    "left_point_number": left.get("point_number"),
                    "right_point_number": right.get("point_number"),
                    "left_point_name": left.get("point_name"),
                    "right_point_name": right.get("point_name"),
                    "distance_meter": round(distance_meter, 2),
                    "left_directed_edge_id": left_link["directed_edge_id"],
                    "right_directed_edge_id": right_link["directed_edge_id"],
                    "left_topology_edge_id": left_link["topology_edge_id"],
                    "right_topology_edge_id": right_link["topology_edge_id"],
                    "left_bearing_deg": round(left_bearing, 1) if left_bearing is not None else None,
                    "right_bearing_deg": round(right_bearing, 1) if right_bearing is not None else None,
                    "direction_diff_deg": round(diff, 1) if diff is not None else None,
                    "same_directed_edge": same_directed_edge,
                    "same_topology_edge": same_topology_edge,
                    "pair_status": "opposite_ok" if is_opposite else "direction_conflict" if is_conflict else "ambiguous",
                    "left_volume_profile": left["volume_profile"],
                    "right_volume_profile": right["volume_profile"],
                    "volume_profile_relation": volume_profile_relation,
                    "left_alternative_opposite_edges": opposite_direction_candidates(left, right_link),
                    "right_alternative_opposite_edges": opposite_direction_candidates(right, left_link),
                    "points": [
                        {"lat": left["lat"], "lon": left["lon"]},
                        {"lat": right["lat"], "lon": right["lon"]},
                    ],
                }
            )
    return pairs


def compare_volume_profiles(left: dict[str, Any], right: dict[str, Any]) -> str:
    """近接ペアの時間変化プロファイル関係を返す。"""

    left_type = left.get("profile_type")
    right_type = right.get("profile_type")
    if "low_volume_or_missing" in {left_type, right_type}:
        return "weak_profile"
    if "flat" in {left_type, right_type}:
        return "weak_profile"
    if {left_type, right_type} == {"morning_heavy", "evening_heavy"}:
        return "opposite_profile"
    if left_type == right_type and left_type in {"morning_heavy", "evening_heavy"}:
        return "same_profile"
    return "weak_profile"


def attach_pair_diagnostics(observations: list[dict[str, Any]], pairs: list[dict[str, Any]]) -> None:
    """観測点ごとに近接ペア診断を付ける。"""

    pairs_by_observation: dict[str, list[dict[str, Any]]] = {}
    for pair in pairs:
        pairs_by_observation.setdefault(pair["left_observation_id"], []).append(pair)
        pairs_by_observation.setdefault(pair["right_observation_id"], []).append(pair)
    for obs in observations:
        related_pairs = pairs_by_observation.get(obs["id"], [])
        obs["near_pair_ids"] = [pair["pair_id"] for pair in related_pairs]
        obs["has_direction_conflict_pair"] = any(pair["pair_status"] == "direction_conflict" for pair in related_pairs)


def opposite_direction_candidates(observation: dict[str, Any], counterpart_link: dict[str, Any]) -> list[dict[str, Any]]:
    """ペア相手と反対方向に近い候補 edge を返す。"""

    counterpart_bearing = counterpart_link.get("bearing_deg")
    candidates = []
    for candidate in observation.get("nearest_candidates", []):
        candidate_bearing = bearing_between_points(candidate.get("from_point"), candidate.get("to_point"))
        diff = angle_diff_deg(candidate_bearing, counterpart_bearing)
        if diff is None or diff < 135.0:
            continue
        candidates.append(
            {
                "directed_edge_id": candidate["directed_edge_id"],
                "topology_edge_id": candidate.get("topology_edge_id"),
                "road_type": candidate.get("road_type"),
                "distance_meter": candidate["distance_meter"],
                "bearing_deg": round(candidate_bearing, 1) if candidate_bearing is not None else None,
                "direction_diff_deg": round(diff, 1),
            }
        )
    return candidates[:3]


def apply_pair_constrained_matching(
    *,
    observations: list[dict[str, Any]],
    pairs: list[dict[str, Any]],
    edge_lookup: dict[str, dict[str, Any]],
) -> None:
    """近接 conflict ペアに対して反対方向候補を優先して採用する。"""

    observations_by_id = {
        obs["id"]: obs
        for obs in observations
    }
    pair_assigned_edges: dict[str, str] = {}
    for pair in pairs:
        if pair.get("pair_status") != "direction_conflict":
            pair["pair_resolution"] = {
                "status": "not_applicable",
                "reason": pair.get("pair_status"),
            }
            continue

        left = observations_by_id[pair["left_observation_id"]]
        right = observations_by_id[pair["right_observation_id"]]
        resolution = resolve_pair_constraint(left, right)
        pair["pair_resolution"] = resolution
        if resolution["status"] != "resolved":
            add_warning_flag(left, "pair_constraint_unresolved")
            add_warning_flag(right, "pair_constraint_unresolved")
            continue

        left_edge_id = resolution["left_selected_edge"]
        right_edge_id = resolution["right_selected_edge"]
        if has_incompatible_pair_assignment(pair_assigned_edges, left["id"], left_edge_id):
            resolution["status"] = "unresolved"
            resolution["reason"] = "multi_pair_conflict"
            add_warning_flag(left, "multi_pair_conflict")
            add_warning_flag(right, "pair_constraint_unresolved")
            continue
        if has_incompatible_pair_assignment(pair_assigned_edges, right["id"], right_edge_id):
            resolution["status"] = "unresolved"
            resolution["reason"] = "multi_pair_conflict"
            add_warning_flag(left, "pair_constraint_unresolved")
            add_warning_flag(right, "multi_pair_conflict")
            continue

        pair_assigned_edges[left["id"]] = left_edge_id
        pair_assigned_edges[right["id"]] = right_edge_id
        left_candidate = resolution["left_candidate"]
        right_candidate = resolution["right_candidate"]
        left["matched_link"] = build_matched_link(left_candidate, edge_lookup)
        right["matched_link"] = build_matched_link(right_candidate, edge_lookup)
        left["match_method"] = "pair_constrained"
        right["match_method"] = "pair_constrained"
        left["match_confidence"] = resolution["confidence"]
        right["match_confidence"] = resolution["confidence"]
        add_warning_flag(left, "direction_conflict_resolved")
        add_warning_flag(right, "direction_conflict_resolved")
        if pair.get("volume_profile_relation") == "opposite_profile":
            add_warning_flag(left, "volume_profile_supports_opposite")
            add_warning_flag(right, "volume_profile_supports_opposite")
        del resolution["left_candidate"]
        del resolution["right_candidate"]


def resolve_pair_constraint(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    """1つの conflict ペアに対して候補組み合わせを選ぶ。"""

    best: dict[str, Any] | None = None
    for left_candidate in left.get("nearest_candidates", [])[:5]:
        for right_candidate in right.get("nearest_candidates", [])[:5]:
            score_item = score_pair_candidate(left_candidate, right_candidate)
            if best is None or score_item["score"] < best["score"]:
                best = {
                    **score_item,
                    "left_candidate": left_candidate,
                    "right_candidate": right_candidate,
                }

    if best is None:
        return {
            "status": "unresolved",
            "method": "opposite_candidate_search",
            "reason": "no_candidate",
        }

    left_distance = best["left_candidate"]["distance_meter"]
    right_distance = best["right_candidate"]["distance_meter"]
    direction_diff = best["direction_diff_deg"]
    if best["same_directed_edge"]:
        reason = "same_directed_edge"
    elif direction_diff is None or direction_diff < 135.0:
        reason = "no_opposite_candidate"
    elif max(left_distance, right_distance) > 30.0:
        reason = "candidate_too_far"
    else:
        reason = None

    if reason:
        return {
            "status": "unresolved",
            "method": "opposite_candidate_search",
            "reason": reason,
            "left_selected_edge": best["left_candidate"]["directed_edge_id"],
            "right_selected_edge": best["right_candidate"]["directed_edge_id"],
            "direction_diff_deg": round(direction_diff, 1) if direction_diff is not None else None,
            "score": round(best["score"], 3),
        }

    confidence = "high" if best["same_topology_edge"] and max(left_distance, right_distance) <= 10.0 else "medium"
    return {
        "status": "resolved",
        "method": "opposite_candidate_search",
        "left_selected_edge": best["left_candidate"]["directed_edge_id"],
        "right_selected_edge": best["right_candidate"]["directed_edge_id"],
        "left_selected_distance_meter": left_distance,
        "right_selected_distance_meter": right_distance,
        "direction_diff_deg": round(direction_diff, 1) if direction_diff is not None else None,
        "same_topology_edge": best["same_topology_edge"],
        "score": round(best["score"], 3),
        "confidence": confidence,
        "left_candidate": best["left_candidate"],
        "right_candidate": best["right_candidate"],
    }


def score_pair_candidate(left_candidate: dict[str, Any], right_candidate: dict[str, Any]) -> dict[str, Any]:
    """候補ペアの局所スコアを返す。小さいほどよい。"""

    left_bearing = bearing_between_points(left_candidate.get("from_point"), left_candidate.get("to_point"))
    right_bearing = bearing_between_points(right_candidate.get("from_point"), right_candidate.get("to_point"))
    direction_diff = angle_diff_deg(left_bearing, right_bearing)
    same_directed_edge = left_candidate["directed_edge_id"] == right_candidate["directed_edge_id"]
    same_topology_edge = left_candidate.get("topology_edge_id") == right_candidate.get("topology_edge_id")
    direction_cost = abs(180.0 - direction_diff) * 0.2 if direction_diff is not None else 180.0
    same_directed_edge_penalty = 1000.0 if same_directed_edge else 0.0
    weak_direction_penalty = 100.0 if direction_diff is None or direction_diff < 90.0 else 0.0
    opposite_same_topology_bonus = -20.0 if same_topology_edge and direction_diff is not None and direction_diff >= 135.0 else 0.0
    score = (
        left_candidate["distance_meter"]
        + right_candidate["distance_meter"]
        + direction_cost
        + same_directed_edge_penalty
        + weak_direction_penalty
        + opposite_same_topology_bonus
    )
    return {
        "score": score,
        "direction_diff_deg": direction_diff,
        "same_directed_edge": same_directed_edge,
        "same_topology_edge": same_topology_edge,
    }


def build_matched_link(candidate: dict[str, Any], edge_lookup: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """採用候補から出力用 matched_link を作る。"""

    edge = edge_lookup.get(candidate["directed_edge_id"], {})
    shape_points = edge.get("shape_points", [])
    return {
        "directed_edge_id": candidate["directed_edge_id"],
        "topology_edge_id": candidate.get("topology_edge_id"),
        "road_type": candidate.get("road_type"),
        "lane_count_total": candidate.get("lane_count_total"),
        "speed_limit_kmh": candidate.get("speed_limit_kmh"),
        "length_meter": candidate.get("length_meter"),
        "from_node_id": candidate.get("from_node_id"),
        "to_node_id": candidate.get("to_node_id"),
        "from_point": candidate.get("from_point"),
        "to_point": candidate.get("to_point"),
        "distance_meter": candidate["distance_meter"],
        "nearest_point": candidate["nearest_point"],
        "position_ratio": candidate["position_ratio"],
        "bearing_deg": bearing_between_points(candidate.get("from_point"), candidate.get("to_point")),
        "shape_points": shape_points,
    }


def has_incompatible_pair_assignment(assignments: dict[str, str], observation_id: str, edge_id: str) -> bool:
    """既存のペア制約割当と矛盾するかを返す。"""

    return observation_id in assignments and assignments[observation_id] != edge_id


def add_warning_flag(observation: dict[str, Any], flag: str) -> None:
    """観測点に警告フラグを重複なく追加する。"""

    flags = observation.setdefault("warning_flags", [])
    if flag not in flags:
        flags.append(flag)


def classify_alignment(distance_meter: float | None) -> str:
    """最近傍距離から目視確認用の状態を返す。"""

    if distance_meter is None:
        return "unknown"
    if distance_meter <= 10:
        return "near"
    if distance_meter <= 30:
        return "moderate"
    return "far"


def build_connector_lines(observations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """観測点から最近傍道路候補への補助線を作る。"""

    connectors: list[dict[str, Any]] = []
    for obs in observations:
        link = obs.get("matched_link") or obs.get("provisional_link")
        if not link:
            continue
        connectors.append(
            {
                "observation_id": obs["id"],
                "distance_meter": link["distance_meter"],
                "alignment_status": obs["alignment_status"],
                "points": [
                    {"lat": obs["lat"], "lon": obs["lon"]},
                    link["nearest_point"],
                ],
            }
        )
    return connectors


def summarize(observations: list[dict[str, Any]], road_lines: list[dict[str, Any]]) -> dict[str, Any]:
    """表示用サマリを作る。"""

    distances = [
        obs["nearest_distance_meter"]
        for obs in observations
        if obs.get("nearest_distance_meter") is not None
    ]
    status_counts: dict[str, int] = {}
    profile_counts: dict[str, int] = {}
    match_method_counts: dict[str, int] = {}
    match_confidence_counts: dict[str, int] = {}
    pair_conflict_observation_count = 0
    pair_constraint_unresolved_observation_count = 0
    usable_count = 0
    for obs in observations:
        status = obs.get("alignment_status", "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1
        profile_type = obs.get("volume_profile", {}).get("profile_type", "unknown")
        profile_counts[profile_type] = profile_counts.get(profile_type, 0) + 1
        match_method = obs.get("match_method", "unknown")
        match_method_counts[match_method] = match_method_counts.get(match_method, 0) + 1
        match_confidence = obs.get("match_confidence", "unknown")
        match_confidence_counts[match_confidence] = match_confidence_counts.get(match_confidence, 0) + 1
        if obs.get("usable_for_initial_matching"):
            usable_count += 1
        if obs.get("has_direction_conflict_pair"):
            pair_conflict_observation_count += 1
        if "pair_constraint_unresolved" in obs.get("warning_flags", []):
            pair_constraint_unresolved_observation_count += 1
    return {
        "observation_count": len(observations),
        "usable_for_initial_matching_count": usable_count,
        "excluded_for_initial_matching_count": len(observations) - usable_count,
        "pair_conflict_observation_count": pair_conflict_observation_count,
        "pair_constraint_unresolved_observation_count": pair_constraint_unresolved_observation_count,
        "road_line_count": len(road_lines),
        "nearest_distance_min_meter": min(distances) if distances else None,
        "nearest_distance_median_meter": percentile(distances, 0.5),
        "nearest_distance_p90_meter": percentile(distances, 0.9),
        "nearest_distance_max_meter": max(distances) if distances else None,
        "alignment_status_counts": status_counts,
        "volume_profile_counts": profile_counts,
        "match_method_counts": match_method_counts,
        "match_confidence_counts": match_confidence_counts,
    }


def combined_bounds(road_lines: list[dict[str, Any]], observations: list[dict[str, Any]]) -> dict[str, float]:
    """道路と観測点を含む bbox を返す。"""

    points: list[dict[str, float]] = []
    for road in road_lines:
        points.extend(road["shape_points"])
    points.extend({"lat": obs["lat"], "lon": obs["lon"]} for obs in observations)
    return {
        "min_lat": min(point["lat"] for point in points),
        "max_lat": max(point["lat"] for point in points),
        "min_lon": min(point["lon"] for point in points),
        "max_lon": max(point["lon"] for point in points),
    }


def percentile(values: list[float], ratio: float) -> float | None:
    """単純なパーセンタイルを返す。"""

    if not values:
        return None
    sorted_values = sorted(values)
    index = min(len(sorted_values) - 1, max(0, round((len(sorted_values) - 1) * ratio)))
    return sorted_values[index]


def line_bounds(shape_points: list[dict[str, float]]) -> dict[str, float]:
    """線分の bbox を返す。"""

    return {
        "min_lat": min(point["lat"] for point in shape_points),
        "max_lat": max(point["lat"] for point in shape_points),
        "min_lon": min(point["lon"] for point in shape_points),
        "max_lon": max(point["lon"] for point in shape_points),
    }


def bbox_distance_lower_bound_meter(lat: float, lon: float, bbox: dict[str, float]) -> float:
    """点から bbox までの最短距離の下限を返す。"""

    clamped_lat = min(max(lat, bbox["min_lat"]), bbox["max_lat"])
    clamped_lon = min(max(lon, bbox["min_lon"]), bbox["max_lon"])
    return haversine_meter(lat, lon, clamped_lat, clamped_lon)


def nearest_point_on_polyline(lat: float, lon: float, shape_points: list[dict[str, float]]) -> dict[str, float]:
    """点から polyline 上の最近傍点を返す。"""

    origin_lat = lat
    origin_lon = lon
    px, py = lonlat_to_local_xy(lat, lon, origin_lat, origin_lon)
    best: dict[str, float] | None = None
    total_length = 0.0
    traversed_length = 0.0
    segment_data = []

    for start, end in zip(shape_points, shape_points[1:]):
        ax, ay = lonlat_to_local_xy(start["lat"], start["lon"], origin_lat, origin_lon)
        bx, by = lonlat_to_local_xy(end["lat"], end["lon"], origin_lat, origin_lon)
        length = math.hypot(bx - ax, by - ay)
        segment_data.append((start, end, ax, ay, bx, by, length))
        total_length += length

    for start, end, ax, ay, bx, by, length in segment_data:
        if length == 0:
            traversed_length += length
            continue
        t = ((px - ax) * (bx - ax) + (py - ay) * (by - ay)) / (length * length)
        t = min(1.0, max(0.0, t))
        qx = ax + t * (bx - ax)
        qy = ay + t * (by - ay)
        distance = math.hypot(px - qx, py - qy)
        if best is None or distance < best["distance_meter"]:
            nearest_lat, nearest_lon = local_xy_to_lonlat(qx, qy, origin_lat, origin_lon)
            best = {
                "lat": nearest_lat,
                "lon": nearest_lon,
                "distance_meter": distance,
                "position_ratio": (traversed_length + length * t) / total_length if total_length else 0.0,
            }
        traversed_length += length

    if best is None:
        point = shape_points[0]
        return {
            "lat": point["lat"],
            "lon": point["lon"],
            "distance_meter": haversine_meter(lat, lon, point["lat"], point["lon"]),
            "position_ratio": 0.0,
        }
    return best


def lonlat_to_local_xy(lat: float, lon: float, origin_lat: float, origin_lon: float) -> tuple[float, float]:
    """緯度経度を局所平面 meter 座標へ変換する。"""

    x = (lon - origin_lon) * meters_per_lon_degree(origin_lat)
    y = (lat - origin_lat) * 111_320.0
    return x, y


def local_xy_to_lonlat(x: float, y: float, origin_lat: float, origin_lon: float) -> tuple[float, float]:
    """局所平面 meter 座標を緯度経度へ戻す。"""

    lat = origin_lat + y / 111_320.0
    lon = origin_lon + x / meters_per_lon_degree(origin_lat)
    return lat, lon


def meters_per_lon_degree(lat: float) -> float:
    """指定緯度で経度 1 度あたりの距離を返す。"""

    return 111_320.0 * math.cos(math.radians(lat))


def haversine_meter(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """緯度経度間の距離を meter で返す。"""

    earth_radius_meter = 6_371_000.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    a = math.sin(delta_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    return earth_radius_meter * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def bearing_between_points(start: dict[str, float] | None, end: dict[str, float] | None) -> float | None:
    """2 点間の方位角を返す。"""

    if not start or not end:
        return None
    lat1 = math.radians(start["lat"])
    lat2 = math.radians(end["lat"])
    delta_lon = math.radians(end["lon"] - start["lon"])
    y = math.sin(delta_lon) * math.cos(lat2)
    x = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(delta_lon)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def angle_diff_deg(left: float | None, right: float | None) -> float | None:
    """2 つの方位角の差を 0-180 度で返す。"""

    if left is None or right is None:
        return None
    diff = (left - right + 180.0) % 360.0 - 180.0
    return abs(diff)


if __name__ == "__main__":
    main()
