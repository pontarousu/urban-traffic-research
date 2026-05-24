#!/usr/bin/env python3
"""交差点の分岐確率を theta と softmax で扱う。"""

from __future__ import annotations

import json
import math
import random
from collections import defaultdict
from pathlib import Path
from typing import Any


BranchKey = tuple[str, str, str]


def build_outgoing_by_node(ways: list[dict[str, Any]]) -> dict[str, list[str]]:
    outgoing: dict[str, list[str]] = defaultdict(list)
    for way in ways:
        outgoing[way["from_node_id"]].append(way["id"])
    return dict(outgoing)


class BranchPolicy:
    """(node, incoming_way, outgoing_way) ごとの分岐パラメータを管理する。"""

    def __init__(
        self,
        outgoing_by_node: dict[str, list[str]],
        theta: dict[str, float] | None = None,
        min_branch_probability: float = 0.02,
        epsilon: float = 0.0,
    ) -> None:
        self.outgoing_by_node = outgoing_by_node
        self.theta: dict[str, float] = theta or {}
        self.min_branch_probability = min_branch_probability
        self.epsilon = max(0.0, min(1.0, epsilon))

    @staticmethod
    def key_to_string(node_id: str, incoming_way_id: str, outgoing_way_id: str) -> str:
        return f"{node_id}|{incoming_way_id}|{outgoing_way_id}"

    @staticmethod
    def string_to_key(value: str) -> BranchKey:
        node_id, incoming_way_id, outgoing_way_id = value.split("|", 2)
        return node_id, incoming_way_id, outgoing_way_id

    @classmethod
    def from_dataset(cls, dataset: dict[str, Any], min_branch_probability: float = 0.02, epsilon: float = 0.0) -> "BranchPolicy":
        outgoing_by_node = build_outgoing_by_node(dataset["graph"]["ways"])
        return cls(outgoing_by_node=outgoing_by_node, min_branch_probability=min_branch_probability, epsilon=epsilon)

    @classmethod
    def load(cls, path: Path, dataset: dict[str, Any]) -> "BranchPolicy":
        with path.open(encoding="utf-8") as file:
            data = json.load(file)
        outgoing_by_node = build_outgoing_by_node(dataset["graph"]["ways"])
        return cls(
            outgoing_by_node=outgoing_by_node,
            theta={str(key): float(value) for key, value in data.get("theta", {}).items()},
            min_branch_probability=float(data.get("min_branch_probability", 0.02)),
            epsilon=float(data.get("epsilon", 0.0)),
        )

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as file:
            json.dump(
                {
                    "schema_version": "0.1",
                    "min_branch_probability": self.min_branch_probability,
                    "epsilon": self.epsilon,
                    "theta": self.theta,
                },
                file,
                ensure_ascii=False,
                indent=2,
            )

    def probabilities(self, node_id: str, incoming_way_id: str) -> dict[str, float]:
        outgoing_way_ids = self.outgoing_by_node.get(node_id, [])
        if not outgoing_way_ids:
            return {}

        raw_values = [
            self.theta.get(self.key_to_string(node_id, incoming_way_id, outgoing_way_id), 0.0)
            for outgoing_way_id in outgoing_way_ids
        ]
        max_value = max(raw_values)
        exp_values = [math.exp(value - max_value) for value in raw_values]
        total = sum(exp_values) or 1.0
        probabilities = {
            outgoing_way_id: exp_value / total
            for outgoing_way_id, exp_value in zip(outgoing_way_ids, exp_values)
        }
        probabilities = self._apply_epsilon(probabilities)
        return self._apply_min_probability(probabilities)

    def choose(self, node_id: str, incoming_way_id: str, rng: random.Random) -> str | None:
        probabilities = self.probabilities(node_id, incoming_way_id)
        if not probabilities:
            return None
        threshold = rng.random()
        current = 0.0
        last_way_id = None
        for way_id, probability in probabilities.items():
            current += probability
            last_way_id = way_id
            if current >= threshold:
                return way_id
        return last_way_id

    def add_delta(self, node_id: str, incoming_way_id: str, outgoing_way_id: str, delta: float) -> None:
        key = self.key_to_string(node_id, incoming_way_id, outgoing_way_id)
        self.theta[key] = self.theta.get(key, 0.0) + delta

    def regularize(self, strength: float) -> None:
        if strength <= 0:
            return
        multiplier = max(0.0, 1.0 - strength)
        for key in list(self.theta.keys()):
            self.theta[key] *= multiplier

    def _apply_min_probability(self, probabilities: dict[str, float]) -> dict[str, float]:
        if not probabilities:
            return {}
        candidate_count = len(probabilities)
        minimum = min(self.min_branch_probability, 1.0 / candidate_count)
        remaining_mass = max(0.0, 1.0 - minimum * candidate_count)
        adjusted = {
            way_id: minimum + probability * remaining_mass
            for way_id, probability in probabilities.items()
        }
        total = sum(adjusted.values()) or 1.0
        return {way_id: value / total for way_id, value in adjusted.items()}

    def _apply_epsilon(self, probabilities: dict[str, float]) -> dict[str, float]:
        if not probabilities or self.epsilon <= 0:
            return probabilities
        uniform = 1.0 / len(probabilities)
        return {
            way_id: (1.0 - self.epsilon) * probability + self.epsilon * uniform
            for way_id, probability in probabilities.items()
        }
