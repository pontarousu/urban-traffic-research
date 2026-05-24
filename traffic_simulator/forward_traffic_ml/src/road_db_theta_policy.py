#!/usr/bin/env python3
"""road DB 分岐確率用 theta を管理する。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class RoadDbThetaPolicy:
    """(node, incoming_edge, outgoing_edge) ごとの分岐スコアを保持する。"""

    def __init__(
        self,
        theta: dict[str, float] | None = None,
        theta_min: float = -3.0,
        theta_max: float = 3.0,
        regularization: float = 0.001,
    ) -> None:
        self.theta = theta or {}
        self.theta_min = theta_min
        self.theta_max = theta_max
        self.regularization = regularization

    @classmethod
    def load(cls, path: Path) -> "RoadDbThetaPolicy":
        """JSONから theta を読む。"""

        with path.open(encoding="utf-8") as file:
            data = json.load(file)
        return cls(
            theta={str(key): float(value) for key, value in data.get("theta", {}).items()},
            theta_min=float(data.get("theta_min", -3.0)),
            theta_max=float(data.get("theta_max", 3.0)),
            regularization=float(data.get("regularization", 0.001)),
        )

    def save(self, path: Path) -> None:
        """theta をJSONへ保存する。"""

        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as file:
            json.dump(
                {
                    "schema_version": "road_db_theta.v1",
                    "theta_min": self.theta_min,
                    "theta_max": self.theta_max,
                    "regularization": self.regularization,
                    "theta": self.theta,
                    "stats": self.stats(),
                },
                file,
                ensure_ascii=False,
                indent=2,
            )

    def apply_deltas(self, deltas: dict[str, float], delta_clip: float) -> dict[str, Any]:
        """集計済み delta を適用し、theta を正則化・clamp する。"""

        clipped_delta_count = 0
        for key, delta in deltas.items():
            clipped = max(-delta_clip, min(delta_clip, delta))
            if clipped != delta:
                clipped_delta_count += 1
            self.theta[key] = self.theta.get(key, 0.0) + clipped

        if self.regularization > 0:
            multiplier = max(0.0, 1.0 - self.regularization)
            for key in list(self.theta.keys()):
                self.theta[key] *= multiplier

        clamped_theta_count = 0
        for key, value in list(self.theta.items()):
            clamped = max(self.theta_min, min(self.theta_max, value))
            if clamped != value:
                clamped_theta_count += 1
            if abs(clamped) < 1e-12:
                self.theta.pop(key, None)
            else:
                self.theta[key] = clamped

        return {
            "theta_updated_count": len(deltas),
            "clipped_delta_count": clipped_delta_count,
            "clamped_theta_count": clamped_theta_count,
            **self.stats(),
        }

    def stats(self) -> dict[str, Any]:
        """theta の状態を返す。"""

        if not self.theta:
            return {
                "theta_nonzero_count": 0,
                "theta_min": 0.0,
                "theta_max": 0.0,
                "theta_abs_mean": 0.0,
            }
        values = list(self.theta.values())
        return {
            "theta_nonzero_count": len(values),
            "theta_min": min(values),
            "theta_max": max(values),
            "theta_abs_mean": sum(abs(value) for value in values) / len(values),
        }
