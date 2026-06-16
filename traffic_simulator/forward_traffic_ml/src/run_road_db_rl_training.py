#!/usr/bin/env python3
"""道路DB順方向シミュレーションの最小RL学習を実行する。"""

from __future__ import annotations

import argparse
import csv
import json
import math
import time
from pathlib import Path
from typing import Any

from compare_road_db_counts import load_rows, summarize, write_rows, write_summary
from road_db_forward_simulator import run_road_db_simulation
from road_db_network_loader import (
    DEFAULT_OBSERVATION_ALIGNMENT_PATH,
    DEFAULT_SNAPSHOT_DIR,
    ObservationMatch,
    RoadDbNetwork,
    build_source_candidates,
    load_json,
    load_observation_matches,
)
from road_db_rl_trainer import compute_rl_feedback, write_rl_diagnostics
from road_db_theta_policy import RoadDbThetaPolicy
from run_road_db_simulation import write_counts, write_traces
from run_road_db_training import should_evaluate_iteration, write_iteration_metrics, write_training_config


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "results/road_db_rl_minimal_mesh_uniform_500_g150_packet5_iter20"


def parse_args() -> argparse.Namespace:
    """コマンドライン引数を読む。"""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot-dir", type=Path, default=DEFAULT_SNAPSHOT_DIR)
    parser.add_argument("--observation-alignment", type=Path, default=DEFAULT_OBSERVATION_ALIGNMENT_PATH)
    parser.add_argument("--scenario", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--initial-theta", type=Path, default=None)
    parser.add_argument("--iterations", type=int, default=20)
    parser.add_argument("--base-seed", type=int, default=12000)
    parser.add_argument("--eval-seed", type=int, default=19601)
    parser.add_argument("--start-min", type=int, default=480)
    parser.add_argument("--duration-min", type=int, default=40)
    parser.add_argument("--warmup-min", type=int, default=10)
    parser.add_argument("--time-step-sec", type=int, default=1)
    parser.add_argument("--generation-multiplier", type=float, default=1.5)
    parser.add_argument("--max-spawn-per-bin", type=int, default=100000)
    parser.add_argument("--max-active-vehicles", type=int, default=15000)
    parser.add_argument("--max-vehicle-age-sec", type=int, default=2400)
    parser.add_argument("--epsilon", type=float, default=0.2)
    parser.add_argument("--no-outgoing-penalty", type=float, default=0.0)
    parser.add_argument("--spawn-timing", choices=["batch", "distributed"], default="distributed")
    parser.add_argument("--vehicle-packet-size", type=int, default=5)
    parser.add_argument("--source-mode", choices=["major", "matched_edges", "mixed", "observation_upstream", "mesh_uniform"], default="mesh_uniform")
    parser.add_argument("--learning-rate", type=float, default=0.005)
    parser.add_argument("--backtrace-mode", choices=["branch_count", "distance"], default="distance")
    parser.add_argument("--max-backtrace-branches", type=int, default=5)
    parser.add_argument("--max-backtrace-distance-meter", type=float, default=1000.0)
    parser.add_argument("--backtrace-decay-meter", type=float, default=350.0)
    parser.add_argument("--min-backtrace-weight", type=float, default=0.05)
    parser.add_argument("--delta-clip", type=float, default=0.03)
    parser.add_argument("--theta-min", type=float, default=-3.0)
    parser.add_argument("--theta-max", type=float, default=3.0)
    parser.add_argument("--regularization", type=float, default=0.001)
    parser.add_argument("--skip-evaluation", action="store_true")
    parser.add_argument("--eval-interval", type=int, default=5)
    parser.add_argument("--upstream-min-distance-meter", type=float, default=80.0)
    parser.add_argument("--upstream-max-distance-meter", type=float, default=450.0)
    parser.add_argument("--upstream-max-candidates-per-observation", type=int, default=12)
    parser.add_argument("--mesh-size-meter", type=float, default=500.0)
    parser.add_argument("--boundary-exclude-meter", type=float, default=1000.0)
    parser.add_argument("--write-vehicle-traces", action="store_true")
    parser.add_argument("--write-rl-diagnostics", action="store_true")
    parser.add_argument("--rl-diagnostics-limit", type=int, default=5000)
    parser.add_argument("--baseline-mode", choices=["global", "observation", "mixed", "mixed_fixed", "mixed_auto"], default="global")
    parser.add_argument("--mixed-baseline-global-weight", type=float, default=0.3)
    parser.add_argument("--baseline-lambda", type=float, default=0.25)
    parser.add_argument("--baseline-lambda-initial", type=float, default=0.0)
    parser.add_argument("--baseline-lambda-smoothing", type=float, default=0.2)
    parser.add_argument("--baseline-lambda-max-step", type=float, default=0.1)
    parser.add_argument("--baseline-min-samples", type=int, default=100)
    return parser.parse_args()


def main() -> None:
    """最小RL training loop を実行する。"""

    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    network = RoadDbNetwork.load(args.snapshot_dir)
    observations_all = load_observation_matches(
        alignment_path=args.observation_alignment,
        scenario_path=args.scenario,
        start_min=args.start_min,
        duration_min=args.duration_min,
        include_low_confidence=False,
    )
    boundary_filter = filter_observations_by_boundary(
        network=network,
        alignment_path=args.observation_alignment,
        observations=observations_all,
        threshold_meter=args.boundary_exclude_meter,
    )
    observations = boundary_filter["included"]
    write_boundary_filter_summary(boundary_filter, args.output_dir / "boundary_filter_summary.json")
    write_excluded_observations(boundary_filter["excluded"], args.output_dir / "excluded_boundary_observations.csv")

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
    reward_start_min = args.start_min + args.warmup_min
    current_mixed_lambda = min(1.0, max(0.0, args.baseline_lambda_initial))
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

        comparison_rows, comparison_summary = write_run_outputs(
            observations=observations,
            result=result,
            output_dir=iteration_dir,
            start_min=args.start_min,
            duration_min=args.duration_min,
            write_vehicle_traces=args.write_vehicle_traces,
        )
        warmup_summary = summarize_after_min(comparison_rows, reward_start_min)

        feedback_started = time.perf_counter()
        mixed_lambda_for_iteration = baseline_lambda_for_iteration(
            baseline_mode=args.baseline_mode,
            fixed_lambda=args.baseline_lambda,
            current_auto_lambda=current_mixed_lambda,
        )
        feedback = compute_rl_feedback(
            network=network,
            comparison_rows=comparison_rows,
            vehicle_traces=result["vehicle_traces"],
            theta=policy.theta,
            iteration=iteration,
            reward_start_min=reward_start_min,
            learning_rate=args.learning_rate,
            epsilon=args.epsilon,
            backtrace_mode=args.backtrace_mode,
            max_backtrace_branches=args.max_backtrace_branches,
            max_backtrace_distance_meter=args.max_backtrace_distance_meter,
            backtrace_decay_meter=args.backtrace_decay_meter,
            min_backtrace_weight=args.min_backtrace_weight,
            no_outgoing_penalty=args.no_outgoing_penalty,
            diagnostics_limit=args.rl_diagnostics_limit if args.write_rl_diagnostics else 0,
            baseline_mode=args.baseline_mode,
            mixed_baseline_global_weight=args.mixed_baseline_global_weight,
            mixed_baseline_lambda=mixed_lambda_for_iteration,
            mixed_baseline_lambda_smoothing=args.baseline_lambda_smoothing,
            mixed_baseline_lambda_max_step=args.baseline_lambda_max_step,
            mixed_baseline_min_samples=args.baseline_min_samples,
        )
        if args.write_rl_diagnostics:
            write_rl_diagnostics(feedback["diagnostics"], iteration_dir / "rl_diagnostics.csv")
        theta_update_summary = policy.apply_deltas(feedback["deltas"], args.delta_clip)
        feedback_runtime_sec = time.perf_counter() - feedback_started
        policy.save(iteration_dir / "theta.json")

        should_run_evaluation = should_evaluate_iteration(
            iteration=iteration,
            total_iterations=args.iterations,
            skip_evaluation=args.skip_evaluation,
            eval_interval=args.eval_interval,
        )
        eval_summary: dict[str, Any] = {}
        if should_run_evaluation:
            eval_summary = run_rl_evaluation(
                network=network,
                observations=observations,
                source_candidates=source_candidates,
                theta=policy.theta,
                output_dir=iteration_dir / "evaluation",
                seed=args.eval_seed,
                start_min=args.start_min,
                duration_min=args.duration_min,
                reward_start_min=reward_start_min,
                time_step_sec=args.time_step_sec,
                generation_multiplier=args.generation_multiplier,
                max_spawn_per_bin=args.max_spawn_per_bin,
                max_active_vehicles=args.max_active_vehicles,
                max_vehicle_age_sec=args.max_vehicle_age_sec,
                epsilon=args.epsilon,
                no_outgoing_penalty=args.no_outgoing_penalty,
                spawn_timing=args.spawn_timing,
                vehicle_packet_size=args.vehicle_packet_size,
                write_vehicle_traces=args.write_vehicle_traces,
            )

        metric_row = {
            "iteration": iteration,
            "seed": seed,
            "eval_seed": args.eval_seed if should_run_evaluation else None,
            "evaluated": should_run_evaluation,
            "iteration_runtime_sec": round(time.perf_counter() - iteration_started, 3),
            "simulation_runtime_sec": round(simulation_runtime_sec, 3),
            "feedback_runtime_sec": round(feedback_runtime_sec, 3),
            "observation_count_before_boundary_filter": len(observations_all),
            "observation_count": len(observations),
            "boundary_excluded_count": len(boundary_filter["excluded"]),
            "baseline_mode": args.baseline_mode,
            "mixed_baseline_global_weight": args.mixed_baseline_global_weight,
            "baseline_lambda": mixed_lambda_for_iteration,
            "baseline_lambda_initial": args.baseline_lambda_initial,
            "baseline_lambda_smoothing": args.baseline_lambda_smoothing,
            "baseline_lambda_max_step": args.baseline_lambda_max_step,
            "baseline_min_samples": args.baseline_min_samples,
            "no_outgoing_penalty": args.no_outgoing_penalty,
            "mae": comparison_summary["mae"],
            "rmse": comparison_summary["rmse"],
            "bias": comparison_summary["bias"],
            "observed_total": comparison_summary["observed_total"],
            "simulated_total": comparison_summary["simulated_total"],
            "simulated_total_ratio": ratio(comparison_summary["simulated_total"], comparison_summary["observed_total"]),
            "warmup_mae": warmup_summary["mae"],
            "warmup_rmse": warmup_summary["rmse"],
            "warmup_bias": warmup_summary["bias"],
            "warmup_observed_total": warmup_summary["observed_total"],
            "warmup_simulated_total": warmup_summary["simulated_total"],
            "warmup_simulated_total_ratio": ratio(warmup_summary["simulated_total"], warmup_summary["observed_total"]),
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
        if args.baseline_mode == "mixed_auto":
            current_mixed_lambda = float(feedback["summary"]["rl_mixed_baseline_lambda_next"])

    policy.save(args.output_dir / "theta_final.json")
    write_training_config(args, args.output_dir / "training_config.json")
    print(f"RL training出力: {args.output_dir}")


def write_run_outputs(
    *,
    observations: list[ObservationMatch],
    result: dict[str, Any],
    output_dir: Path,
    start_min: int,
    duration_min: int,
    write_vehicle_traces: bool,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """シミュレーション結果・比較結果を書き、比較行とサマリを返す。"""

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
    if write_vehicle_traces:
        write_traces(result["vehicle_traces"], traces_path)
    comparison_rows = load_rows(counts_path)
    comparison_summary = summarize(comparison_rows)
    write_rows(comparison_rows, comparison_path)
    write_summary(comparison_summary, comparison_summary_path)
    return comparison_rows, comparison_summary


def run_rl_evaluation(
    *,
    network: RoadDbNetwork,
    observations: list[ObservationMatch],
    source_candidates: list[dict[str, Any]],
    theta: dict[str, float],
    output_dir: Path,
    seed: int,
    start_min: int,
    duration_min: int,
    reward_start_min: int,
    time_step_sec: int,
    generation_multiplier: float,
    max_spawn_per_bin: int,
    max_active_vehicles: int,
    max_vehicle_age_sec: int,
    epsilon: float,
    no_outgoing_penalty: float,
    spawn_timing: str,
    vehicle_packet_size: int,
    write_vehicle_traces: bool,
) -> dict[str, Any]:
    """固定seed評価runを実行する。"""

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
    comparison_rows, comparison_summary = write_run_outputs(
        observations=observations,
        result=result,
        output_dir=output_dir,
        start_min=start_min,
        duration_min=duration_min,
        write_vehicle_traces=write_vehicle_traces,
    )
    warmup_summary = summarize_after_min(comparison_rows, reward_start_min)
    return {
        "eval_runtime_sec": round(time.perf_counter() - eval_started, 3),
        "eval_mae": comparison_summary["mae"],
        "eval_rmse": comparison_summary["rmse"],
        "eval_bias": comparison_summary["bias"],
        "eval_observed_total": comparison_summary["observed_total"],
        "eval_simulated_total": comparison_summary["simulated_total"],
        "eval_simulated_total_ratio": ratio(comparison_summary["simulated_total"], comparison_summary["observed_total"]),
        "eval_warmup_mae": warmup_summary["mae"],
        "eval_warmup_rmse": warmup_summary["rmse"],
        "eval_warmup_bias": warmup_summary["bias"],
        "eval_warmup_observed_total": warmup_summary["observed_total"],
        "eval_warmup_simulated_total": warmup_summary["simulated_total"],
        "eval_warmup_simulated_total_ratio": ratio(warmup_summary["simulated_total"], warmup_summary["observed_total"]),
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


def filter_observations_by_boundary(
    *,
    network: RoadDbNetwork,
    alignment_path: Path,
    observations: list[ObservationMatch],
    threshold_meter: float,
) -> dict[str, Any]:
    """道路DB bbox 境界から近い観測点を除外する。"""

    alignment = load_json(alignment_path)
    lat_lon_by_id = {
        obs["id"]: (float(obs["lat"]), float(obs["lon"]))
        for obs in alignment.get("observations", [])
        if "lat" in obs and "lon" in obs
    }
    bounds = bounds_from_network(network)
    center_lat = (bounds["min_lat"] + bounds["max_lat"]) / 2.0
    included: list[ObservationMatch] = []
    excluded: list[dict[str, Any]] = []
    for observation in observations:
        lat_lon = lat_lon_by_id.get(observation.observation_id)
        if not lat_lon:
            included.append(observation)
            continue
        lat, lon = lat_lon
        boundary_distance = distance_to_bbox_edge_meter(lat, lon, bounds, center_lat)
        if boundary_distance < threshold_meter:
            excluded.append(
                {
                    "observation_id": observation.observation_id,
                    "point_number": observation.point_number,
                    "point_name": observation.point_name,
                    "lat": lat,
                    "lon": lon,
                    "boundary_distance_meter": round(boundary_distance, 1),
                    "directed_edge_id": observation.directed_edge_id,
                    "observed_total": sum(observation.observed_volume_5min.values()),
                }
            )
        else:
            included.append(observation)
    return {
        "threshold_meter": threshold_meter,
        "bounds": bounds,
        "included": included,
        "excluded": sorted(excluded, key=lambda item: item["boundary_distance_meter"]),
        "summary": {
            "threshold_meter": threshold_meter,
            "before_count": len(observations),
            "included_count": len(included),
            "excluded_count": len(excluded),
        },
    }


def bounds_from_network(network: RoadDbNetwork) -> dict[str, float]:
    """道路DB node のbboxを返す。"""

    lats = [float(node["lat"]) for node in network.nodes.values()]
    lons = [float(node["lon"]) for node in network.nodes.values()]
    return {
        "min_lat": min(lats),
        "max_lat": max(lats),
        "min_lon": min(lons),
        "max_lon": max(lons),
    }


def distance_to_bbox_edge_meter(lat: float, lon: float, bounds: dict[str, float], center_lat: float) -> float:
    """bbox境界までの最短距離を概算メートルで返す。"""

    north = max(0.0, bounds["max_lat"] - lat) * 111_320.0
    south = max(0.0, lat - bounds["min_lat"]) * 111_320.0
    east = max(0.0, bounds["max_lon"] - lon) * meters_per_lon_degree(center_lat)
    west = max(0.0, lon - bounds["min_lon"]) * meters_per_lon_degree(center_lat)
    return min(north, south, east, west)


def meters_per_lon_degree(lat: float) -> float:
    """指定緯度における経度1度あたりの距離を返す。"""

    return 111_320.0 * math.cos(math.radians(lat))


def summarize_after_min(rows: list[dict[str, Any]], start_min: int) -> dict[str, Any]:
    """指定時刻以降の比較サマリを返す。"""

    return summarize([row for row in rows if int(row["time_min"]) >= start_min])


def ratio(numerator: float | int | None, denominator: float | int | None) -> float | None:
    """分母が0でない場合だけ比率を返す。"""

    if denominator in (None, 0):
        return None
    if numerator is None:
        return None
    return float(numerator) / float(denominator)


def baseline_lambda_for_iteration(
    *,
    baseline_mode: str,
    fixed_lambda: float,
    current_auto_lambda: float,
) -> float:
    """baseline mode に応じてその iteration で使う lambda を返す。"""

    if baseline_mode == "mixed_auto":
        return min(1.0, max(0.0, current_auto_lambda))
    if baseline_mode == "mixed_fixed":
        return min(1.0, max(0.0, fixed_lambda))
    return min(1.0, max(0.0, fixed_lambda))


def write_boundary_filter_summary(boundary_filter: dict[str, Any], path: Path) -> None:
    """境界除外サマリを書く。"""

    output = {
        "threshold_meter": boundary_filter["threshold_meter"],
        "bounds": boundary_filter["bounds"],
        "summary": boundary_filter["summary"],
        "excluded": boundary_filter["excluded"],
    }
    with path.open("w", encoding="utf-8") as file:
        json.dump(output, file, ensure_ascii=False, indent=2)


def write_excluded_observations(rows: list[dict[str, Any]], path: Path) -> None:
    """境界除外観測点CSVを書く。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "observation_id",
        "point_number",
        "point_name",
        "lat",
        "lon",
        "boundary_distance_meter",
        "directed_edge_id",
        "observed_total",
    ]
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    main()
