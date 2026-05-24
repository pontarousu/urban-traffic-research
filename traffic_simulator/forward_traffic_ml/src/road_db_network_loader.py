#!/usr/bin/env python3
"""道路DBスナップショットを順方向シミュレーション用に読む。"""

from __future__ import annotations

import json
import math
import random
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SNAPSHOT_DIR = PROJECT_ROOT / "data/road_db_snapshots/road_db_prototype_tokyo_core_small_runtime_current"
DEFAULT_OBSERVATION_ALIGNMENT_PATH = PROJECT_ROOT / "viewer/data/observation_alignment.json"

MAJOR_ROAD_TYPES = {
    "motorway",
    "trunk",
    "primary",
    "secondary",
    "tertiary",
    "motorway_link",
    "trunk_link",
    "primary_link",
    "secondary_link",
    "tertiary_link",
}

ROAD_TYPE_WEIGHTS = {
    "motorway": 5.0,
    "trunk": 4.5,
    "primary": 3.6,
    "secondary": 2.6,
    "tertiary": 1.8,
    "motorway_link": 2.6,
    "trunk_link": 2.4,
    "primary_link": 2.0,
    "secondary_link": 1.5,
    "tertiary_link": 1.2,
}


@dataclass(frozen=True)
class ObservationMatch:
    """観測点と directed edge の対応を持つ。"""

    observation_id: str
    point_number: str | None
    point_name: str | None
    directed_edge_id: str
    topology_edge_id: str | None
    position_ratio: float
    position_meter: float
    observed_volume_5min: dict[int, int]
    match_method: str
    match_confidence: str
    warning_flags: tuple[str, ...]


class RoadDbNetwork:
    """シミュレーションに必要な道路DBの接続情報を持つ。"""

    def __init__(self, core: dict[str, Any]) -> None:
        self.core = core
        self.directed_edges: dict[str, dict[str, Any]] = {
            edge["directed_edge_id"]: edge
            for edge in core["graph"]["directed_edges"]
        }
        self.nodes: dict[str, dict[str, Any]] = {
            node["topology_node_id"]: node
            for node in core["graph"]["topology_nodes"]
        }
        self.incoming_edges_by_node: dict[str, list[str]] = defaultdict(list)
        for edge in self.directed_edges.values():
            self.incoming_edges_by_node[edge["to_node_id"]].append(edge["directed_edge_id"])
        self.branch_options_by_incoming: dict[str, list[dict[str, Any]]] = {}
        for item in core.get("branch_options", []):
            incoming_edge_id = item["incoming_directed_edge_id"]
            options = [
                option
                for option in item.get("outgoing_options", [])
                if option.get("outgoing_directed_edge_id") in self.directed_edges
            ]
            self.branch_options_by_incoming[incoming_edge_id] = options

    @classmethod
    def load(cls, snapshot_dir: Path = DEFAULT_SNAPSHOT_DIR) -> "RoadDbNetwork":
        """network_core.json を読む。"""

        with (snapshot_dir / "network_core.json").open(encoding="utf-8") as file:
            return cls(json.load(file))

    def edge_length(self, directed_edge_id: str) -> float:
        """edge 長を meter で返す。"""

        edge = self.directed_edges[directed_edge_id]
        return max(1.0, float(edge.get("length_meter") or 1.0))

    def edge_speed_mps(self, directed_edge_id: str) -> float:
        """edge の暫定走行速度を m/s で返す。"""

        edge = self.directed_edges[directed_edge_id]
        speed_kmh = float(edge.get("speed_limit_kmh") or 30.0)
        return max(3.0, speed_kmh * 1000.0 / 3600.0)

    def outgoing_options(self, incoming_edge_id: str) -> list[dict[str, Any]]:
        """incoming edge に対する分岐候補を返す。"""

        return self.branch_options_by_incoming.get(incoming_edge_id, [])

    def choose_next_edge(
        self,
        incoming_edge_id: str,
        theta: dict[str, float],
        rng: random.Random,
        epsilon: float,
    ) -> tuple[str | None, float | None]:
        """softmax + epsilon で次の directed edge を選ぶ。"""

        options = self.outgoing_options(incoming_edge_id)
        if not options:
            return None, None

        incoming = self.directed_edges[incoming_edge_id]
        node_id = incoming["to_node_id"]
        scores = [
            theta.get(branch_key(node_id, incoming_edge_id, option["outgoing_directed_edge_id"]), 0.0)
            for option in options
        ]
        max_score = max(scores)
        exp_values = [math.exp(score - max_score) for score in scores]
        total = sum(exp_values) or 1.0
        probabilities = [value / total for value in exp_values]
        if epsilon > 0:
            uniform = 1.0 / len(probabilities)
            probabilities = [
                (1.0 - epsilon) * probability + epsilon * uniform
                for probability in probabilities
            ]

        threshold = rng.random()
        current = 0.0
        for option, probability in zip(options, probabilities):
            current += probability
            if current >= threshold:
                return option["outgoing_directed_edge_id"], probability
        return options[-1]["outgoing_directed_edge_id"], probabilities[-1]


def branch_key(node_id: str, incoming_edge_id: str, outgoing_edge_id: str) -> str:
    """分岐 theta 用キーを作る。"""

    return f"{node_id}|{incoming_edge_id}|{outgoing_edge_id}"


def load_json(path: Path) -> Any:
    """JSON を読む。"""

    with path.open(encoding="utf-8") as file:
        return json.load(file)


def load_observation_matches(
    *,
    alignment_path: Path = DEFAULT_OBSERVATION_ALIGNMENT_PATH,
    scenario_path: Path | None = None,
    start_min: int,
    duration_min: int,
    include_low_confidence: bool = False,
) -> list[ObservationMatch]:
    """観測点対応と元シナリオの観測時系列を結合する。"""

    alignment = load_json(alignment_path)
    if scenario_path is None:
        source = alignment.get("source", {})
        scenario_path = Path(source["scenario"])
    scenario = load_json(scenario_path)
    traffic_by_id = {
        obs["id"]: {
            int(record["time_min"]): int(record["volume_5min"])
            for record in obs.get("traffic_volume", [])
        }
        for obs in scenario.get("observation_points", [])
    }
    end_min = start_min + duration_min
    matches: list[ObservationMatch] = []
    for obs in alignment.get("observations", []):
        link = obs.get("matched_link")
        if not link:
            continue
        confidence = obs.get("match_confidence", "low")
        if confidence == "low" and not include_low_confidence:
            continue
        edge_length = max(1.0, float(link.get("length_meter") or 1.0))
        position_ratio = min(1.0, max(0.0, float(link.get("position_ratio") or 0.5)))
        observed_volume_5min = {
            time_min: int(traffic_by_id.get(obs["id"], {}).get(time_min, 0))
            for time_min in range(start_min, end_min, 5)
        }
        matches.append(
            ObservationMatch(
                observation_id=obs["id"],
                point_number=obs.get("point_number"),
                point_name=obs.get("point_name"),
                directed_edge_id=link["directed_edge_id"],
                topology_edge_id=link.get("topology_edge_id"),
                position_ratio=position_ratio,
                position_meter=edge_length * position_ratio,
                observed_volume_5min=observed_volume_5min,
                match_method=obs.get("match_method", "unknown"),
                match_confidence=confidence,
                warning_flags=tuple(obs.get("warning_flags", [])),
            )
        )
    return matches


def build_observations_by_edge(matches: list[ObservationMatch]) -> dict[str, list[ObservationMatch]]:
    """edge ごとに観測点を位置順でまとめる。"""

    output: dict[str, list[ObservationMatch]] = defaultdict(list)
    for match in matches:
        output[match.directed_edge_id].append(match)
    for values in output.values():
        values.sort(key=lambda item: item.position_meter)
    return dict(output)


def build_source_candidates(
    network: RoadDbNetwork,
    observations: list[ObservationMatch],
    source_mode: str,
    min_length_meter: float = 20.0,
    upstream_min_distance_meter: float = 80.0,
    upstream_max_distance_meter: float = 450.0,
    upstream_max_candidates_per_observation: int = 12,
) -> list[dict[str, Any]]:
    """車両発生候補 edge を作る。"""

    if source_mode == "matched_edges":
        observed_totals = {
            obs.directed_edge_id: sum(obs.observed_volume_5min.values())
            for obs in observations
        }
        return [
            {
                "directed_edge_id": edge_id,
                "weight": max(1.0, total),
                "source_category": "matched_edge_debug",
            }
            for edge_id, total in observed_totals.items()
            if edge_id in network.directed_edges and network.outgoing_options(edge_id)
        ]

    major_candidates = []
    for edge_id, edge in network.directed_edges.items():
        road_type = edge.get("road_type")
        length = float(edge.get("length_meter") or 0.0)
        if road_type not in MAJOR_ROAD_TYPES:
            continue
        if length < min_length_meter:
            continue
        if not network.outgoing_options(edge_id):
            continue
        lane_count = max(1.0, float(edge.get("lane_count_total") or 1.0))
        weight = length * lane_count * ROAD_TYPE_WEIGHTS.get(road_type, 1.0)
        major_candidates.append(
            {
                "directed_edge_id": edge_id,
                "weight": weight,
                "source_category": "major_rule",
            }
        )

    if source_mode == "major":
        return major_candidates
    if source_mode == "observation_upstream":
        return build_observation_upstream_source_candidates(
            network=network,
            observations=observations,
            min_length_meter=min_length_meter,
            upstream_min_distance_meter=upstream_min_distance_meter,
            upstream_max_distance_meter=upstream_max_distance_meter,
            max_candidates_per_observation=upstream_max_candidates_per_observation,
        )
    if source_mode != "mixed":
        raise ValueError(f"未知の source_mode です: {source_mode}")

    matched_candidates = build_source_candidates(network, observations, "matched_edges", min_length_meter)
    for item in matched_candidates:
        item["weight"] *= 0.15
        item["source_category"] = "matched_edge_debug_mixed"
    return major_candidates + matched_candidates


def build_observation_upstream_source_candidates(
    *,
    network: RoadDbNetwork,
    observations: list[ObservationMatch],
    min_length_meter: float,
    upstream_min_distance_meter: float,
    upstream_max_distance_meter: float,
    max_candidates_per_observation: int,
) -> list[dict[str, Any]]:
    """観測点から一定距離上流にある発生候補を作る。"""

    combined_weights: dict[str, dict[str, Any]] = {}
    for observation in observations:
        observed_total = sum(observation.observed_volume_5min.values())
        if observed_total <= 0:
            continue
        candidates = find_upstream_edges_for_observation(
            network=network,
            observation=observation,
            min_distance_meter=upstream_min_distance_meter,
            max_distance_meter=upstream_max_distance_meter,
            min_length_meter=min_length_meter,
            max_candidates=max_candidates_per_observation,
        )
        for candidate in candidates:
            edge_id = candidate["directed_edge_id"]
            distance = candidate["upstream_distance_meter"]
            distance_weight = upstream_distance_weight(
                distance,
                upstream_min_distance_meter,
                upstream_max_distance_meter,
            )
            edge = network.directed_edges[edge_id]
            road_type_weight = ROAD_TYPE_WEIGHTS.get(edge.get("road_type"), 0.6)
            contribution = observed_total * distance_weight * road_type_weight
            item = combined_weights.setdefault(
                edge_id,
                {
                    "directed_edge_id": edge_id,
                    "weight": 0.0,
                    "source_category": "observation_upstream",
                    "linked_observation_count": 0,
                    "min_upstream_distance_meter": distance,
                    "road_type": edge.get("road_type"),
                },
            )
            item["weight"] += contribution
            item["linked_observation_count"] += 1
            item["min_upstream_distance_meter"] = min(item["min_upstream_distance_meter"], distance)

    return [
        {
            **item,
            "weight": max(1.0, round(item["weight"], 4)),
            "min_upstream_distance_meter": round(item["min_upstream_distance_meter"], 2),
        }
        for item in combined_weights.values()
    ]


def find_upstream_edges_for_observation(
    *,
    network: RoadDbNetwork,
    observation: ObservationMatch,
    min_distance_meter: float,
    max_distance_meter: float,
    min_length_meter: float,
    max_candidates: int,
) -> list[dict[str, Any]]:
    """1観測点に対して距離ベースの上流 edge 候補を返す。"""

    start_edge_id = observation.directed_edge_id
    distance_to_start = max(0.0, observation.position_meter)
    stack: list[tuple[str, float]] = [(start_edge_id, distance_to_start)]
    best_distance_by_edge: dict[str, float] = {}
    candidates: list[dict[str, Any]] = []

    while stack:
        edge_id, distance_to_observation = stack.pop()
        known_distance = best_distance_by_edge.get(edge_id)
        if known_distance is not None and known_distance <= distance_to_observation:
            continue
        best_distance_by_edge[edge_id] = distance_to_observation
        if distance_to_observation > max_distance_meter:
            continue

        edge = network.directed_edges[edge_id]
        if (
            distance_to_observation >= min_distance_meter
            and is_valid_upstream_source_edge(network, edge_id, min_length_meter)
        ):
            candidates.append(
                {
                    "directed_edge_id": edge_id,
                    "upstream_distance_meter": distance_to_observation,
                    "road_type": edge.get("road_type"),
                    "length_meter": edge.get("length_meter"),
                }
            )

        from_node_id = edge["from_node_id"]
        for previous_edge_id in network.incoming_edges_by_node.get(from_node_id, []):
            previous_length = network.edge_length(previous_edge_id)
            next_distance = distance_to_observation + previous_length
            if next_distance <= max_distance_meter:
                stack.append((previous_edge_id, next_distance))

    candidates.sort(
        key=lambda item: (
            abs(item["upstream_distance_meter"] - preferred_upstream_distance(min_distance_meter, max_distance_meter)),
            item["upstream_distance_meter"],
        )
    )
    return candidates[:max_candidates]


def is_valid_upstream_source_edge(network: RoadDbNetwork, edge_id: str, min_length_meter: float) -> bool:
    """発生源として使える上流 edge か判定する。"""

    edge = network.directed_edges[edge_id]
    if not network.outgoing_options(edge_id):
        return False
    if float(edge.get("length_meter") or 0.0) < min_length_meter:
        return False
    road_type = edge.get("road_type")
    if road_type in {"service", "living_street"}:
        return False
    return True


def preferred_upstream_distance(min_distance_meter: float, max_distance_meter: float) -> float:
    """上流発生の目標距離を返す。"""

    return min_distance_meter + (max_distance_meter - min_distance_meter) * 0.35


def upstream_distance_weight(distance_meter: float, min_distance_meter: float, max_distance_meter: float) -> float:
    """上流距離に応じた発生重みを返す。"""

    preferred = preferred_upstream_distance(min_distance_meter, max_distance_meter)
    span = max(1.0, max_distance_meter - min_distance_meter)
    normalized_distance = abs(distance_meter - preferred) / span
    return max(0.15, 1.0 - normalized_distance)
