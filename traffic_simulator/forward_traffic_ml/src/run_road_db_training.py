#!/usr/bin/env python3
"""road DB 順方向シミュレーションの trace-based theta 学習を実行する。"""

from __future__ import annotations

import argparse
import csv
import json
import time
from pathlib import Path
from typing import Any

from compare_road_db_counts import load_rows, summarize, write_rows, write_summary
from road_db_feedback_trainer import (
    compute_feedback,
    summarize_backtrace,
    write_backtrace_diagnostics,
    write_backtrace_summary,
)
from road_db_forward_simulator import run_road_db_simulation
from road_db_network_loader import (
    DEFAULT_OBSERVATION_ALIGNMENT_PATH,
    DEFAULT_SNAPSHOT_DIR,
    RoadDbNetwork,
    build_source_candidates,
    load_observation_matches,
)
from road_db_theta_policy import RoadDbThetaPolicy
from run_road_db_simulation import write_counts, write_traces


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "results/road_db_training"


def parse_args() -> argparse.Namespace:
    """コマンドライン引数を読む。"""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot-dir", type=Path, default=DEFAULT_SNAPSHOT_DIR)
    parser.add_argument("--observation-alignment", type=Path, default=DEFAULT_OBSERVATION_ALIGNMENT_PATH)
    parser.add_argument("--scenario", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--initial-theta", type=Path, default=None)
    parser.add_argument("--iterations", type=int, default=5)
    parser.add_argument("--base-seed", type=int, default=7000)
    parser.add_argument("--eval-seed", type=int, default=10007)
    parser.add_argument("--start-min", type=int, default=480)
    parser.add_argument("--duration-min", type=int, default=15)
    parser.add_argument("--time-step-sec", type=int, default=1)
    parser.add_argument("--generation-multiplier", type=float, default=0.03)
    parser.add_argument("--max-spawn-per-bin", type=int, default=300)
    parser.add_argument("--max-active-vehicles", type=int, default=1200)
    parser.add_argument("--max-vehicle-age-sec", type=int, default=1800)
    parser.add_argument("--epsilon", type=float, default=0.2)
    parser.add_argument("--no-outgoing-penalty", type=float, default=0.0)
    parser.add_argument("--spawn-timing", choices=["batch", "distributed"], default="distributed")
    parser.add_argument("--vehicle-packet-size", type=int, default=1)
    parser.add_argument("--source-mode", choices=["major", "matched_edges", "mixed", "observation_upstream", "mesh_uniform"], default="observation_upstream")
    parser.add_argument("--learning-rate", type=float, default=0.05)
    parser.add_argument("--error-floor", type=float, default=20.0)
    parser.add_argument("--backtrace-mode", choices=["branch_count", "distance"], default="branch_count")
    parser.add_argument("--max-backtrace-branches", type=int, default=5)
    parser.add_argument("--max-backtrace-distance-meter", type=float, default=1000.0)
    parser.add_argument("--backtrace-decay-meter", type=float, default=350.0)
    parser.add_argument("--min-backtrace-weight", type=float, default=0.05)
    parser.add_argument("--delta-clip", type=float, default=0.05)
    parser.add_argument("--theta-min", type=float, default=-3.0)
    parser.add_argument("--theta-max", type=float, default=3.0)
    parser.add_argument("--regularization", type=float, default=0.001)
    parser.add_argument("--skip-evaluation", action="store_true")
    parser.add_argument("--eval-interval", type=int, default=1)
    parser.add_argument("--upstream-min-distance-meter", type=float, default=80.0)
    parser.add_argument("--upstream-max-distance-meter", type=float, default=450.0)
    parser.add_argument("--upstream-max-candidates-per-observation", type=int, default=12)
    parser.add_argument("--mesh-size-meter", type=float, default=500.0)
    return parser.parse_args()


def main() -> None:
    """training loop を実行する。"""

    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    network = RoadDbNetwork.load(args.snapshot_dir)
    observations = load_observation_matches(
        alignment_path=args.observation_alignment,
        scenario_path=args.scenario,
        start_min=args.start_min,
        duration_min=args.duration_min,
        include_low_confidence=False,
    )
    source_candidates = build_source_candidates(
        network,
        observations,
        args.source_mode,
        upstream_min_distance_meter=args.upstream_min_distance_meter,
        upstream_max_distance_meter=args.upstream_max_distance_meter,
        upstream_max_candidates_per_observation=args.upstream_max_candidates_per_observation,
        mesh_size_meter=args.mesh_size_meter,
    )
    if args.initial_theta:
        policy = RoadDbThetaPolicy.load(args.initial_theta)
        policy.theta_min = args.theta_min
        policy.theta_max = args.theta_max
        policy.regularization = args.regularization
    else:
        policy = RoadDbThetaPolicy(
            theta_min=args.theta_min,
            theta_max=args.theta_max,
            regularization=args.regularization,
        )
    metric_rows: list[dict[str, Any]] = []
    all_backtrace_summary_rows: list[dict[str, Any]] = []

    for iteration in range(1, args.iterations + 1):
        iteration_started = time.perf_counter()
        seed = args.base_seed + iteration
        iteration_dir = args.output_dir / f"iteration_{iteration:03d}"
        iteration_dir.mkdir(parents=True, exist_ok=True)
        simulation_started = time.perf_counter()
        result = run_road_db_simulation(
            network=network,
            observations=observations,
            source_candidates=source_candidates,
            start_min=args.start_min,
            duration_min=args.duration_min,
            seed=seed,
            time_step_sec=args.time_step_sec,
            generation_multiplier=args.generation_multiplier,
            max_spawn_per_bin=args.max_spawn_per_bin,
            max_active_vehicles=args.max_active_vehicles,
            max_vehicle_age_sec=args.max_vehicle_age_sec,
            epsilon=args.epsilon,
            no_outgoing_penalty=args.no_outgoing_penalty,
            spawn_timing=args.spawn_timing,
            vehicle_packet_size=args.vehicle_packet_size,
            theta=policy.theta,
        )
        simulation_runtime_sec = time.perf_counter() - simulation_started

        counts_path = iteration_dir / "simulation_counts.csv"
        traces_path = iteration_dir / "vehicle_traces.json"
        comparison_path = iteration_dir / "comparison.csv"
        comparison_summary_path = iteration_dir / "comparison_summary.json"
        write_counts(
            observations=observations,
            counts=result["counts"],
            output_path=counts_path,
            start_min=args.start_min,
            duration_min=args.duration_min,
        )
        write_traces(result["vehicle_traces"], traces_path)
        comparison_rows = load_rows(counts_path)
        comparison_summary = summarize(comparison_rows)
        write_rows(comparison_rows, comparison_path)
        write_summary(comparison_summary, comparison_summary_path)

        feedback_started = time.perf_counter()
        feedback = compute_feedback(
            network=network,
            comparison_rows=comparison_rows,
            vehicle_traces=result["vehicle_traces"],
            iteration=iteration,
            learning_rate=args.learning_rate,
            error_floor=args.error_floor,
            max_backtrace_branches=args.max_backtrace_branches,
            backtrace_mode=args.backtrace_mode,
            max_backtrace_distance_meter=args.max_backtrace_distance_meter,
            backtrace_decay_meter=args.backtrace_decay_meter,
            min_backtrace_weight=args.min_backtrace_weight,
        )
        backtrace_path = iteration_dir / "backtrace_diagnostics.csv"
        write_backtrace_diagnostics(feedback["diagnostics"], backtrace_path)
        backtrace_summary_rows = summarize_backtrace(feedback["diagnostics"], iteration)
        all_backtrace_summary_rows.extend(backtrace_summary_rows)
        write_backtrace_summary(backtrace_summary_rows, iteration_dir / "backtrace_summary.csv")
        theta_update_summary = policy.apply_deltas(feedback["deltas"], args.delta_clip)
        feedback_runtime_sec = time.perf_counter() - feedback_started
        policy.save(iteration_dir / "theta.json")
        eval_summary: dict[str, Any] = {}
        should_run_evaluation = should_evaluate_iteration(
            iteration=iteration,
            total_iterations=args.iterations,
            skip_evaluation=args.skip_evaluation,
            eval_interval=args.eval_interval,
        )
        if should_run_evaluation:
            eval_summary = run_evaluation(
                network=network,
                observations=observations,
                source_candidates=source_candidates,
                theta=policy.theta,
                output_dir=iteration_dir / "evaluation",
                seed=args.eval_seed,
                start_min=args.start_min,
                duration_min=args.duration_min,
                time_step_sec=args.time_step_sec,
                generation_multiplier=args.generation_multiplier,
                max_spawn_per_bin=args.max_spawn_per_bin,
                max_active_vehicles=args.max_active_vehicles,
                max_vehicle_age_sec=args.max_vehicle_age_sec,
                epsilon=args.epsilon,
                no_outgoing_penalty=args.no_outgoing_penalty,
                spawn_timing=args.spawn_timing,
                vehicle_packet_size=args.vehicle_packet_size,
            )
        iteration_runtime_sec = time.perf_counter() - iteration_started

        metric_row = {
            "iteration": iteration,
            "seed": seed,
            "eval_seed": args.eval_seed if should_run_evaluation else None,
            "evaluated": should_run_evaluation,
            "iteration_runtime_sec": round(iteration_runtime_sec, 3),
            "simulation_runtime_sec": round(simulation_runtime_sec, 3),
            "feedback_runtime_sec": round(feedback_runtime_sec, 3),
            "no_outgoing_penalty": args.no_outgoing_penalty,
            "mae": comparison_summary["mae"],
            "rmse": comparison_summary["rmse"],
            "bias": comparison_summary["bias"],
            "observed_total": comparison_summary["observed_total"],
            "simulated_total": comparison_summary["simulated_total"],
            "simulated_total_ratio": (
                comparison_summary["simulated_total"] / comparison_summary["observed_total"]
                if comparison_summary["observed_total"]
                else None
            ),
            "hit_rows": comparison_summary["hit_rows"],
            "observed_rows": comparison_summary["observed_rows"],
            "correlation": comparison_summary["correlation"],
            "scheduled_spawn_count": result["summary"]["scheduled_spawn_count"],
            "spawned_count": result["summary"]["spawned_count"],
            "spawn_packet_count": result["summary"]["spawn_packet_count"],
            "dropped_spawn_count": result["summary"]["dropped_spawn_count"],
            "active_packet_avg": result["summary"]["active_packet_avg"],
            "active_packet_max": result["summary"]["active_packet_max"],
            "active_vehicle_weight_avg": result["summary"]["active_vehicle_weight_avg"],
            "active_vehicle_weight_max": result["summary"]["active_vehicle_weight_max"],
            "vehicle_packet_size": result["summary"]["vehicle_packet_size"],
            "observation_event_count": result["summary"]["observation_event_count"],
            "observation_event_weight_sum": result["summary"]["observation_event_weight_sum"],
            "branch_event_count": result["summary"]["branch_event_count"],
            "final_no_next_edge_weight": result["summary"]["final_status_weight_counts"].get("no_next_edge", 0),
            "final_no_next_edge_weight_ratio": ratio(
                result["summary"]["final_status_weight_counts"].get("no_next_edge", 0),
                result["summary"]["spawned_count"],
            ),
            **feedback["summary"],
            **theta_update_summary,
            **eval_summary,
        }
        metric_rows.append(metric_row)
        write_iteration_metrics(metric_rows, args.output_dir / "iteration_metrics.csv")
        print(json.dumps(metric_row, ensure_ascii=False, indent=2))

    policy.save(args.output_dir / "theta_final.json")
    write_backtrace_summary(all_backtrace_summary_rows, args.output_dir / "backtrace_summary.csv")
    write_training_config(args, args.output_dir / "training_config.json")
    print(f"training出力: {args.output_dir}")


def run_evaluation(
    *,
    network: RoadDbNetwork,
    observations: list[Any],
    source_candidates: list[dict[str, Any]],
    theta: dict[str, float],
    output_dir: Path,
    seed: int,
    start_min: int,
    duration_min: int,
    time_step_sec: int,
    generation_multiplier: float,
    max_spawn_per_bin: int,
    max_active_vehicles: int,
    max_vehicle_age_sec: int,
    epsilon: float,
    no_outgoing_penalty: float,
    spawn_timing: str,
    vehicle_packet_size: int,
) -> dict[str, Any]:
    """固定seedで評価runを実行し、summaryを返す。"""

    output_dir.mkdir(parents=True, exist_ok=True)
    eval_started = time.perf_counter()
    result = run_road_db_simulation(
        network=network,
        observations=observations,
        source_candidates=source_candidates,
        start_min=start_min,
        duration_min=duration_min,
        seed=seed,
        time_step_sec=time_step_sec,
        generation_multiplier=generation_multiplier,
        max_spawn_per_bin=max_spawn_per_bin,
        max_active_vehicles=max_active_vehicles,
        max_vehicle_age_sec=max_vehicle_age_sec,
        epsilon=epsilon,
        no_outgoing_penalty=no_outgoing_penalty,
        spawn_timing=spawn_timing,
        vehicle_packet_size=vehicle_packet_size,
        theta=theta,
    )
    counts_path = output_dir / "simulation_counts.csv"
    traces_path = output_dir / "vehicle_traces.json"
    comparison_path = output_dir / "comparison.csv"
    comparison_summary_path = output_dir / "comparison_summary.json"
    write_counts(
        observations=observations,
        counts=result["counts"],
        output_path=counts_path,
        start_min=start_min,
        duration_min=duration_min,
    )
    write_traces(result["vehicle_traces"], traces_path)
    comparison_rows = load_rows(counts_path)
    comparison_summary = summarize(comparison_rows)
    write_rows(comparison_rows, comparison_path)
    write_summary(comparison_summary, comparison_summary_path)
    eval_runtime_sec = time.perf_counter() - eval_started
    return {
        "eval_runtime_sec": round(eval_runtime_sec, 3),
        "eval_mae": comparison_summary["mae"],
        "eval_rmse": comparison_summary["rmse"],
        "eval_bias": comparison_summary["bias"],
        "eval_observed_total": comparison_summary["observed_total"],
        "eval_simulated_total": comparison_summary["simulated_total"],
        "eval_simulated_total_ratio": (
            comparison_summary["simulated_total"] / comparison_summary["observed_total"]
            if comparison_summary["observed_total"]
            else None
        ),
        "eval_hit_rows": comparison_summary["hit_rows"],
        "eval_observed_rows": comparison_summary["observed_rows"],
        "eval_correlation": comparison_summary["correlation"],
        "eval_scheduled_spawn_count": result["summary"]["scheduled_spawn_count"],
        "eval_spawned_count": result["summary"]["spawned_count"],
        "eval_spawn_packet_count": result["summary"]["spawn_packet_count"],
        "eval_dropped_spawn_count": result["summary"]["dropped_spawn_count"],
        "eval_active_packet_avg": result["summary"]["active_packet_avg"],
        "eval_active_packet_max": result["summary"]["active_packet_max"],
        "eval_active_vehicle_weight_avg": result["summary"]["active_vehicle_weight_avg"],
        "eval_active_vehicle_weight_max": result["summary"]["active_vehicle_weight_max"],
        "eval_observation_event_count": result["summary"]["observation_event_count"],
        "eval_observation_event_weight_sum": result["summary"]["observation_event_weight_sum"],
        "eval_branch_event_count": result["summary"]["branch_event_count"],
        "eval_final_no_next_edge_weight": result["summary"]["final_status_weight_counts"].get("no_next_edge", 0),
        "eval_final_no_next_edge_weight_ratio": ratio(
            result["summary"]["final_status_weight_counts"].get("no_next_edge", 0),
            result["summary"]["spawned_count"],
        ),
    }


def write_iteration_metrics(rows: list[dict[str, Any]], path: Path) -> None:
    """iteration metrics CSVを書く。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def should_evaluate_iteration(
    *,
    iteration: int,
    total_iterations: int,
    skip_evaluation: bool,
    eval_interval: int,
) -> bool:
    """指定 iteration で固定seed評価を実行するか返す。"""

    if skip_evaluation:
        return False
    if eval_interval <= 0:
        return iteration == total_iterations
    return iteration % eval_interval == 0 or iteration == total_iterations


def write_training_config(args: argparse.Namespace, path: Path) -> None:
    """training 設定をJSONへ保存する。"""

    with path.open("w", encoding="utf-8") as file:
        json.dump(vars(args), file, ensure_ascii=False, indent=2, default=str)


if __name__ == "__main__":
    main()
