#!/usr/bin/env python3
"""道路DB出力を固定スナップショットとして取り込む。"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PROJECT_ROOT.parent
DEFAULT_SOURCE_DIR = REPO_ROOT / "private_inputs/road_db_snapshot_source"
DEFAULT_SNAPSHOT_ROOT = PROJECT_ROOT / "data/road_db_snapshots"

REQUIRED_FILES = [
    "directed_edges.geojson",
    "topology_edges.geojson",
    "topology_nodes.geojson",
    "intersections.geojson",
    "intersection_approaches.geojson",
    "turn_relations.json",
]
OPTIONAL_FILES = [
    "summary.json",
]


def parse_args() -> argparse.Namespace:
    """コマンドライン引数を読む。"""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE_DIR)
    parser.add_argument("--snapshot-root", type=Path, default=DEFAULT_SNAPSHOT_ROOT)
    parser.add_argument("--snapshot-id", default=None)
    parser.add_argument("--copy-source-files", action="store_true")
    parser.add_argument("--allow-existing", action="store_true")
    return parser.parse_args()


def main() -> None:
    """道路DBスナップショットを作成する。"""

    args = parse_args()
    source_dir = args.source_dir.resolve()
    snapshot_id = args.snapshot_id or datetime.now().strftime("road_db_%Y%m%d_%H%M%S")
    snapshot_dir = args.snapshot_root / snapshot_id

    if snapshot_dir.exists() and not args.allow_existing:
        raise FileExistsError(f"スナップショットが既に存在します: {snapshot_dir}")
    snapshot_dir.mkdir(parents=True, exist_ok=True)

    validate_source_files(source_dir)
    source_file_info = build_source_file_info(source_dir)

    directed_edges_geojson = load_json(source_dir / "directed_edges.geojson")
    topology_edges_geojson = load_json(source_dir / "topology_edges.geojson")
    topology_nodes_geojson = load_json(source_dir / "topology_nodes.geojson")
    intersections_geojson = load_json(source_dir / "intersections.geojson")
    approaches_geojson = load_json(source_dir / "intersection_approaches.geojson")
    turn_relations = load_json(source_dir / "turn_relations.json")
    source_summary = load_json(source_dir / "summary.json") if (source_dir / "summary.json").exists() else {}

    snapshot_data, validation = build_snapshot_data(
        snapshot_id=snapshot_id,
        source_dir=source_dir,
        source_file_info=source_file_info,
        source_summary=source_summary,
        directed_edges_geojson=directed_edges_geojson,
        topology_edges_geojson=topology_edges_geojson,
        topology_nodes_geojson=topology_nodes_geojson,
        intersections_geojson=intersections_geojson,
        approaches_geojson=approaches_geojson,
        turn_relations=turn_relations,
    )

    manifest = build_manifest(
        snapshot_id=snapshot_id,
        source_dir=source_dir,
        source_file_info=source_file_info,
        snapshot_data=snapshot_data,
        validation=validation,
        copied_source_files=args.copy_source_files,
    )

    write_json(snapshot_dir / "network_core.json", snapshot_data["network_core"])
    write_json(snapshot_dir / "network_reference.json", snapshot_data["network_reference"])
    write_json(snapshot_dir / "network_geometry.json", snapshot_data["network_geometry"])
    write_json(snapshot_dir / "branch_candidates.json", snapshot_data["branch_candidates_file"])
    write_json(snapshot_dir / "manifest.json", manifest)
    if args.copy_source_files:
        copy_source_files(source_dir, snapshot_dir / "source_files")

    print(f"snapshot_dir: {snapshot_dir}")
    print(json.dumps(manifest["counts"], ensure_ascii=False, indent=2))
    if validation["warnings"]:
        print("warnings:")
        for warning in validation["warnings"]:
            print(f"- {warning}")


def validate_source_files(source_dir: Path) -> None:
    """必要な道路DB出力が存在することを確認する。"""

    missing = [name for name in REQUIRED_FILES if not (source_dir / name).exists()]
    if missing:
        raise FileNotFoundError(f"必要な道路DB出力が見つかりません: {missing}")


def build_source_file_info(source_dir: Path) -> dict[str, dict[str, Any]]:
    """入力ファイルのサイズ・更新時刻・hash を記録する。"""

    file_info: dict[str, dict[str, Any]] = {}
    for name in REQUIRED_FILES + OPTIONAL_FILES:
        path = source_dir / name
        if not path.exists():
            continue
        stat = path.stat()
        file_info[name] = {
            "path": str(path),
            "size_bytes": stat.st_size,
            "mtime_epoch": stat.st_mtime,
            "sha256": sha256_file(path),
        }
    return file_info


def sha256_file(path: Path) -> str:
    """ファイルの SHA-256 を返す。"""

    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> Any:
    """JSON ファイルを読む。"""

    with path.open(encoding="utf-8") as file:
        return json.load(file)


def write_json(path: Path, data: Any) -> None:
    """JSON ファイルを書き出す。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)
        file.write("\n")


def build_snapshot_data(
    *,
    snapshot_id: str,
    source_dir: Path,
    source_file_info: dict[str, dict[str, Any]],
    source_summary: dict[str, Any],
    directed_edges_geojson: dict[str, Any],
    topology_edges_geojson: dict[str, Any],
    topology_nodes_geojson: dict[str, Any],
    intersections_geojson: dict[str, Any],
    approaches_geojson: dict[str, Any],
    turn_relations: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """道路DB出力から分割済みスナップショットを作る。"""

    topology_nodes = convert_topology_nodes(topology_nodes_geojson)
    topology_edges, topology_edge_geometries = convert_topology_edges(topology_edges_geojson)
    directed_edges, directed_edge_geometries = convert_directed_edges(directed_edges_geojson)
    intersections = convert_intersections(intersections_geojson)
    approaches, approach_geometries = convert_approaches(approaches_geojson)

    validation = validate_references(
        topology_nodes=topology_nodes,
        topology_edges=topology_edges,
        directed_edges=directed_edges,
        intersections=intersections,
        approaches=approaches,
        turn_relations=turn_relations,
    )

    branch_candidates, branch_options, branch_summary = build_branch_candidates(
        directed_edges=directed_edges,
        intersections=intersections,
        approaches=approaches,
        turn_relations=turn_relations,
    )

    counts = {
        "topology_node_count": len(topology_nodes),
        "topology_edge_count": len(topology_edges),
        "directed_edge_count": len(directed_edges),
        "intersection_count": len(intersections),
        "intersection_approach_count": len(approaches),
        "turn_relation_count": len(turn_relations),
        "branch_candidate_count": len(branch_candidates),
        "branch_option_state_count": len(branch_options),
        **branch_summary,
    }

    common_metadata = {
        "snapshot_id": snapshot_id,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "source": {
            "source_dir": str(source_dir),
            "source_file_hashes": {
                name: info["sha256"]
                for name, info in source_file_info.items()
            },
            "source_summary_counts": source_summary.get("counts", {}),
        },
        "counts": counts,
    }

    network_core = {
        "schema_version": "road_db_network_core.v2",
        **common_metadata,
        "graph": {
            "topology_nodes": topology_nodes,
            "directed_edges": directed_edges,
        },
        "intersections": intersections,
        "branch_options": branch_options,
        "reference_file": "network_reference.json",
        "geometry_file": "network_geometry.json",
        "branch_candidates_file": "branch_candidates.json",
        "observation_matching": {
            "status": "not_implemented",
            "reason": "観測点の directed_edge 対応付け方法は別途設計するため、Phase 1 では作成しない。",
        },
        "notes": [
            "road_database_project は読み取り専用の入力元として扱う。",
            "学習・シミュレーションはこのスナップショット内の road_network.json を読む。",
            "turn_relations.json は全候補ではなく、OSM turn restriction に基づく禁止 turn のマスクとして扱う。",
            "Uターンは道路リンクを削除せず、初期学習候補から抑制するフラグとして扱う。",
            "実行時のネットワーク計算では network_core.json を読み、描画時だけ network_geometry.json を読む。",
        ],
    }

    network_reference = {
        "schema_version": "road_db_network_reference.v1",
        **common_metadata,
        "graph": {
            "topology_edges": topology_edges,
        },
        "intersection_approaches": approaches,
        "turn_relations": turn_relations,
        "notes": [
            "network_core.json から外した検査・参照用データ。",
            "通常のシミュレーション実行では必須ではない。",
        ],
    }

    network_geometry = {
        "schema_version": "road_db_network_geometry.v1",
        **common_metadata,
        "topology_edge_geometries": topology_edge_geometries,
        "directed_edge_geometries": directed_edge_geometries,
        "intersection_points": {
            intersection["intersection_id"]: {
                "lat": intersection["lat"],
                "lon": intersection["lon"],
                "topology_node_id": intersection["topology_node_id"],
            }
            for intersection in intersections
        },
        "approach_geometries": approach_geometries,
    }

    branch_candidates_file = {
        "schema_version": "road_db_branch_candidates.v1",
        **common_metadata,
        "branch_candidates": branch_candidates,
    }

    return {
        "network_core": network_core,
        "network_reference": network_reference,
        "network_geometry": network_geometry,
        "branch_candidates_file": branch_candidates_file,
    }, validation


def convert_topology_nodes(geojson: dict[str, Any]) -> list[dict[str, Any]]:
    """topology node を内部形式へ変換する。"""

    nodes: list[dict[str, Any]] = []
    for feature in geojson["features"]:
        props = feature["properties"]
        lon, lat = feature["geometry"]["coordinates"]
        nodes.append(
            {
                "topology_node_id": props["topology_node_id"],
                "node_type": props.get("node_type"),
                "lat": lat,
                "lon": lon,
                "degree": props.get("degree"),
                "incident_segment_count": props.get("incident_segment_count"),
            }
        )
    return nodes


def convert_topology_edges(geojson: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """topology edge を内部形式へ変換する。"""

    edges: list[dict[str, Any]] = []
    geometries: dict[str, Any] = {}
    for feature in geojson["features"]:
        props = feature["properties"]
        topology_edge_id = props["topology_edge_id"]
        edges.append(
            {
                "topology_edge_id": topology_edge_id,
                "from_topology_node_id": props["from_topology_node_id"],
                "to_topology_node_id": props["to_topology_node_id"],
                "road_type": props.get("road_type"),
                "lane_count_total": int(props.get("lane_count_total") or 1),
                "speed_limit_kmh": float(props.get("speed_limit_kmh") or 30.0),
                "length_meter": float(props.get("length_meter") or 0.0),
                "oneway": props.get("oneway"),
                "segment_count": props.get("segment_count"),
                "source_osm_way_ids": props.get("source_osm_way_ids", []),
            }
        )
        geometries[topology_edge_id] = {
            "topology_edge_id": topology_edge_id,
            "shape_points": coordinates_to_shape_points(feature["geometry"]["coordinates"]),
        }
    return edges, geometries


def convert_directed_edges(geojson: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """directed edge を内部形式へ変換する。"""

    edges: list[dict[str, Any]] = []
    geometries: dict[str, Any] = {}
    for feature in geojson["features"]:
        props = feature["properties"]
        directed_edge_id = props["directed_edge_id"]
        length_meter = props.get("length_meter")
        if length_meter is None:
            length_meter = line_length_meter(feature["geometry"]["coordinates"])
        edges.append(
            {
                "directed_edge_id": directed_edge_id,
                "topology_edge_id": props["topology_edge_id"],
                "direction": props.get("direction"),
                "from_node_id": props["from_node_id"],
                "to_node_id": props["to_node_id"],
                "road_type": props.get("road_type"),
                "lane_count_total": int(props.get("lane_count_total") or 1),
                "speed_limit_kmh": float(props.get("speed_limit_kmh") or 30.0),
                "length_meter": float(length_meter),
            }
        )
        geometries[directed_edge_id] = {
            "directed_edge_id": directed_edge_id,
            "shape_points": coordinates_to_shape_points(feature["geometry"]["coordinates"]),
        }
    return edges, geometries


def convert_intersections(geojson: dict[str, Any]) -> list[dict[str, Any]]:
    """intersection を内部形式へ変換する。"""

    intersections: list[dict[str, Any]] = []
    for feature in geojson["features"]:
        props = feature["properties"]
        lon, lat = feature["geometry"]["coordinates"]
        intersections.append(
            {
                "intersection_id": props["intersection_id"],
                "topology_node_id": props["topology_node_id"],
                "lat": lat,
                "lon": lon,
                "degree": props.get("degree"),
            }
        )
    return intersections


def convert_approaches(geojson: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """intersection approach を内部形式へ変換する。"""

    approaches: list[dict[str, Any]] = []
    geometries: dict[str, Any] = {}
    for feature in geojson["features"]:
        props = feature["properties"]
        approach_id = props["approach_id"]
        approaches.append(
            {
                "approach_id": approach_id,
                "intersection_id": props["intersection_id"],
                "topology_node_id": props["topology_node_id"],
                "directed_edge_id": props["directed_edge_id"],
                "topology_edge_id": props["topology_edge_id"],
                "approach_type": props["approach_type"],
                "bearing_deg": props.get("bearing_deg"),
                "road_type": props.get("road_type"),
                "lane_count": int(props.get("lane_count") or 1),
                "source_osm_way_ids": props.get("source_osm_way_ids", []),
            }
        )
        geometries[approach_id] = {
            "approach_id": approach_id,
            "shape_points": coordinates_to_shape_points(feature["geometry"]["coordinates"]),
        }
    return approaches, geometries


def coordinates_to_shape_points(coordinates: list[list[float]]) -> list[dict[str, float]]:
    """GeoJSON 座標列を lat/lon の点列に変換する。"""

    return [{"lat": lat, "lon": lon} for lon, lat in coordinates]


def validate_references(
    *,
    topology_nodes: list[dict[str, Any]],
    topology_edges: list[dict[str, Any]],
    directed_edges: list[dict[str, Any]],
    intersections: list[dict[str, Any]],
    approaches: list[dict[str, Any]],
    turn_relations: list[dict[str, Any]],
) -> dict[str, Any]:
    """道路DB出力間の ID 整合性を確認する。"""

    node_ids = {node["topology_node_id"] for node in topology_nodes}
    topology_edge_ids = {edge["topology_edge_id"] for edge in topology_edges}
    directed_edge_ids = {edge["directed_edge_id"] for edge in directed_edges}
    intersection_ids = {intersection["intersection_id"] for intersection in intersections}
    intersection_node_ids = {intersection["topology_node_id"] for intersection in intersections}
    directed_by_id = {edge["directed_edge_id"]: edge for edge in directed_edges}

    missing: dict[str, int] = {
        "intersection_nodes_missing_from_topology_nodes": len(intersection_node_ids - node_ids),
        "topology_edges_with_missing_from_node": sum(1 for edge in topology_edges if edge["from_topology_node_id"] not in node_ids),
        "topology_edges_with_missing_to_node": sum(1 for edge in topology_edges if edge["to_topology_node_id"] not in node_ids),
        "directed_edges_with_missing_topology_edge": sum(1 for edge in directed_edges if edge["topology_edge_id"] not in topology_edge_ids),
        "directed_edges_with_missing_from_node": sum(1 for edge in directed_edges if edge["from_node_id"] not in node_ids),
        "directed_edges_with_missing_to_node": sum(1 for edge in directed_edges if edge["to_node_id"] not in node_ids),
        "approaches_with_missing_intersection": sum(1 for approach in approaches if approach["intersection_id"] not in intersection_ids),
        "approaches_with_missing_directed_edge": sum(1 for approach in approaches if approach["directed_edge_id"] not in directed_edge_ids),
        "turns_with_missing_intersection": sum(1 for turn in turn_relations if turn["intersection_id"] not in intersection_ids),
        "turns_with_missing_from_edge": sum(1 for turn in turn_relations if turn["from_directed_edge_id"] not in directed_edge_ids),
        "turns_with_missing_to_edge": sum(1 for turn in turn_relations if turn["to_directed_edge_id"] not in directed_edge_ids),
    }

    bad_approach_endpoint = 0
    for approach in approaches:
        edge = directed_by_id.get(approach["directed_edge_id"])
        if not edge:
            continue
        node_id = approach["topology_node_id"]
        if approach["approach_type"] == "incoming" and edge["to_node_id"] != node_id:
            bad_approach_endpoint += 1
        if approach["approach_type"] == "outgoing" and edge["from_node_id"] != node_id:
            bad_approach_endpoint += 1
    missing["approaches_with_bad_endpoint"] = bad_approach_endpoint

    bad_turn_endpoint = 0
    for turn in turn_relations:
        from_edge = directed_by_id.get(turn["from_directed_edge_id"])
        to_edge = directed_by_id.get(turn["to_directed_edge_id"])
        if not from_edge or not to_edge:
            continue
        node_id = turn["topology_node_id"]
        if from_edge["to_node_id"] != node_id or to_edge["from_node_id"] != node_id:
            bad_turn_endpoint += 1
    missing["turns_with_bad_endpoint"] = bad_turn_endpoint

    warnings = [
        f"{name}: {count}"
        for name, count in missing.items()
        if count
    ]

    return {
        "reference_counts": missing,
        "warnings": warnings,
    }


def build_branch_candidates(
    *,
    directed_edges: list[dict[str, Any]],
    intersections: list[dict[str, Any]],
    approaches: list[dict[str, Any]],
    turn_relations: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, int]]:
    """交差点ごとの incoming x outgoing 分岐候補を作る。"""

    directed_edge_ids = {edge["directed_edge_id"] for edge in directed_edges}
    intersection_ids = {intersection["intersection_id"] for intersection in intersections}

    approaches_by_intersection: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    for approach in approaches:
        if approach["intersection_id"] not in intersection_ids:
            continue
        if approach["directed_edge_id"] not in directed_edge_ids:
            continue
        approaches_by_intersection[approach["intersection_id"]][approach["approach_type"]].append(approach)

    prohibited_turns: dict[tuple[str, str, str], dict[str, Any]] = {}
    for turn in turn_relations:
        key = (turn["intersection_id"], turn["from_directed_edge_id"], turn["to_directed_edge_id"])
        if turn.get("is_allowed") is False:
            prohibited_turns[key] = turn

    branch_candidates: list[dict[str, Any]] = []
    branch_options: list[dict[str, Any]] = []
    summary_counter: Counter[str] = Counter()

    for intersection_id in sorted(intersection_ids):
        grouped = approaches_by_intersection.get(intersection_id, {})
        incoming_approaches = sorted(grouped.get("incoming", []), key=lambda item: item["directed_edge_id"])
        outgoing_approaches = sorted(grouped.get("outgoing", []), key=lambda item: item["directed_edge_id"])
        outgoing_by_incoming: dict[str, list[dict[str, Any]]] = defaultdict(list)

        for incoming in incoming_approaches:
            for outgoing in outgoing_approaches:
                key = (intersection_id, incoming["directed_edge_id"], outgoing["directed_edge_id"])
                prohibited_turn = prohibited_turns.get(key)
                turn_type = classify_turn_type(incoming.get("bearing_deg"), outgoing.get("bearing_deg"))
                is_u_turn = turn_type == "u_turn"
                is_prohibited = prohibited_turn is not None
                initial_learning_allowed = (not is_prohibited) and (not is_u_turn)
                candidate = {
                    "branch_candidate_id": f"{intersection_id}|{incoming['directed_edge_id']}|{outgoing['directed_edge_id']}",
                    "intersection_id": intersection_id,
                    "topology_node_id": incoming["topology_node_id"],
                    "incoming_directed_edge_id": incoming["directed_edge_id"],
                    "outgoing_directed_edge_id": outgoing["directed_edge_id"],
                    "incoming_bearing_deg": incoming.get("bearing_deg"),
                    "outgoing_bearing_deg": outgoing.get("bearing_deg"),
                    "turn_type": turn_type,
                    "is_u_turn": is_u_turn,
                    "is_prohibited_by_turn_relation": is_prohibited,
                    "restriction_relation_id": prohibited_turn.get("restriction_relation_id") if prohibited_turn else None,
                    "restriction_type": prohibited_turn.get("restriction_type") if prohibited_turn else None,
                    "initial_learning_allowed": initial_learning_allowed,
                }
                branch_candidates.append(candidate)
                summary_counter["candidate_total"] += 1
                if is_u_turn:
                    summary_counter["u_turn_candidate_count"] += 1
                if is_prohibited:
                    summary_counter["prohibited_candidate_count"] += 1
                if initial_learning_allowed:
                    summary_counter["initial_learning_candidate_count"] += 1
                    outgoing_by_incoming[incoming["directed_edge_id"]].append(
                        {
                            "outgoing_directed_edge_id": outgoing["directed_edge_id"],
                            "turn_type": turn_type,
                            "outgoing_bearing_deg": outgoing.get("bearing_deg"),
                        }
                    )

        for incoming_edge_id, outgoing_options in sorted(outgoing_by_incoming.items()):
            branch_options.append(
                {
                    "intersection_id": intersection_id,
                    "incoming_directed_edge_id": incoming_edge_id,
                    "outgoing_options": outgoing_options,
                }
            )

    summary = {
        "raw_branch_candidate_count": summary_counter["candidate_total"],
        "u_turn_candidate_count": summary_counter["u_turn_candidate_count"],
        "prohibited_candidate_count": summary_counter["prohibited_candidate_count"],
        "initial_learning_candidate_count": summary_counter["initial_learning_candidate_count"],
    }
    return branch_candidates, branch_options, summary


def classify_turn_type(incoming_bearing: float | None, outgoing_bearing: float | None) -> str:
    """進入方位と退出方位から旋回種別を推定する。"""

    if incoming_bearing is None or outgoing_bearing is None:
        return "unknown"
    diff = normalize_angle_deg(float(outgoing_bearing) - float(incoming_bearing))
    if abs(diff) <= 35:
        return "straight"
    if abs(diff) >= 145:
        return "u_turn"
    if diff > 0:
        return "right"
    return "left"


def normalize_angle_deg(value: float) -> float:
    """角度を -180 から 180 の範囲へ正規化する。"""

    return (value + 180.0) % 360.0 - 180.0


def line_length_meter(coordinates: list[list[float]]) -> float:
    """GeoJSON LineString の長さを概算する。"""

    total = 0.0
    for left, right in zip(coordinates, coordinates[1:]):
        total += haversine_meter(left[1], left[0], right[1], right[0])
    return total


def haversine_meter(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """緯度経度間の距離を meter で返す。"""

    earth_radius_meter = 6_371_000.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    a = math.sin(delta_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    return earth_radius_meter * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def build_manifest(
    *,
    snapshot_id: str,
    source_dir: Path,
    source_file_info: dict[str, dict[str, Any]],
    snapshot_data: dict[str, Any],
    validation: dict[str, Any],
    copied_source_files: bool,
) -> dict[str, Any]:
    """スナップショットの再現性確認用 manifest を作る。"""

    network_core = snapshot_data["network_core"]
    return {
        "schema_version": "road_db_snapshot_manifest.v1",
        "snapshot_id": snapshot_id,
        "created_at": network_core["created_at"],
        "source_dir": str(source_dir),
        "source_files": source_file_info,
        "copied_source_files": copied_source_files,
        "counts": network_core["counts"],
        "validation": validation,
        "outputs": {
            "network_core": "network_core.json",
            "network_reference": "network_reference.json",
            "network_geometry": "network_geometry.json",
            "branch_candidates": "branch_candidates.json",
            "manifest": "manifest.json",
        },
        "phase2_observation_matching": {
            "status": "deferred",
            "reason": "観測点をどう道路リンクへ対応付けるかは別途設計する。",
        },
    }


def copy_source_files(source_dir: Path, destination_dir: Path) -> None:
    """必要な元ファイルをスナップショット内にコピーする。"""

    destination_dir.mkdir(parents=True, exist_ok=True)
    for name in REQUIRED_FILES + OPTIONAL_FILES:
        source_path = source_dir / name
        if source_path.exists():
            shutil.copy2(source_path, destination_dir / name)


if __name__ == "__main__":
    main()
