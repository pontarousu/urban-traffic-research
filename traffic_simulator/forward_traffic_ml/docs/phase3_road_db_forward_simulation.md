# Phase 3: Road DB ベース順方向シミュレーション

> このファイルは詳細ログです。初見の場合は先に `docs/README.md`、`docs/research_timeline.md`、`docs/spec.md` を読んでください。`Phase 3` は研究中の内部フェーズ名であり、公開版の読み順を意味するものではありません。

## 目的

Phase 3 では、OSM way ベースの旧シミュレーションから、道路DBの `directed_edge` ベースへ移行する。

この段階の目的は精度最適化ではなく、以下の動作を確認すること。

- 車両が `directed_edge` 上を前進する
- edge 終端で `branch_options` に従って次の edge を選ぶ
- 観測点の `matched_link` と `position_ratio` に基づいて通過を記録する
- 観測値と simulated count を5分単位で比較できる
- 分岐 trace と観測 trace が次フェーズの学習に使える形式で出る

## 入力

```text
data/road_db_snapshots/road_db_prototype_tokyo_core_small_runtime_current/network_core.json
viewer/data/observation_alignment.json
data/private/scenario_with_observations.json
```

`network_core.json` から使うもの:

```text
directed_edges
topology_nodes
branch_options
```

`observation_alignment.json` から使うもの:

```text
observations[].matched_link.directed_edge_id
observations[].matched_link.position_ratio
observations[].match_method
observations[].match_confidence
```

元シナリオ JSON から使うもの:

```text
observation_points[].traffic_volume
```

`observation_alignment.json` には5分別の観測時系列を持たせていないため、観測点対応と観測時系列は実行時に結合する。

## 実装ファイル

```text
src/road_db_network_loader.py
  road DB snapshot と観測点対応を読む。
  edge ごとの観測点 index と発生候補 edge を作る。

src/road_db_forward_simulator.py
  directed_edge 上で車両を前進させる。
  交差点で branch_options から次 edge を選ぶ。
  観測点通過、分岐 trace、車両 trace を記録する。

src/run_road_db_simulation.py
  小規模シミュレーションを実行し、count / trace / summary を出力する。

src/compare_road_db_counts.py
  simulation_counts.csv と観測値を比較し、MAE / RMSE / Bias を出す。
```

## 車両状態

```json
{
  "vehicle_id": 1,
  "directed_edge_id": "directed_edge_xxx",
  "position_meter": 0.0,
  "birth_time_sec": 0,
  "source_edge_id": "directed_edge_xxx",
  "source_category": "major_rule",
  "branch_trace": [],
  "observation_trace": []
}
```

## 分岐

Phase 3 の分岐は、まだ学習済みではない。

`branch_options` の候補に対して `theta = 0` の softmax を使うため、初期状態ではほぼ一様ランダムになる。
探索用に `epsilon` も混ぜる。

分岐パラメータの単位は以下。

```text
(node_id, incoming_directed_edge_id, outgoing_directed_edge_id)
```

trace には以下を記録する。

```json
{
  "time_sec": 120,
  "time_min": 482,
  "node_id": "10001175954",
  "incoming_directed_edge_id": "directed_edge_000001",
  "outgoing_directed_edge_id": "directed_edge_000003",
  "probability": 0.5
}
```

## 観測点通過

観測点位置は以下で計算する。

```text
observation_position_meter = matched_link.length_meter * matched_link.position_ratio
```

車両が同じ `directed_edge` 上で、前回位置から今回位置までの間に観測点位置をまたいだ場合に通過とする。

```text
previous_position <= observation_position_meter < next_position
```

通過 trace は以下。

```json
{
  "time_sec": 145,
  "time_min": 482,
  "bin_min": 480,
  "observation_id": "obs_300C_2010",
  "point_number": "2010",
  "directed_edge_id": "directed_edge_xxx",
  "position_ratio": 0.62
}
```

## 発生源モード

Phase 3 では、発生源学習はまだ対象にしない。
検証目的ごとに3モードを用意した。

```text
major:
  幹線道路から発生する。
  road_type, lane_count_total, length_meter で重み付けする。

matched_edges:
  観測点が対応した directed_edge から発生する。
  これは観測点通過判定の debug 用であり、現実的な交通発生モデルではない。

mixed:
  major を主体にしつつ、debug 用に matched_edges を弱く混ぜる。

observation_upstream:
  観測点の matched directed_edge から、道路接続を逆向きにたどる。
  edge 数ではなく length_meter の累積距離で上流候補を選ぶ。
  観測点の真上から発生させる debug 方式より自然で、major 発生より観測点に届きやすい。
```

`observation_upstream` の初期設定:

```text
upstream_min_distance_meter = 80
upstream_max_distance_meter = 450
upstream_max_candidates_per_observation = 12
min_length_meter = 20
```

## 初回検証

debug 条件:

```bash
python3 -B src/run_road_db_simulation.py \
  --duration-min 15 \
  --source-mode matched_edges \
  --generation-multiplier 0.02 \
  --max-spawn-per-bin 150 \
  --max-active-vehicles 500 \
  --time-step-sec 5 \
  --seed 7
```

結果:

```text
発生台数: 450
観測点通過イベント: 733
分岐イベント: 18068
vehicle trace: 450
観測点あり trace: 448
```

比較:

```text
observed_total: 48583
simulated_total: 733
hit_rows: 427 / 864
MAE: 55.428
RMSE: 59.490
Bias: -55.382
Correlation: 0.184
```

この条件は観測点通過判定の確認用であり、発生源としては現実的ではない。

本番寄り条件:

```bash
python3 -B src/run_road_db_simulation.py \
  --duration-min 15 \
  --source-mode major \
  --generation-multiplier 0.02 \
  --max-spawn-per-bin 150 \
  --max-active-vehicles 500 \
  --time-step-sec 5 \
  --seed 7 \
  --output-dir results/road_db_phase3_major_smoke
```

結果:

```text
発生台数: 450
観測点通過イベント: 140
分岐イベント: 15459
hit_rows: 109 / 864
```

本番寄りの発生では観測点到達がかなり少ない。
これは、次フェーズで発生源候補やOD傾向を調整する必要があることを示している。

## 観測点上流発生の追加検証

発生位置を edge 数ではなく `length_meter` の累積距離で決める `observation_upstream` を追加しました。

候補生成結果:

```text
対象観測点: 288
上流発生候補: 2529
上流距離: 81.28m - 447.97m
中央値: 214.95m
```

実行条件:

```bash
python3 -B src/run_road_db_simulation.py \
  --duration-min 15 \
  --source-mode observation_upstream \
  --generation-multiplier 0.02 \
  --max-spawn-per-bin 150 \
  --max-active-vehicles 500 \
  --time-step-sec 5 \
  --seed 7 \
  --output-dir results/road_db_phase3_observation_upstream_smoke
```

結果:

```text
発生台数: 450
観測点通過イベント: 350
分岐イベント: 15651
hit_rows: 243 / 864
```

同条件比較:

```text
major:
  観測点通過イベント 140
  hit_rows 109 / 864

observation_upstream:
  観測点通過イベント 350
  hit_rows 243 / 864

matched_edges:
  観測点通過イベント 733
  hit_rows 427 / 864
```

`observation_upstream` は、debug 用の `matched_edges` よりは直接的すぎず、`major` よりは観測点へ届きやすい。
分岐学習の初期信号を得るための発生モードとして有効そうです。

## 発生タイミング

初期実装では、5分binの開始時点で発生台数をまとめて投入していました。
ただし、これは実際の交通流として不自然で、同時刻に大量の車両が同じ周辺から出るため、分岐 trace にも偏りが出ます。

そのため、`spawn_timing` を追加しました。

```text
batch:
  5分binの開始時点でまとめて発生する。
  旧挙動の再現や比較用。

distributed:
  5分binの発生台数を timestep ごとに平滑化して発生する。
  例: 5分100台なら、time_step_sec=1 では約3秒に1台、
      time_step_sec=5 では5秒ごとに1-2台発生する。
```

Phase 4 の学習では `distributed` を標準にします。
発生タイミングを平滑化することで、5分境界にだけ交通流が偏ることを避けます。

distributed の smoke test:

```bash
python3 -B src/run_road_db_simulation.py \
  --duration-min 15 \
  --source-mode observation_upstream \
  --spawn-timing distributed \
  --generation-multiplier 0.02 \
  --max-spawn-per-bin 150 \
  --max-active-vehicles 500 \
  --time-step-sec 1 \
  --seed 7 \
  --output-dir results/road_db_phase3_observation_upstream_distributed_smoke
```

結果:

```text
発生台数: 450
scheduled_spawn_events: 450
観測点通過イベント: 287
hit_rows: 201 / 864
active_vehicle_max: 140
```

同じ450台でも、一括発生時の観測点通過イベント350より少なくなった。
これは後半に発生した車が15分内に観測点へ届ききらないためで、5分開始時にまとめて全車を出すより自然な挙動です。

## 300-1000m 上流発生の距離診断

backtrace を長距離化する前に、実際に車両が発生地点から観測点までどれくらい走っているかを確認しました。

実行条件:

```bash
python3 -B src/run_road_db_simulation.py \
  --duration-min 20 \
  --source-mode observation_upstream \
  --upstream-min-distance-meter 300 \
  --upstream-max-distance-meter 1000 \
  --spawn-timing distributed \
  --generation-multiplier 0.03 \
  --max-spawn-per-bin 100000 \
  --max-active-vehicles 3000 \
  --max-vehicle-age-sec 2400 \
  --time-step-sec 1 \
  --seed 9001 \
  --output-dir results/road_db_phase3_upstream_300_1000_diagnostics
```

`max_spawn_per_bin` は cap にかからないよう大きくし、発生量は `generation_multiplier` の結果をそのまま使いました。

結果:

```text
発生台数: 1953
観測点通過イベント: 863
初回観測点に到達した車両: 532
到達率: 27.2%
source_to_first_observation_distance:
  mean 1142.0m
  median 578.9m
  p90 3112.4m
source_to_first_observation_time:
  mean 111.3秒
  median 50.0秒
  p90 307.0秒
```

比較として、80-450m 上流発生の distributed smoke では以下でした。

```text
発生台数: 450
初回観測点に到達した車両: 178
到達率: 39.6%
source_to_first_observation_distance:
  mean 682.0m
  median 246.3m
  p90 1847.3m
source_to_first_observation_time:
  mean 64.0秒
  median 19.5秒
  p90 184.0秒
```

300-1000m 上流発生では、初回観測点までの走行距離は明確に伸びました。
一方で到達率は下がるため、長距離 backtrace を使う場合は発生量、duration、到達率をセットで見る必要があります。

## iteration ごとの乱数

Phase 4 の学習ループでは、毎 iteration で同じ乱数を使い続けません。
固定乱数だけで学習すると、その発生配置にだけ適合した theta になるリスクがあるためです。

初期方針:

```text
iteration_seed = base_seed + iteration_index
```

これにより、発生候補のルールや総発生量は同じまま、実際にどの source edge から発生するかが iteration ごとに少し変わります。
評価の安定性を見る場合は、別途 fixed seed の検証 run を残します。

## Phase 3 の現時点の結論

以下は確認できた。

```text
road DB directed_edge 上で車両が動く
branch_options による分岐 trace が出る
matched_link による観測点通過 trace が出る
5分単位の simulated count と観測値比較が出る
```

一方で、精度や総量はまだ評価対象ではない。
特に発生源を major road だけにすると観測点への到達が少ないため、次は発生源設計と分岐学習の接続を進める。
