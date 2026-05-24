#!/usr/bin/env python3
"""OSM 車道からトポロジーとジオメトリの試作レイヤーを生成する。"""

from __future__ import annotations

import argparse
import json
import math
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict, deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ALLOWED_HIGHWAYS = {
    "motorway",
    "motorway_link",
    "trunk",
    "trunk_link",
    "primary",
    "primary_link",
    "secondary",
    "secondary_link",
    "tertiary",
    "tertiary_link",
    "unclassified",
    "residential",
    "living_street",
    "service",
}

LARGE_ROAD_TYPES = {
    "motorway",
    "motorway_link",
    "trunk",
    "trunk_link",
    "primary",
    "primary_link",
    "secondary",
    "secondary_link",
}

CURRENT_SIMULATION_EXCLUDED_ROAD_TYPES = {
    "motorway",
    "motorway_link",
}


@dataclass(frozen=True)
class RoadSegment:
    """OSM way の隣接 node 間区間を表す。"""

    segment_id: str
    osm_way_id: str
    segment_index: int
    from_node_id: str
    to_node_id: str
    highway: str
    lane_count: int
    speed_limit_kmh: int
    oneway: str
    name: str | None

    @property
    def attribute_signature(self) -> tuple[str, int, int, str]:
        """縮約時に連結可能かを判定する主要属性を返す。"""

        return (self.highway, self.lane_count, self.speed_limit_kmh, self.oneway)


def parse_args() -> argparse.Namespace:
    """コマンドライン引数を読む。"""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        type=Path,
        default=Path("../inverse_traffic_simulator/data/raw_osm/tokyo_station_raw.osm"),
        help="入力 OSM XML",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("road_database_project/output/prototype_tokyo_station"),
        help="出力ディレクトリ",
    )
    return parser.parse_args()


def main() -> None:
    """試作レイヤーを生成する。"""

    args = parse_args()
    raw_nodes, raw_ways, turn_restrictions, excluded_way_counts = load_osm(args.input)
    segments = build_segments(raw_ways)
    used_node_ids = {node_id for segment in segments for node_id in (segment.from_node_id, segment.to_node_id)}
    used_nodes = {node_id: raw_nodes[node_id] for node_id in used_node_ids if node_id in raw_nodes}
    incident_segments = build_incident_segments(segments)
    topology_node_types, topology_node_cut_reasons = find_topology_node_types(incident_segments)
    topology_node_ids = set(topology_node_types)
    all_topology_edges = build_topology_edges(segments, incident_segments, topology_node_ids)
    canonical_candidate_edges = [
        edge
        for edge in all_topology_edges
        if edge["road_type"] not in CURRENT_SIMULATION_EXCLUDED_ROAD_TYPES
    ]
    component_edge_id_sets = topology_connected_components(canonical_candidate_edges)
    canonical_edge_ids = max(component_edge_id_sets, key=len, default=set())
    topology_edges = [edge for edge in all_topology_edges if edge["topology_edge_id"] in canonical_edge_ids]
    excluded_topology_edges = [edge for edge in all_topology_edges if edge["topology_edge_id"] not in canonical_edge_ids]
    canonical_topology_node_ids = {
        node_id
        for edge in topology_edges
        for node_id in (edge["from_topology_node_id"], edge["to_topology_node_id"])
    }
    canonical_topology_node_types = {
        node_id: topology_node_types[node_id]
        for node_id in canonical_topology_node_ids
    }
    canonical_topology_node_cut_reasons = {
        node_id: topology_node_cut_reasons.get(node_id, [])
        for node_id in canonical_topology_node_ids
    }
    intersection_node_ids = {
        node_id
        for node_id, node_type in canonical_topology_node_types.items()
        if node_type == "intersection"
    }
    directed_edges = build_directed_edges(topology_edges, raw_nodes)
    analysis_segments = build_analysis_segments(topology_edges)
    intersection_approaches = build_intersection_approaches(directed_edges, intersection_node_ids, raw_nodes)
    turn_relations, turn_restriction_summary = build_turn_relations(
        intersection_node_ids=intersection_node_ids,
        directed_edges=directed_edges,
        intersection_approaches=intersection_approaches,
        turn_restrictions=turn_restrictions,
        nodes=raw_nodes,
    )

    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    write_geojson(output_dir / "osm_roads.geojson", build_osm_roads_geojson(raw_ways, raw_nodes))
    write_geojson(output_dir / "geometry_edges.geojson", build_geometry_edges_geojson(topology_edges, raw_nodes))
    write_geojson(output_dir / "all_topology_edges.geojson", build_topology_edges_geojson(all_topology_edges, raw_nodes))
    write_geojson(output_dir / "excluded_topology_edges.geojson", build_topology_edges_geojson(excluded_topology_edges, raw_nodes))
    write_geojson(
        output_dir / "topology_nodes.geojson",
        build_topology_nodes_geojson(
            canonical_topology_node_types,
            canonical_topology_node_cut_reasons,
            used_nodes,
            incident_segments,
        ),
    )
    write_geojson(
        output_dir / "intersections.geojson",
        build_intersections_geojson(intersection_node_ids, used_nodes, incident_segments),
    )
    write_geojson(
        output_dir / "intersection_approaches.geojson",
        build_intersection_approaches_geojson(intersection_approaches, raw_nodes),
    )
    write_geojson(
        output_dir / "turn_relations.geojson",
        build_turn_relations_geojson(turn_relations, raw_nodes),
    )
    (output_dir / "turn_relations.json").write_text(
        json.dumps(turn_relations, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    write_geojson(output_dir / "topology_edges.geojson", build_topology_edges_geojson(topology_edges, raw_nodes))
    write_geojson(output_dir / "directed_edges.geojson", build_directed_edges_geojson(directed_edges, raw_nodes))
    write_geojson(output_dir / "analysis_segments.geojson", build_analysis_segments_geojson(analysis_segments, raw_nodes))

    summary = build_summary(
        input_path=args.input,
        raw_node_count=len(raw_nodes),
        raw_way_count=len(raw_ways) + sum(excluded_way_counts.values()),
        selected_way_count=len(raw_ways),
        excluded_way_counts=excluded_way_counts,
        used_node_count=len(used_nodes),
        nodes=raw_nodes,
        topology_node_types=canonical_topology_node_types,
        topology_node_cut_reasons=canonical_topology_node_cut_reasons,
        all_topology_node_count=len(topology_node_types),
        intersection_node_ids=intersection_node_ids,
        all_topology_edges=all_topology_edges,
        canonical_candidate_edges=canonical_candidate_edges,
        topology_edges=topology_edges,
        excluded_topology_edges=excluded_topology_edges,
        directed_edges=directed_edges,
        analysis_segments=analysis_segments,
        intersection_approaches=intersection_approaches,
        turn_relations=turn_relations,
        turn_restrictions=turn_restrictions,
        turn_restriction_summary=turn_restriction_summary,
        incident_segments=incident_segments,
    )
    (output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print(f"出力: {output_dir}")
    print(json.dumps(summary["counts"], ensure_ascii=False, indent=2))


def load_osm(path: Path) -> tuple[dict[str, dict[str, float]], list[dict[str, Any]], list[dict[str, Any]], Counter[str]]:
    """OSM XML から node と対象車道 way を読む。"""

    root = ET.parse(path).getroot()
    nodes: dict[str, dict[str, float]] = {}
    excluded_way_counts: Counter[str] = Counter()

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
            excluded_way_counts["unsupported_highway"] += 1
            continue
        if tags.get("access") in {"no", "private"}:
            excluded_way_counts[f"access_{tags['access']}"] += 1
            continue
        if tags.get("motor_vehicle") in {"no", "private"}:
            excluded_way_counts[f"motor_vehicle_{tags['motor_vehicle']}"] += 1
            continue
        if tags.get("area") == "yes":
            excluded_way_counts["area_yes"] += 1
            continue
        if tags.get("service") == "parking_aisle":
            excluded_way_counts["parking_aisle"] += 1
            continue
        if highway == "construction" or tags.get("construction"):
            excluded_way_counts["construction"] += 1
            continue

        node_refs = [nd.attrib["ref"] for nd in way.findall("nd")]
        node_refs = [node_ref for node_ref in node_refs if node_ref in nodes]
        if len(node_refs) < 2:
            excluded_way_counts["too_short"] += 1
            continue

        ways.append(
            {
                "id": way.attrib["id"],
                "node_refs": node_refs,
                "tags": tags,
                "highway": highway,
                "lane_count": parse_lane_count(tags.get("lanes")) or default_lane_count(highway),
                "speed_limit_kmh": parse_speed_limit(tags.get("maxspeed"), highway),
                "oneway": parse_oneway(tags),
                "name": tags.get("name:ja") or tags.get("name"),
            }
        )

    turn_restrictions = parse_turn_restrictions(root)

    return nodes, ways, turn_restrictions, excluded_way_counts


def parse_turn_restrictions(root: ET.Element) -> list[dict[str, Any]]:
    """OSM relation から右左折規制を読む。"""

    restrictions: list[dict[str, Any]] = []
    for relation in root.findall("relation"):
        tags = {tag.attrib["k"]: tag.attrib["v"] for tag in relation.findall("tag")}
        if tags.get("type") != "restriction":
            continue

        from_way_ids: list[str] = []
        to_way_ids: list[str] = []
        via_node_ids: list[str] = []
        via_way_ids: list[str] = []
        for member in relation.findall("member"):
            member_type = member.attrib.get("type")
            role = member.attrib.get("role")
            ref = member.attrib.get("ref")
            if not ref:
                continue
            if member_type == "way" and role == "from":
                from_way_ids.append(ref)
            elif member_type == "way" and role == "to":
                to_way_ids.append(ref)
            elif member_type == "node" and role == "via":
                via_node_ids.append(ref)
            elif member_type == "way" and role == "via":
                via_way_ids.append(ref)

        restrictions.append(
            {
                "relation_id": relation.attrib["id"],
                "restriction": tags.get("restriction", "unknown"),
                "from_way_ids": from_way_ids,
                "to_way_ids": to_way_ids,
                "via_node_ids": via_node_ids,
                "via_way_ids": via_way_ids,
            }
        )

    return restrictions


def build_segments(ways: list[dict[str, Any]]) -> list[RoadSegment]:
    """OSM way を隣接 node 間の区間へ分解する。"""

    segments: list[RoadSegment] = []
    for way in ways:
        for segment_index, (from_node_id, to_node_id) in enumerate(zip(way["node_refs"], way["node_refs"][1:])):
            segments.append(
                RoadSegment(
                    segment_id=f"seg_{way['id']}_{segment_index}",
                    osm_way_id=way["id"],
                    segment_index=segment_index,
                    from_node_id=from_node_id,
                    to_node_id=to_node_id,
                    highway=way["highway"],
                    lane_count=way["lane_count"],
                    speed_limit_kmh=way["speed_limit_kmh"],
                    oneway=way["oneway"],
                    name=way["name"],
                )
            )
    return segments


def build_incident_segments(segments: list[RoadSegment]) -> dict[str, list[RoadSegment]]:
    """node ごとの接続 segment を作る。"""

    incident_segments: dict[str, list[RoadSegment]] = defaultdict(list)
    for segment in segments:
        incident_segments[segment.from_node_id].append(segment)
        incident_segments[segment.to_node_id].append(segment)
    return incident_segments


def find_topology_node_types(
    incident_segments: dict[str, list[RoadSegment]],
) -> tuple[dict[str, str], dict[str, list[str]]]:
    """トポロジー上残す node と種別を判定する。"""

    topology_node_types: dict[str, str] = {}
    topology_node_cut_reasons: dict[str, set[str]] = defaultdict(set)

    for node_id, node_segments in incident_segments.items():
        degree = neighbor_count(node_id, node_segments)
        if degree >= 3:
            topology_node_types[node_id] = "intersection"
            topology_node_cut_reasons[node_id].add("intersection")
            continue
        if degree == 1:
            topology_node_types[node_id] = "dead_end"
            topology_node_cut_reasons[node_id].add("dead_end")
            continue
        if is_oneway_transition(node_id, node_segments):
            topology_node_types[node_id] = "direction_change"
            topology_node_cut_reasons[node_id].add("oneway_transition")
            continue

        attribute_reasons = attribute_boundary_reasons(node_segments)
        if attribute_reasons:
            topology_node_types[node_id] = "attribute_boundary"
            topology_node_cut_reasons[node_id].update(attribute_reasons)

    # すべて degree 2 の閉路だけで構成される場合に備え、成分ごとに 1 点を残す。
    visited_nodes: set[str] = set()
    for start_node_id in incident_segments:
        if start_node_id in visited_nodes:
            continue
        component_nodes = collect_component_nodes(start_node_id, incident_segments, visited_nodes)
        if not component_nodes & set(topology_node_types):
            anchor_node_id = sorted(component_nodes)[0]
            topology_node_types[anchor_node_id] = "cycle_anchor"
            topology_node_cut_reasons[anchor_node_id].add("cycle_anchor")

    return topology_node_types, {
        node_id: sorted(topology_node_cut_reasons[node_id])
        for node_id in topology_node_types
    }


def attribute_boundary_reasons(node_segments: list[RoadSegment]) -> list[str]:
    """edge 属性の変化で切断すべき理由を返す。"""

    reasons = []
    if len({segment.lane_count for segment in node_segments}) > 1:
        reasons.append("lane_count_change")
    if len({segment.speed_limit_kmh for segment in node_segments}) > 1:
        reasons.append("speed_limit_change")
    return reasons


def is_oneway_transition(
    node_id: str,
    node_segments: list[RoadSegment],
) -> bool:
    """一方通行の開始または終了に見える node か判定する。"""

    incoming_allowed = 0
    outgoing_allowed = 0
    for segment in node_segments:
        allows_forward, allows_reverse = allowed_directions(segment)
        if segment.to_node_id == node_id and allows_forward:
            incoming_allowed += 1
        if segment.from_node_id == node_id and allows_forward:
            outgoing_allowed += 1
        if segment.from_node_id == node_id and allows_reverse:
            incoming_allowed += 1
        if segment.to_node_id == node_id and allows_reverse:
            outgoing_allowed += 1
    return incoming_allowed != outgoing_allowed


def collect_component_nodes(
    start_node_id: str,
    incident_segments: dict[str, list[RoadSegment]],
    visited_nodes: set[str],
) -> set[str]:
    """未訪問の連結成分 node を返す。"""

    queue = deque([start_node_id])
    component_nodes: set[str] = set()
    while queue:
        node_id = queue.popleft()
        if node_id in visited_nodes:
            continue
        visited_nodes.add(node_id)
        component_nodes.add(node_id)
        for segment in incident_segments[node_id]:
            other_node_id = segment.to_node_id if segment.from_node_id == node_id else segment.from_node_id
            if other_node_id not in visited_nodes:
                queue.append(other_node_id)
    return component_nodes


def build_topology_edges(
    segments: list[RoadSegment],
    incident_segments: dict[str, list[RoadSegment]],
    topology_node_ids: set[str],
) -> list[dict[str, Any]]:
    """トポロジー node 間を結ぶ edge を作る。"""

    topology_edges: list[dict[str, Any]] = []
    visited_segment_ids: set[str] = set()
    edge_index = 0

    for start_node_id in sorted(topology_node_ids):
        for first_segment in sorted(incident_segments[start_node_id], key=lambda item: item.segment_id):
            if first_segment.segment_id in visited_segment_ids:
                continue

            chain_segments, node_path = walk_segment_chain(
                start_node_id=start_node_id,
                first_segment=first_segment,
                incident_segments=incident_segments,
                topology_node_ids=topology_node_ids,
                visited_segment_ids=visited_segment_ids,
            )
            if not chain_segments:
                continue
            edge_index += 1
            topology_edges.append(
                {
                    "topology_edge_id": f"topology_edge_{edge_index:06d}",
                    "from_topology_node_id": node_path[0],
                    "to_topology_node_id": node_path[-1],
                    "node_path": node_path,
                    "segment_ids": [segment.segment_id for segment in chain_segments],
                    "source_osm_way_ids": sorted({segment.osm_way_id for segment in chain_segments}),
                    "road_type": chain_segments[0].highway,
                    "lane_count_total": chain_segments[0].lane_count,
                    "speed_limit_kmh": chain_segments[0].speed_limit_kmh,
                    "oneway": chain_segments[0].oneway,
                    "name": chain_segments[0].name,
                    "allows_forward": all(segment_allows_traversal(segment, node_path[index], node_path[index + 1]) for index, segment in enumerate(chain_segments)),
                    "allows_reverse": all(segment_allows_traversal(segment, node_path[index + 1], node_path[index]) for index, segment in enumerate(chain_segments)),
                }
            )

    return topology_edges


def walk_segment_chain(
    start_node_id: str,
    first_segment: RoadSegment,
    incident_segments: dict[str, list[RoadSegment]],
    topology_node_ids: set[str],
    visited_segment_ids: set[str],
) -> tuple[list[RoadSegment], list[str]]:
    """1 本のトポロジー edge に含まれる segment 列をたどる。"""

    chain_segments: list[RoadSegment] = []
    node_path = [start_node_id]
    current_node_id = start_node_id
    current_segment = first_segment

    while True:
        if current_segment.segment_id in visited_segment_ids:
            break
        visited_segment_ids.add(current_segment.segment_id)
        chain_segments.append(current_segment)
        next_node_id = (
            current_segment.to_node_id
            if current_segment.from_node_id == current_node_id
            else current_segment.from_node_id
        )
        node_path.append(next_node_id)
        if next_node_id in topology_node_ids and next_node_id != start_node_id:
            break

        next_candidates = [
            segment
            for segment in incident_segments[next_node_id]
            if segment.segment_id not in visited_segment_ids
        ]
        if not next_candidates:
            break
        current_node_id = next_node_id
        current_segment = sorted(next_candidates, key=lambda item: item.segment_id)[0]

    return chain_segments, node_path


def build_directed_edges(
    topology_edges: list[dict[str, Any]],
    nodes: dict[str, dict[str, float]],
) -> list[dict[str, Any]]:
    """トポロジー edge から有向 edge を作る。"""

    directed_edges: list[dict[str, Any]] = []
    directed_index = 0
    for edge in topology_edges:
        if edge["allows_forward"]:
            directed_index += 1
            directed_edges.append(
                {
                    **edge,
                    "directed_edge_id": f"directed_edge_{directed_index:06d}",
                    "from_topology_node_id": edge["from_topology_node_id"],
                    "to_topology_node_id": edge["to_topology_node_id"],
                    "node_path": edge["node_path"],
                    "length_meter": round(edge_length_meter(edge, nodes), 2),
                }
            )
        if edge["allows_reverse"]:
            directed_index += 1
            directed_edges.append(
                {
                    **edge,
                    "directed_edge_id": f"directed_edge_{directed_index:06d}",
                    "from_topology_node_id": edge["to_topology_node_id"],
                    "to_topology_node_id": edge["from_topology_node_id"],
                    "node_path": list(reversed(edge["node_path"])),
                    "length_meter": round(edge_length_meter(edge, nodes), 2),
                }
            )
    return directed_edges


def build_analysis_segments(topology_edges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """初期試作では topology edge と同粒度の analysis segment を作る。"""

    analysis_segments = []
    for index, edge in enumerate(topology_edges, start=1):
        analysis_segments.append(
            {
                **edge,
                "analysis_segment_id": f"analysis_segment_{index:06d}",
                "segment_index": 0,
                "from_position_ratio": 0.0,
                "to_position_ratio": 1.0,
            }
        )
    return analysis_segments


def build_osm_roads_geojson(ways: list[dict[str, Any]], nodes: dict[str, dict[str, float]]) -> dict[str, Any]:
    """抽出対象 OSM way の GeoJSON を作る。"""

    features = []
    for way in ways:
        coordinates = coordinates_for_node_ids(way["node_refs"], nodes)
        features.append(
            line_feature(
                coordinates,
                {
                    "osm_way_id": way["id"],
                    "road_type": way["highway"],
                    "lane_count": way["lane_count"],
                    "speed_limit_kmh": way["speed_limit_kmh"],
                    "oneway": way["oneway"],
                    "name": way["name"],
                },
            )
        )
    return feature_collection(features)


def build_geometry_edges_geojson(topology_edges: list[dict[str, Any]], nodes: dict[str, dict[str, float]]) -> dict[str, Any]:
    """ジオメトリ edge の GeoJSON を作る。"""

    return feature_collection(
        [
            line_feature(
                coordinates_for_node_ids(edge["node_path"], nodes),
                {
                    "topology_edge_id": edge["topology_edge_id"],
                    "road_type": edge["road_type"],
                    "source_osm_way_ids": edge["source_osm_way_ids"],
                },
            )
            for edge in topology_edges
        ]
    )


def build_topology_nodes_geojson(
    topology_node_types: dict[str, str],
    topology_node_cut_reasons: dict[str, list[str]],
    nodes: dict[str, dict[str, float]],
    incident_segments: dict[str, list[RoadSegment]],
) -> dict[str, Any]:
    """トポロジー node の GeoJSON を作る。"""

    features = []
    for node_id in sorted(topology_node_types):
        node = nodes[node_id]
        features.append(
            point_feature(
                [node["lon"], node["lat"]],
                {
                    "topology_node_id": node_id,
                    "node_type": topology_node_types[node_id],
                    "cut_reasons": topology_node_cut_reasons.get(node_id, []),
                    "incident_segment_count": len(incident_segments[node_id]),
                    "degree": neighbor_count(node_id, incident_segments[node_id]),
                },
            )
        )
    return feature_collection(features)


def build_intersections_geojson(
    intersection_node_ids: set[str],
    nodes: dict[str, dict[str, float]],
    incident_segments: dict[str, list[RoadSegment]],
) -> dict[str, Any]:
    """交差点だけの GeoJSON を作る。"""

    features = []
    for node_id in sorted(intersection_node_ids):
        node = nodes[node_id]
        features.append(
            point_feature(
                [node["lon"], node["lat"]],
                {
                    "intersection_id": f"intersection_{node_id}",
                    "topology_node_id": node_id,
                    "degree": neighbor_count(node_id, incident_segments[node_id]),
                },
            )
        )
    return feature_collection(features)


def build_topology_edges_geojson(topology_edges: list[dict[str, Any]], nodes: dict[str, dict[str, float]]) -> dict[str, Any]:
    """トポロジー edge の GeoJSON を作る。"""

    return feature_collection(
        [
            line_feature(
                coordinates_for_node_ids(edge["node_path"], nodes),
                {
                    "topology_edge_id": edge["topology_edge_id"],
                    "from_topology_node_id": edge["from_topology_node_id"],
                    "to_topology_node_id": edge["to_topology_node_id"],
                    "road_type": edge["road_type"],
                    "lane_count_total": edge["lane_count_total"],
                    "speed_limit_kmh": edge["speed_limit_kmh"],
                    "length_meter": round(edge_length_meter(edge, nodes), 2),
                    "oneway": edge["oneway"],
                    "segment_count": len(edge["segment_ids"]),
                    "source_osm_way_ids": edge["source_osm_way_ids"],
                },
            )
            for edge in topology_edges
        ]
    )


def build_directed_edges_geojson(directed_edges: list[dict[str, Any]], nodes: dict[str, dict[str, float]]) -> dict[str, Any]:
    """有向 edge の GeoJSON を作る。"""

    return feature_collection(
        [
            line_feature(
                coordinates_for_node_ids(edge["node_path"], nodes),
                {
                    "directed_edge_id": edge["directed_edge_id"],
                    "topology_edge_id": edge["topology_edge_id"],
                    "from_topology_node_id": edge["from_topology_node_id"],
                    "to_topology_node_id": edge["to_topology_node_id"],
                    "road_type": edge["road_type"],
                    "lane_count_total": edge["lane_count_total"],
                    "speed_limit_kmh": edge["speed_limit_kmh"],
                    "length_meter": edge["length_meter"],
                },
            )
            for edge in directed_edges
        ]
    )


def build_intersection_approaches(
    directed_edges: list[dict[str, Any]],
    intersection_node_ids: set[str],
    nodes: dict[str, dict[str, float]],
) -> list[dict[str, Any]]:
    """交差点へ出入りする directed edge を作る。"""

    approaches: list[dict[str, Any]] = []
    for edge in directed_edges:
        if edge["to_topology_node_id"] in intersection_node_ids:
            approaches.append(
                build_intersection_approach(
                    edge=edge,
                    node_id=edge["to_topology_node_id"],
                    approach_type="incoming",
                    nodes=nodes,
                )
            )
        if edge["from_topology_node_id"] in intersection_node_ids:
            approaches.append(
                build_intersection_approach(
                    edge=edge,
                    node_id=edge["from_topology_node_id"],
                    approach_type="outgoing",
                    nodes=nodes,
                )
            )
    return approaches


def build_intersection_approach(
    edge: dict[str, Any],
    node_id: str,
    approach_type: str,
    nodes: dict[str, dict[str, float]],
) -> dict[str, Any]:
    """1 本の交差点 approach を作る。"""

    node_path = edge["node_path"]
    bearing_deg = None
    if approach_type == "incoming" and len(node_path) >= 2:
        bearing_deg = bearing_between_nodes(node_path[-2], node_path[-1], nodes)
    elif approach_type == "outgoing" and len(node_path) >= 2:
        bearing_deg = bearing_between_nodes(node_path[0], node_path[1], nodes)

    return {
        "approach_id": f"approach_{node_id}_{edge['directed_edge_id']}_{approach_type}",
        "intersection_id": f"intersection_{node_id}",
        "topology_node_id": node_id,
        "directed_edge_id": edge["directed_edge_id"],
        "topology_edge_id": edge["topology_edge_id"],
        "approach_type": approach_type,
        "bearing_deg": round(bearing_deg, 2) if bearing_deg is not None else None,
        "road_type": edge["road_type"],
        "lane_count": edge["lane_count_total"],
        "source_osm_way_ids": edge["source_osm_way_ids"],
        "node_path": node_path,
    }


def build_turn_relations(
    *,
    intersection_node_ids: set[str],
    directed_edges: list[dict[str, Any]],
    intersection_approaches: list[dict[str, Any]],
    turn_restrictions: list[dict[str, Any]],
    nodes: dict[str, dict[str, float]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """OSM restriction に基づく明示的な通行規制だけを作る。"""

    del nodes
    directed_edges_by_id = {edge["directed_edge_id"]: edge for edge in directed_edges}
    approaches_by_node: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    for approach in intersection_approaches:
        approaches_by_node[approach["topology_node_id"]][approach["approach_type"]].append(approach)

    restrictions_by_via_node: dict[str, list[dict[str, Any]]] = defaultdict(list)
    via_way_restriction_count = 0
    for restriction in turn_restrictions:
        if restriction["via_way_ids"]:
            via_way_restriction_count += 1
        for via_node_id in restriction["via_node_ids"]:
            restrictions_by_via_node[via_node_id].append(restriction)

    turn_relations: list[dict[str, Any]] = []
    denied_count = 0
    applied_relation_ids: set[str] = set()

    relation_index = 0
    for node_id in sorted(intersection_node_ids):
        incoming_approaches = approaches_by_node[node_id].get("incoming", [])
        outgoing_approaches = approaches_by_node[node_id].get("outgoing", [])
        node_restrictions = restrictions_by_via_node.get(node_id, [])

        for incoming in incoming_approaches:
            incoming_edge = directed_edges_by_id[incoming["directed_edge_id"]]
            applicable_restrictions = [
                restriction
                for restriction in node_restrictions
                if way_sets_overlap(incoming_edge["source_osm_way_ids"], restriction["from_way_ids"])
            ]
            only_restrictions = [
                restriction
                for restriction in applicable_restrictions
                if restriction["restriction"].startswith("only_")
            ]

            for outgoing in outgoing_approaches:
                outgoing_edge = directed_edges_by_id[outgoing["directed_edge_id"]]
                for restriction in applicable_restrictions:
                    restriction_type = restriction["restriction"]
                    if restriction_type.startswith("no_") and way_sets_overlap(
                        outgoing_edge["source_osm_way_ids"],
                        restriction["to_way_ids"],
                    ):
                        relation_index += 1
                        denied_count += 1
                        applied_relation_ids.add(restriction["relation_id"])
                        turn_relations.append(
                            build_turn_relation_record(
                                relation_index=relation_index,
                                node_id=node_id,
                                incoming_edge=incoming_edge,
                                outgoing_edge=outgoing_edge,
                                restriction=restriction,
                                is_allowed=False,
                            )
                        )

                for restriction in only_restrictions:
                    if way_sets_overlap(outgoing_edge["source_osm_way_ids"], restriction["to_way_ids"]):
                        continue
                    relation_index += 1
                    denied_count += 1
                    applied_relation_ids.add(restriction["relation_id"])
                    turn_relations.append(
                        build_turn_relation_record(
                            relation_index=relation_index,
                            node_id=node_id,
                            incoming_edge=incoming_edge,
                            outgoing_edge=outgoing_edge,
                            restriction=restriction,
                            is_allowed=False,
                        )
                    )

    summary = {
        "restriction_relation_count": len(turn_restrictions),
        "via_node_restriction_count": sum(1 for restriction in turn_restrictions if restriction["via_node_ids"]),
        "via_way_restriction_count": via_way_restriction_count,
        "applied_restriction_relation_count": len(applied_relation_ids),
        "turn_relation_count": len(turn_relations),
        "denied_turn_relation_count": denied_count,
        "restriction_source_counts": {"osm_turn_restriction": len(turn_relations)} if turn_relations else {},
    }
    return turn_relations, summary


def build_turn_relation_record(
    *,
    relation_index: int,
    node_id: str,
    incoming_edge: dict[str, Any],
    outgoing_edge: dict[str, Any],
    restriction: dict[str, Any],
    is_allowed: bool,
) -> dict[str, Any]:
    """1 件の明示的な turn restriction レコードを作る。"""

    return {
        "turn_relation_id": f"turn_relation_{relation_index:08d}",
        "intersection_id": f"intersection_{node_id}",
        "topology_node_id": node_id,
        "from_directed_edge_id": incoming_edge["directed_edge_id"],
        "to_directed_edge_id": outgoing_edge["directed_edge_id"],
        "is_allowed": is_allowed,
        "restriction_source": "osm_turn_restriction",
        "restriction_type": restriction["restriction"],
        "restriction_relation_id": restriction["relation_id"],
        "confidence": 1.0,
    }


def way_sets_overlap(left: list[str], right: list[str]) -> bool:
    """OSM way ID の重なりがあるか返す。"""

    return bool(set(left) & set(right))


def build_intersection_approaches_geojson(
    intersection_approaches: list[dict[str, Any]],
    nodes: dict[str, dict[str, float]],
) -> dict[str, Any]:
    """intersection approach の GeoJSON を作る。"""

    return feature_collection(
        [
            line_feature(
                coordinates_for_node_ids(approach["node_path"], nodes),
                {
                    key: value
                    for key, value in approach.items()
                    if key != "node_path"
                },
            )
            for approach in intersection_approaches
        ]
    )


def build_turn_relations_geojson(
    turn_relations: list[dict[str, Any]],
    nodes: dict[str, dict[str, float]],
) -> dict[str, Any]:
    """turn relation を交差点位置の Point GeoJSON として作る。"""

    features = []
    for turn_relation in turn_relations:
        node = nodes[turn_relation["topology_node_id"]]
        features.append(
            point_feature(
                [node["lon"], node["lat"]],
                turn_relation,
            )
        )
    return feature_collection(features)


def build_analysis_segments_geojson(
    analysis_segments: list[dict[str, Any]],
    nodes: dict[str, dict[str, float]],
) -> dict[str, Any]:
    """analysis segment の GeoJSON を作る。"""

    return feature_collection(
        [
            line_feature(
                coordinates_for_node_ids(segment["node_path"], nodes),
                {
                    "analysis_segment_id": segment["analysis_segment_id"],
                    "topology_edge_id": segment["topology_edge_id"],
                    "road_type": segment["road_type"],
                    "lane_count_total": segment["lane_count_total"],
                    "speed_limit_kmh": segment["speed_limit_kmh"],
                },
            )
            for segment in analysis_segments
        ]
    )


def build_summary(
    *,
    input_path: Path,
    raw_node_count: int,
    raw_way_count: int,
    selected_way_count: int,
    excluded_way_counts: Counter[str],
    used_node_count: int,
    nodes: dict[str, dict[str, float]],
    topology_node_types: dict[str, str],
    topology_node_cut_reasons: dict[str, list[str]],
    all_topology_node_count: int,
    intersection_node_ids: set[str],
    all_topology_edges: list[dict[str, Any]],
    canonical_candidate_edges: list[dict[str, Any]],
    topology_edges: list[dict[str, Any]],
    excluded_topology_edges: list[dict[str, Any]],
    directed_edges: list[dict[str, Any]],
    analysis_segments: list[dict[str, Any]],
    intersection_approaches: list[dict[str, Any]],
    turn_relations: list[dict[str, Any]],
    turn_restrictions: list[dict[str, Any]],
    turn_restriction_summary: dict[str, Any],
    incident_segments: dict[str, list[RoadSegment]],
) -> dict[str, Any]:
    """試作結果の要約を作る。"""

    degree_counter: Counter[int] = Counter()
    node_type_counter: Counter[str] = Counter(topology_node_types.values())
    cut_reason_counter: Counter[str] = Counter(
        reason
        for reasons in topology_node_cut_reasons.values()
        for reason in reasons
    )
    for node_id in topology_node_types:
        degree_counter[neighbor_count(node_id, incident_segments[node_id])] += 1

    edge_lengths = [
        {
            "topology_edge_id": edge["topology_edge_id"],
            "length_meter": round(edge_length_meter(edge, nodes), 2),
            "segment_count": len(edge["segment_ids"]),
        }
        for edge in topology_edges
    ]
    connected_components = topology_connected_components(canonical_candidate_edges)
    component_edge_counts = sorted((len(component) for component in connected_components), reverse=True)
    largest_component_ratio = 0.0
    if canonical_candidate_edges:
        largest_component_ratio = component_edge_counts[0] / len(canonical_candidate_edges)

    return {
        "input": str(input_path),
        "counts": {
            "raw_osm_node_count": raw_node_count,
            "raw_osm_way_count": raw_way_count,
            "selected_osm_way_count": selected_way_count,
            "used_osm_node_count": used_node_count,
            "all_topology_node_count": all_topology_node_count,
            "all_topology_edge_count": len(all_topology_edges),
            "canonical_candidate_edge_count": len(canonical_candidate_edges),
            "topology_node_count": len(topology_node_types),
            "intersection_count": len(intersection_node_ids),
            "topology_edge_count": len(topology_edges),
            "directed_edge_count": len(directed_edges),
            "analysis_segment_count": len(analysis_segments),
            "intersection_approach_count": len(intersection_approaches),
            "turn_relation_count": len(turn_relations),
            "turn_restriction_relation_count": len(turn_restrictions),
            "excluded_topology_edge_count": len(excluded_topology_edges),
        },
        "excluded_way_counts": dict(sorted(excluded_way_counts.items())),
        "topology_node_type_distribution": dict(sorted(node_type_counter.items())),
        "topology_node_cut_reason_distribution": dict(sorted(cut_reason_counter.items())),
        "topology_node_degree_distribution": {str(key): value for key, value in sorted(degree_counter.items())},
        "connectivity": {
            "component_count": len(connected_components),
            "largest_component_edge_ratio": round(largest_component_ratio, 4),
            "component_edge_counts_top10": component_edge_counts[:10],
            "canonical_component_edge_count": len(topology_edges),
            "excluded_component_edge_count": len(excluded_topology_edges),
        },
        "turn_restrictions": turn_restriction_summary,
        "edge_length_meter": {
            "min": round(min(item["length_meter"] for item in edge_lengths), 2) if edge_lengths else None,
            "max": round(max(item["length_meter"] for item in edge_lengths), 2) if edge_lengths else None,
            "avg": round(sum(item["length_meter"] for item in edge_lengths) / len(edge_lengths), 2)
            if edge_lengths
            else None,
            "shortest_top10": sorted(edge_lengths, key=lambda item: item["length_meter"])[:10],
            "longest_top10": sorted(edge_lengths, key=lambda item: item["length_meter"], reverse=True)[:10],
        },
        "notes": [
            "初期試作では analysis_segment は topology_edge と同粒度です。",
            "現行シミュレーション用 canonical network は motorway / motorway_link を除外した後の最大無向連結成分だけを採用しています。",
            "intersection は車が進路選択できる接続点だけを表し、dead_end と direction_change は topology_node として別管理しています。",
            "lane_count_total と speed_limit_kmh の変化点は attribute_boundary として topology_edge の切断点にしています。",
            "立体交差は OSM の共有 node 有無を前提に扱い、bridge/layer の詳細判定は後続課題です。",
        ],
    }


def topology_connected_components(topology_edges: list[dict[str, Any]]) -> list[set[str]]:
    """topology edge ID の連結成分を返す。"""

    edge_ids_by_node: dict[str, set[str]] = defaultdict(set)
    edges_by_id = {edge["topology_edge_id"]: edge for edge in topology_edges}
    for edge in topology_edges:
        edge_ids_by_node[edge["from_topology_node_id"]].add(edge["topology_edge_id"])
        edge_ids_by_node[edge["to_topology_node_id"]].add(edge["topology_edge_id"])

    components: list[set[str]] = []
    visited_edge_ids: set[str] = set()
    for edge_id in edges_by_id:
        if edge_id in visited_edge_ids:
            continue
        queue = deque([edge_id])
        component: set[str] = set()
        while queue:
            current_edge_id = queue.popleft()
            if current_edge_id in visited_edge_ids:
                continue
            visited_edge_ids.add(current_edge_id)
            component.add(current_edge_id)
            edge = edges_by_id[current_edge_id]
            for node_id in (edge["from_topology_node_id"], edge["to_topology_node_id"]):
                queue.extend(edge_ids_by_node[node_id] - visited_edge_ids)
        components.append(component)
    return components


def edge_length_meter(edge: dict[str, Any], nodes: dict[str, dict[str, float]]) -> float:
    """node path の近似長を返す。"""

    points = coordinates_for_node_ids(edge["node_path"], nodes)
    return sum(
        haversine_meter(start[1], start[0], end[1], end[0])
        for start, end in zip(points, points[1:])
    )


def write_geojson(path: Path, payload: dict[str, Any]) -> None:
    """GeoJSON を書く。"""

    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def feature_collection(features: list[dict[str, Any]]) -> dict[str, Any]:
    """FeatureCollection を返す。"""

    return {"type": "FeatureCollection", "features": features}


def line_feature(coordinates: list[list[float]], properties: dict[str, Any]) -> dict[str, Any]:
    """LineString Feature を返す。"""

    return {
        "type": "Feature",
        "geometry": {"type": "LineString", "coordinates": coordinates},
        "properties": properties,
    }


def point_feature(coordinates: list[float], properties: dict[str, Any]) -> dict[str, Any]:
    """Point Feature を返す。"""

    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": coordinates},
        "properties": properties,
    }


def coordinates_for_node_ids(node_ids: list[str], nodes: dict[str, dict[str, float]]) -> list[list[float]]:
    """node ID 列を GeoJSON 座標列へ変換する。"""

    return [[nodes[node_id]["lon"], nodes[node_id]["lat"]] for node_id in node_ids]


def neighbor_count(node_id: str, node_segments: list[RoadSegment]) -> int:
    """node の隣接 node 数を返す。"""

    return len(
        {
            segment.to_node_id if segment.from_node_id == node_id else segment.from_node_id
            for segment in node_segments
        }
    )


def allowed_directions(segment: RoadSegment) -> tuple[bool, bool]:
    """segment の正順・逆順通行可否を返す。"""

    if segment.oneway == "forward":
        return True, False
    if segment.oneway == "reverse":
        return False, True
    return True, True


def segment_allows_traversal(segment: RoadSegment, from_node_id: str, to_node_id: str) -> bool:
    """指定向きの通行が可能か返す。"""

    allows_forward, allows_reverse = allowed_directions(segment)
    if segment.from_node_id == from_node_id and segment.to_node_id == to_node_id:
        return allows_forward
    if segment.to_node_id == from_node_id and segment.from_node_id == to_node_id:
        return allows_reverse
    return False


def parse_oneway(tags: dict[str, str]) -> str:
    """OSM タグから方向種別を返す。"""

    oneway = tags.get("oneway")
    if oneway in {"yes", "1", "true"} or tags.get("junction") == "roundabout":
        return "forward"
    if oneway == "-1":
        return "reverse"
    return "both"


def parse_lane_count(raw_value: str | None) -> int | None:
    """lane 数タグを整数へ寄せる。"""

    if not raw_value:
        return None
    first_value = raw_value.split(";")[0].strip()
    digits = "".join(char for char in first_value if char.isdigit())
    if not digits:
        return None
    return max(1, int(digits))


def default_lane_count(highway: str) -> int:
    """lane 数がない場合の初期推定値を返す。"""

    if highway in LARGE_ROAD_TYPES:
        return 2
    return 1


def parse_speed_limit(raw_value: str | None, highway: str) -> int:
    """速度制限タグを初期値へ寄せる。"""

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


def bearing_between_nodes(from_node_id: str, to_node_id: str, nodes: dict[str, dict[str, float]]) -> float:
    """2 つの node 間の方位角を度で返す。"""

    from_node = nodes[from_node_id]
    to_node = nodes[to_node_id]
    lat1 = math.radians(from_node["lat"])
    lat2 = math.radians(to_node["lat"])
    delta_lon = math.radians(to_node["lon"] - from_node["lon"])
    y = math.sin(delta_lon) * math.cos(lat2)
    x = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(delta_lon)
    return (math.degrees(math.atan2(y, x)) + 360) % 360


def haversine_meter(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """2 点間距離の近似値を返す。"""

    earth_radius_meter = 6_371_000.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    a = math.sin(delta_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    return earth_radius_meter * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


if __name__ == "__main__":
    main()
