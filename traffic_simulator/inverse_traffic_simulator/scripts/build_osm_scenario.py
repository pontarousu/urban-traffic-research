#!/usr/bin/env python3
"""OpenStreetMapの車道wayを、そのまま描画しやすいJSONへ変換する。"""

from __future__ import annotations

import argparse
import json
import xml.etree.ElementTree as ET
from pathlib import Path


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


def parse_args() -> argparse.Namespace:
    """コマンドライン引数を読む。"""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        default="inverse_traffic_simulator/data/tokyo_station_raw.osm",
        help="入力OSM XMLファイル",
    )
    parser.add_argument(
        "--output",
        default="inverse_traffic_simulator/data/tokyo_station_osm.json",
        help="出力JSONファイル",
    )
    parser.add_argument(
        "--name",
        default="東京駅北東側 OSM 車道描画",
        help="シナリオ名",
    )
    parser.add_argument(
        "--description",
        default="OpenStreetMapのnodeとwayを使って、車道だけをそのまま描画する試作です。lane数があるwayは平行線として描きます。",
        help="シナリオ説明",
    )
    return parser.parse_args()


def load_osm(path: Path) -> tuple[dict[str, dict[str, float]], list[dict[str, object]]]:
    """OSM XMLからnodeと対象wayを読む。"""

    root = ET.parse(path).getroot()
    nodes: dict[str, dict[str, float]] = {}

    for node in root.findall("node"):
        nodes[node.attrib["id"]] = {
            "lat": float(node.attrib["lat"]),
            "lon": float(node.attrib["lon"]),
        }

    ways: list[dict[str, object]] = []
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
        if len(node_refs) < 2:
            continue

        ways.append(
            {
                "id": way.attrib["id"],
                "nodeRefs": node_refs,
                "highway": highway,
                "name": tags.get("name:ja") or tags.get("name") or highway,
                "lanes": parse_lane_count(tags.get("lanes")),
                "oneway": tags.get("oneway") in {"yes", "1", "true"},
            }
        )

    return nodes, ways


def parse_lane_count(raw_value: str | None) -> int:
    """lane数タグを整数へ寄せる。"""

    if not raw_value:
        return 1

    first_value = raw_value.split(";")[0].strip()
    digits = "".join(char for char in first_value if char.isdigit())
    if not digits:
        return 1

    return max(1, int(digits))


def project_nodes(
    nodes: dict[str, dict[str, float]],
    used_node_ids: set[str],
    view_box: list[int],
) -> dict[str, dict[str, float]]:
    """緯度経度を描画座標へ変換する。"""

    selected = [nodes[node_id] for node_id in used_node_ids]
    lats = [point["lat"] for point in selected]
    lons = [point["lon"] for point in selected]
    min_lat = min(lats)
    max_lat = max(lats)
    min_lon = min(lons)
    max_lon = max(lons)

    left, top, width, height = view_box
    padding_x = width * 0.08
    padding_y = height * 0.12
    usable_width = width - padding_x * 2
    usable_height = height - padding_y * 2

    projected: dict[str, dict[str, float]] = {}
    for node_id in used_node_ids:
        point = nodes[node_id]
        lon_ratio = 0 if max_lon == min_lon else (point["lon"] - min_lon) / (max_lon - min_lon)
        lat_ratio = 0 if max_lat == min_lat else (point["lat"] - min_lat) / (max_lat - min_lat)
        projected[node_id] = {
            "x": round(left + padding_x + lon_ratio * usable_width, 1),
            "y": round(top + padding_y + (1 - lat_ratio) * usable_height, 1),
            "lat": point["lat"],
            "lon": point["lon"],
        }

    return projected


def build_map_labels(
    ways: list[dict[str, object]],
    projected_nodes: dict[str, dict[str, float]],
) -> list[dict[str, object]]:
    """道路名ラベルを少数だけ作る。"""

    labels = []
    seen_names: set[str] = set()

    for way in ways:
        if way["name"] in seen_names:
            continue
        if way["highway"] not in {"primary", "secondary", "tertiary"}:
            continue
        refs = way["nodeRefs"]
        mid_ref = refs[len(refs) // 2]
        point = projected_nodes[mid_ref]
        labels.append({"x": point["x"] + 8, "y": point["y"] - 10, "text": way["name"]})
        seen_names.add(way["name"])

    return labels


def main() -> None:
    """変換を実行する。"""

    args = parse_args()
    input_path = Path(args.input)
    output_path = Path(args.output)

    nodes, ways = load_osm(input_path)
    used_node_ids = {node_id for way in ways for node_id in way["nodeRefs"]}
    view_box = [0, 0, 900, 620]
    projected_nodes = project_nodes(nodes, used_node_ids, view_box)
    labels = build_map_labels(ways, projected_nodes)

    payload = {
        "meta": {
            "name": args.name,
            "description": args.description,
            "viewBox": view_box,
        },
        "roadGraph": {
            "nodes": projected_nodes,
            "ways": ways,
        },
        "mapLabels": labels,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {output_path}")
    print(f"nodes={len(projected_nodes)} ways={len(ways)}")


if __name__ == "__main__":
    main()
