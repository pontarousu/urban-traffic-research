# Phase 4: Trace-based Feedback Training

> このファイルは詳細ログです。初見の場合は先に `docs/README.md`、`docs/research_timeline.md`、`docs/spec.md`、`docs/experiment_summary.md` を読んでください。`Phase 4` は研究中の内部フェーズ名であり、公開版の読み順を意味するものではありません。

## 目的

Phase 4 では、観測点ごとの誤差を車両の分岐 trace に戻し、交差点の分岐確率 `theta` を更新する。

学習対象は以下の単位。

```text
theta[node_id, incoming_directed_edge_id, outgoing_directed_edge_id]
```

`theta` は交通量そのものではなく、交差点での outgoing edge の選ばれやすさを表すスコア。
シミュレーション時は softmax によって分岐確率へ変換する。

## 更新の意味

観測点・5分binごとに以下を計算する。

```text
feedback_error = (observed - simulated) / max(observed, error_floor)
```

意味:

```text
feedback_error > 0:
  観測値に対してシミュレーションが不足している。
  その観測点へ到達した車両の直近分岐を強める。

feedback_error < 0:
  観測値に対してシミュレーションが過剰。
  その観測点へ到達した車両の直近分岐を弱める。
```

各観測点に多くの車両が届いた場合に更新量が過大にならないよう、以下で割る。

```text
observation_weight = 1 / max(1, simulated)
```

1つの分岐寄与の更新量:

```text
delta_theta =
  learning_rate
  * feedback_error
  * recency_weight
  * observation_weight
```

初期設定:

```text
learning_rate = 0.05
error_floor = 20
max_backtrace_branches = 5
delta_clip = 0.05
theta_min = -3.0
theta_max = 3.0
regularization = 0.001
```

recency weight:

```text
rank 1: 1.0
rank 2: 0.8
rank 3: 0.6
rank 4: 0.4
rank 5: 0.2
```

## 実装ファイル

```text
src/road_db_theta_policy.py
  theta の保存、読み込み、delta 適用、clamp、regularization を扱う。

src/road_db_feedback_trainer.py
  comparison と vehicle_traces から theta delta を作る。
  backtrace 距離・時間診断も出す。

src/run_road_db_training.py
  simulation -> comparison -> feedback -> theta update を iteration で回す。
```

## iteration ごとの発生

固定乱数への過適合を避けるため、iteration ごとに seed を変える。

```text
seed = base_seed + iteration
```

発生は以下を標準にする。

```text
source_mode = observation_upstream
spawn_timing = distributed
```

## 固定 seed 評価 run

training run は iteration ごとに seed を変えるため、指標変化が theta の効果なのか乱数差なのか切り分けにくい。
そのため、各 iteration の theta 更新後に、毎回同じ `eval_seed` で evaluation run を追加しました。

```text
training run:
  seed = base_seed + iteration
  theta 更新に使う

evaluation run:
  seed = eval_seed
  theta 更新後に実行する
  theta は更新しない
```

出力場所:

```text
iteration_xxx/evaluation/simulation_counts.csv
iteration_xxx/evaluation/comparison.csv
iteration_xxx/evaluation/comparison_summary.json
iteration_xxx/evaluation/vehicle_traces.json
```

`iteration_metrics.csv` には以下の列を追加しました。

```text
eval_mae
eval_rmse
eval_bias
eval_simulated_total
eval_simulated_total_ratio
eval_hit_rows
eval_correlation
eval_observation_event_count
eval_branch_event_count
```

## 出力指標

iteration ごとに以下を `iteration_metrics.csv` へ出す。

```text
MAE:
  観測点・5分binごとの平均絶対誤差。

RMSE:
  大きな誤差を強く見る誤差指標。

Bias:
  simulated - observed の平均。
  負なら全体的に過小、正なら過大。

simulated_total_ratio:
  simulated_total / observed_total。
  全体量の再現率。

hit_rows:
  simulated_count > 0 の観測点・5分bin数。
  trace-based feedback 可能な範囲の目安。

observation_event_count:
  延べ観測点通過イベント数。

branch_event_count:
  交差点分岐イベント数。

theta_updated_count:
  その iteration で更新された theta 数。

theta_nonzero_count:
  非ゼロ theta 数。

theta_min / theta_max:
  theta が極端になっていないかを見る。
```

## backtrace 診断

5分岐戻す設定は仮置きであり、edge 分割粒度に依存する。
そのため、各観測点通過イベントについて、直近分岐から観測点までの概算距離・時間を記録する。

出力:

```text
iteration_xxx/backtrace_diagnostics.csv
iteration_xxx/backtrace_summary.csv
backtrace_summary.csv
```

主な列:

```text
rank_from_observation
time_to_observation_sec
distance_to_observation_meter
feedback_error
recency_weight
delta_theta_raw
```

距離は、分岐後に通った directed_edge の `length_meter` と観測点の `position_ratio` から概算する。

## 初回 smoke training

実行条件:

```bash
python3 -B src/run_road_db_training.py \
  --iterations 5 \
  --duration-min 15 \
  --time-step-sec 1 \
  --source-mode observation_upstream \
  --spawn-timing distributed \
  --generation-multiplier 0.03 \
  --max-spawn-per-bin 300 \
  --max-active-vehicles 1200 \
  --base-seed 7000 \
  --learning-rate 0.05 \
  --max-backtrace-branches 5 \
  --output-dir results/road_db_training
```

結果概要:

```text
iteration 1:
  simulated_total 555
  hit_rows 343
  theta_updated_count 1265
  theta_nonzero_count 1264
  theta_max 0.04995

iteration 5:
  simulated_total 596
  hit_rows 357
  theta_updated_count 1460
  theta_nonzero_count 3862
  theta_max 0.24925
```

theta は更新され、clamp には達していない。
MAE は小幅に下がったが、iteration ごとに seed が変わるため、この5回だけで改善と断定しない。
今後、評価専用 fixed seed run を追加して、theta の効果と乱数差を切り分ける必要がある。

## fixed eval seed 付き smoke training

実行条件:

```bash
python3 -B src/run_road_db_training.py \
  --iterations 5 \
  --duration-min 15 \
  --time-step-sec 1 \
  --source-mode observation_upstream \
  --spawn-timing distributed \
  --generation-multiplier 0.03 \
  --max-spawn-per-bin 300 \
  --max-active-vehicles 1200 \
  --base-seed 7000 \
  --eval-seed 10007 \
  --learning-rate 0.05 \
  --max-backtrace-branches 5 \
  --output-dir results/road_db_training_eval
```

評価seed固定の結果:

```text
iteration 1:
  eval_mae 55.584
  eval_simulated_total 584
  eval_hit_rows 335

iteration 2:
  eval_mae 55.580
  eval_simulated_total 592
  eval_hit_rows 353

iteration 3:
  eval_mae 55.639
  eval_simulated_total 555
  eval_hit_rows 333

iteration 4:
  eval_mae 55.522
  eval_simulated_total 640
  eval_hit_rows 349

iteration 5:
  eval_mae 55.597
  eval_simulated_total 579
  eval_hit_rows 341
```

この結果では、iteration 4 で一度評価指標が改善するが、iteration 5 で戻る。
したがって、現時点では安定した改善とは判断しない。
ただし固定seed評価により、theta変更の影響を乱数差から分けて観察できるようになった。

## 5分岐 backtrace の距離・時間

初回 smoke training の rank 別概算は以下。

```text
rank 1:
  距離平均 約59-61m
  時間平均 約3.5-3.7秒

rank 2:
  距離平均 約106-116m
  時間平均 約7.7-8.1秒

rank 3:
  距離平均 約168-180m
  時間平均 約13.3-14.0秒

rank 4:
  距離平均 約226-244m
  時間平均 約18.5-19.7秒

rank 5:
  距離平均 約268-293m
  時間平均 約23.8-25.1秒
```

この結果だけを見ると、5分岐はおおむね 270-290m、24秒前後に相当する。
ただし場所ごとのばらつきがあるため、次に距離ベース backtrace へ切り替える候補を検討する。

## 距離ベース backtrace の試行

5分岐 backtrace は edge 分割粒度に依存するため、観測点から上流方向へ概算距離で責任を戻す方式を追加した。

追加した設定:

```text
backtrace_mode:
  branch_count:
    従来方式。観測点直前の最大 N 分岐へ戻す。

  distance:
    観測点から max_backtrace_distance_meter 以内の分岐へ戻す。
    距離が遠い分岐ほど exp(-distance / backtrace_decay_meter) で弱める。
```

今回の試行条件:

```text
source_mode = observation_upstream
upstream_min_distance_meter = 300
upstream_max_distance_meter = 1000
duration_min = 20
generation_multiplier = 0.03
spawn_timing = distributed
iterations = 10
eval_seed = 19001
learning_rate = 0.05

branch_count 比較:
  max_backtrace_branches = 5

distance 比較:
  max_backtrace_distance_meter = 1000
  backtrace_decay_meter = 350
  min_backtrace_weight = 0.05
```

結果概要:

```text
branch_count, iteration 10:
  eval_mae 55.583
  eval_simulated_total 1111
  eval_hit_rows 513
  eval_correlation 0.170
  raw_feedback_contribution_count 5090
  theta_nonzero_count 6791

distance, iteration 10:
  eval_mae 55.606
  eval_simulated_total 1121
  eval_hit_rows 490
  eval_correlation 0.157
  raw_feedback_contribution_count 15523
  theta_nonzero_count 24932
```

best eval_mae:

```text
branch_count:
  iteration 9
  eval_mae 55.572

distance:
  iteration 8
  eval_mae 55.543
```

解釈:

```text
distance backtrace は、1回の観測点通過から更新される theta の範囲を大きく広げられる。
そのため、観測点が疎な領域でも学習信号を上流側へ届けやすい。

一方で、10 iteration 時点の最終評価では branch_count よりわずかに悪い。
途中の best eval_mae は distance の方が良いが、まだ安定改善とは判断しない。

distance 方式は有望だが、learning_rate、decay_meter、更新量正規化を調整しないと、
広く薄く戻した誤差がノイズとして働く可能性がある。
```

次の判断:

```text
短時間・少台数条件では、distance backtrace の実装自体は動作した。
次は、時間規模を少し広げて、評価seed固定のまま改善が再現するかを見る。
ただし、時間を伸ばす前に distance の learning_rate を少し下げる比較も候補にする。
```

## 40分スケールでの確認

20分条件で distance backtrace が動作したため、まず `duration_min = 40` に伸ばして確認した。
iteration 数は軽めに 5 回とし、固定評価 seed で推移を見る。

実行条件:

```text
source_mode = observation_upstream
upstream_min_distance_meter = 300
upstream_max_distance_meter = 1000
duration_min = 40
generation_multiplier = 0.03
spawn_timing = distributed
iterations = 5
eval_seed = 19101
learning_rate = 0.05
backtrace_mode = distance
max_backtrace_distance_meter = 1000
backtrace_decay_meter = 350
max_active_vehicles = 6000
```

結果:

```text
iteration 1 evaluation:
  eval_mae 56.587
  eval_simulated_total 2354
  eval_simulated_total_ratio 0.0178
  eval_hit_rows 1068
  eval_correlation 0.108

iteration 5 evaluation:
  eval_mae 56.480
  eval_simulated_total 2615
  eval_simulated_total_ratio 0.0197
  eval_hit_rows 1084
  eval_correlation 0.117
```

theta 状態:

```text
iteration 5:
  theta_nonzero_count 27800
  theta_max 0.249
  theta_min -0.029
  clamped_theta_count 0
```

解釈:

```text
40分条件でも実行は破綻していない。
固定seed評価では、iteration 1 から 5 にかけて MAE が小さくなり、
観測点通過イベント数と simulated_total_ratio も増えた。

ただし simulated_total_ratio はまだ約2%で、絶対的には大きく過小。
これは分岐学習だけではなく、発生量、発生位置、観測点近傍への到達率にも強く依存している。
```

次の候補:

```text
duration_min = 60 へ拡大する。
その前後で、learning_rate = 0.03 などの弱め更新も比較する。
simulated_total_ratio が低すぎるため、generation_multiplier を段階的に上げる実験も必要。
```

## intersection 更新ヒートマップ

theta 更新がどの intersection に集中しているか確認するため、ヒートマップビューアを追加した。

追加ファイル:

```text
src/export_intersection_update_heatmap.py
viewer/intersection_update_heatmap.html
viewer/intersection_update_heatmap.js
viewer/data/intersection_update_heatmap.json
```

集計元:

```text
results/road_db_training_upstream_300_1000_distance1000_duration40/iteration_*/backtrace_diagnostics.csv
```

各 intersection について以下を集計する。

```text
update_count:
  更新寄与が発生した回数。

abs_delta_sum:
  絶対更新量の合計。ヒートマップの標準表示に使う。

signed_delta_sum:
  正負付き更新量の合計。

unique_theta_count:
  更新対象になった theta の種類数。
```

40分・5 iteration 結果:

```text
updated_intersection_count 10982
raw_update_row_count 173705
road_line_count 22014
abs_delta_sum median 0.030
abs_delta_sum p90 0.274
abs_delta_sum p99 1.254
abs_delta_sum max 4.095
```

ビューア:

```text
http://localhost:8010/intersection_update_heatmap.html
```

表示上の注意:

```text
濃い色の intersection は、観測誤差が強く戻された場所を示す。
これは「交通量が多い交差点」そのものではなく、
現行の trace-based feedback が強く theta を動かそうとしている場所を意味する。
```

## mesh_uniform 発生位置プレビュー

観測点上流発生による学習作用の偏りを確認するため、`mesh_uniform` 発生方式を追加し、まず発生位置だけを可視化した。

実装:

```text
source_mode = mesh_uniform
mesh_size_meter = 500
```

発生候補は directed_edge の中点でメッシュに割り当てる。
メッシュごとの総重みは一様にし、メッシュ内では道路種別、車線数、速度、edge長で重みを付ける。

確認条件:

```text
start_min = 480
duration_min = 40
generation_multiplier = 0.03
seed = 9201
```

出力:

```text
results/road_db_mesh_uniform_spawn_preview/vehicle_traces.json
viewer/data/spawn_observation_points.json
```

結果:

```text
spawn_vehicle_count 3975
spawn_edge_count 3054
spawn_mesh_count 471
vehicles_with_observation_trace 640
```

ビューア:

```text
http://localhost:8011/spawn_observation_points.html
```

解釈:

```text
発生位置は観測点近傍だけでなく広く分散する。
一方で、同じ発生台数では observation_upstream より観測点通過数が下がる。
したがって、学習実験に進む前に generation_multiplier を上げるか、
observation_upstream との混合発生を検討する必要がある。
```

## mesh_uniform training 結果

`mesh_uniform` で 40分・5 iteration の学習を実行した。
高速化として、発生候補の重み選択を毎回全候補走査する方式から、累積重みの二分探索へ変更した。

比較条件:

```text
start_min = 480
duration_min = 40
mesh_size_meter = 500
backtrace_mode = distance
max_backtrace_distance_meter = 1000
backtrace_decay_meter = 350
iterations = 5
```

結果:

```text
mesh_uniform, generation_multiplier = 0.03:
  spawned_count 3975
  eval_mae 57.043
  eval_simulated_total 1193
  eval_simulated_total_ratio 0.0090
  eval_hit_rows 770
  theta_nonzero_count 21952

mesh_uniform, generation_multiplier = 0.1:
  spawned_count 13248
  eval_mae 55.846
  eval_simulated_total 4204
  eval_simulated_total_ratio 0.0317
  eval_hit_rows 1590
  theta_nonzero_count 38889
```

参考として、前回の観測点上流発生:

```text
observation_upstream, generation_multiplier = 0.03:
  spawned_count 3975
  eval_mae 56.480
  eval_simulated_total 2615
  eval_simulated_total_ratio 0.0197
  eval_hit_rows 1084
  theta_nonzero_count 27800
```

解釈:

```text
mesh_uniform g003 は観測点到達が少なく、学習信号が弱い。
mesh_uniform g010 では観測点通過数と更新対象 intersection が増え、MAE も observation_upstream g003 より良くなった。
ただし simulated_total_ratio はまだ 3.2% 程度で、観測総量には大きく届いていない。
```

更新ヒートマップ:

```text
result_dir = results/road_db_training_mesh_uniform_500_g010_duration40_fast
updated_intersection_count = 14080
raw_update_row_count = 272593
abs_delta_sum_max = 4.976
```

`viewer/data/intersection_update_heatmap.json` は `mesh_uniform g010` の結果で更新した。

## 車両パケット化の比較

再現量を上げる前に、複数台を1つの代表車両で扱う `vehicle_packet_size` を追加した。

仕様:

```text
vehicle.weight = packet_size
観測点通過時:
  simulated_count += vehicle.weight

feedback:
  delta_theta_raw *= vehicle.weight
```

最初の実装では、packet 全体が同じ分岐を選ぶ。
そのため計算量は下がるが、通過する観測点・経路の空間的なばらつきは減る。

比較条件:

```text
source_mode = mesh_uniform
mesh_size_meter = 500
generation_multiplier = 0.1
duration_min = 40
iterations = 5
base_seed = 9600
eval_seed = 19601
```

結果:

```text
packet_size = 1:
  avg_iteration_runtime_sec 19.395
  avg_simulation_runtime_sec 5.456
  avg_feedback_runtime_sec 3.477
  avg_eval_runtime_sec 7.792
  last_eval_mae 55.875
  last_eval_simulated_total 4128
  last_eval_simulated_total_ratio 0.0312
  last_eval_hit_rows 1574
  last_spawn_packet_count 13248
  last_theta_nonzero_count 38490

packet_size = 5:
  avg_iteration_runtime_sec 5.070
  avg_simulation_runtime_sec 1.346
  avg_feedback_runtime_sec 0.872
  avg_eval_runtime_sec 2.127
  last_eval_mae 56.007
  best_eval_mae 55.909
  last_eval_simulated_total 3841
  last_eval_simulated_total_ratio 0.0290
  last_eval_hit_rows 705
  last_spawn_packet_count 3648
  last_theta_nonzero_count 21035
```

解釈:

```text
packet_size = 5 は、1 iteration あたり約3.8倍高速。
一方で、代表車両がまとめて同じ経路を走るため、hit_rows と theta_nonzero_count は大きく減る。
MAE は大きく崩れてはいないが、packet_size = 1 よりやや悪い。
```

判断:

```text
大量発生の探索には packet_size = 5 を使える。
ただし空間カバレッジを重視する評価では packet_size = 1 または 2 も比較する。
将来的には、交差点で packet を分岐確率に応じて split する方式を検討する。
```

比較CSV:

```text
results/packet_size_comparison_g010_duration40.csv
```

## generation_multiplier = 0.3 の確認

`packet_size = 5` のまま、発生倍率だけを `0.1` から `0.3` に上げて比較した。

条件:

```text
source_mode = mesh_uniform
mesh_size_meter = 500
generation_multiplier = 0.3
duration_min = 40
iterations = 5
base_seed = 9600
eval_seed = 19601
vehicle_packet_size = 5
```

結果:

```text
generation_multiplier = 0.1, packet_size = 5:
  avg_iteration_runtime_sec 5.070
  avg_simulation_runtime_sec 1.346
  avg_feedback_runtime_sec 0.872
  avg_eval_runtime_sec 2.127
  last_eval_mae 56.007
  best_eval_mae 55.909
  last_eval_simulated_total 3841
  last_eval_simulated_total_ratio 0.0290
  last_eval_hit_rows 705
  last_spawned_count 13248
  last_spawn_packet_count 3648
  last_theta_nonzero_count 21035

generation_multiplier = 0.3, packet_size = 5:
  avg_iteration_runtime_sec 14.724
  avg_simulation_runtime_sec 4.072
  avg_feedback_runtime_sec 2.742
  avg_eval_runtime_sec 5.921
  last_eval_mae 52.777
  best_eval_mae 52.777
  last_eval_simulated_total 11964
  last_eval_simulated_total_ratio 0.0903
  last_eval_hit_rows 1294
  last_spawned_count 39746
  last_spawn_packet_count 9588
  last_theta_nonzero_count 34307
```

解釈:

```text
generation_multiplier を 0.3 に上げると、計算時間は約2.9倍に増える。
一方で、simulated_total_ratio、hit_rows、theta_nonzero_count、MAE は明確に改善した。
まだ観測総量に対する再現量は約9.0%であり、絶対量は不足している。
ただし g010 より学習信号は増えており、次に発生倍率を上げる実験へ進む根拠はある。
```

出力:

```text
results/road_db_training_mesh_uniform_500_g030_packet5_compare
```

## generation_multiplier = 0.5 の確認

`generation_multiplier = 0.3` の改善を受けて、同じ `packet_size = 5` のまま `0.5` まで上げた。

条件:

```text
source_mode = mesh_uniform
mesh_size_meter = 500
generation_multiplier = 0.5
duration_min = 40
iterations = 5
base_seed = 9600
eval_seed = 19601
vehicle_packet_size = 5
```

結果:

```text
generation_multiplier = 0.3, packet_size = 5:
  avg_iteration_runtime_sec 14.724
  avg_simulation_runtime_sec 4.072
  avg_feedback_runtime_sec 2.742
  avg_eval_runtime_sec 5.921
  last_eval_mae 52.777
  last_eval_simulated_total 11964
  last_eval_simulated_total_ratio 0.0903
  last_eval_hit_rows 1294
  last_spawned_count 39746
  last_spawn_packet_count 9588
  last_theta_nonzero_count 34307

generation_multiplier = 0.5, packet_size = 5:
  avg_iteration_runtime_sec 22.213
  avg_simulation_runtime_sec 6.294
  avg_feedback_runtime_sec 4.012
  avg_eval_runtime_sec 8.906
  last_eval_mae 49.497
  best_eval_mae 49.497
  last_eval_simulated_total 20480
  last_eval_simulated_total_ratio 0.1546
  last_eval_hit_rows 1649
  last_spawned_count 66242
  last_spawn_packet_count 14400
  last_theta_nonzero_count 40004
```

解釈:

```text
g030 から g050 に上げると、計算時間は約1.5倍に増えた。
一方で、MAE は 52.777 から 49.497 まで改善した。
simulated_total_ratio は 9.0% から 15.5% に増え、hit_rows も 1294 から 1649 に増えた。
5 iteration 内では eval_mae が iteration ごとに下がっており、まだ学習が頭打ちではない。
```

注意:

```text
g050 でも観測総量に対する再現量は約15.5%で、絶対量はまだ不足している。
ただし 1 iteration が約22秒になっており、g075 や g100 では計算時間がさらに重くなる。
次は g050 のまま iteration を増やすか、g075 を少数 iteration で試すかを選ぶ。
```

出力:

```text
results/road_db_training_mesh_uniform_500_g050_packet5_compare
```

## generation_multiplier = 0.75 の確認

`generation_multiplier = 0.5` でも再現量が不足していたため、同じ `packet_size = 5` のまま `0.75` を試した。

条件:

```text
source_mode = mesh_uniform
mesh_size_meter = 500
generation_multiplier = 0.75
duration_min = 40
iterations = 5
base_seed = 9600
eval_seed = 19601
vehicle_packet_size = 5
```

結果:

```text
generation_multiplier = 0.5, packet_size = 5:
  avg_iteration_runtime_sec 22.213
  avg_simulation_runtime_sec 6.294
  avg_feedback_runtime_sec 4.012
  avg_eval_runtime_sec 8.906
  last_eval_mae 49.497
  last_eval_simulated_total 20480
  last_eval_simulated_total_ratio 0.1546
  last_eval_hit_rows 1649
  last_spawned_count 66242
  last_spawn_packet_count 14400
  last_theta_nonzero_count 40004

generation_multiplier = 0.75, packet_size = 5:
  avg_iteration_runtime_sec 35.706
  avg_simulation_runtime_sec 9.927
  avg_feedback_runtime_sec 6.384
  avg_eval_runtime_sec 14.819
  last_eval_mae 45.933
  best_eval_mae 45.933
  last_eval_simulated_total 29818
  last_eval_simulated_total_ratio 0.2251
  last_eval_hit_rows 1833
  last_spawned_count 99363
  last_spawn_packet_count 21095
  last_theta_nonzero_count 45500
```

解釈:

```text
g050 から g075 に上げると、計算時間は約1.6倍に増えた。
simulated_total_ratio は 15.5% から 22.5% に増え、MAE は 49.497 から 45.933 に改善した。
hit_rows は 1649 から 1833 に増えたが、観測セル総数 2228 に対してまだ未到達セルが残る。
theta_nonzero_count も増えており、学習対象 intersection はさらに広がった。
```

注意:

```text
1 iteration が約36秒になったため、評価付きで 50 iteration 回すと単純計算で約30分かかる。
今後 iteration を増やす場合は、毎回 eval するのではなく、学習中は skip_evaluation を使い、数 iteration ごとに固定 seed 評価する構成を検討する。
```

出力:

```text
results/road_db_training_mesh_uniform_500_g075_packet5_compare
```

## generation_multiplier = 1.0 / 1.5 の確認

50%程度の再現量を目標に、`generation_multiplier = 1.0` と `1.5` を同条件で試した。

条件:

```text
source_mode = mesh_uniform
mesh_size_meter = 500
duration_min = 40
iterations = 5
base_seed = 9600
eval_seed = 19601
vehicle_packet_size = 5
```

結果:

```text
generation_multiplier = 0.75, packet_size = 5:
  avg_iteration_runtime_sec 35.706
  avg_simulation_runtime_sec 9.927
  avg_feedback_runtime_sec 6.384
  avg_eval_runtime_sec 14.819
  last_eval_mae 45.933
  last_eval_simulated_total 29818
  last_eval_simulated_total_ratio 0.2251
  last_eval_hit_rows 1833
  last_spawned_count 99363
  last_spawn_packet_count 21095
  last_theta_nonzero_count 45500

generation_multiplier = 1.0, packet_size = 5:
  avg_iteration_runtime_sec 41.420
  avg_simulation_runtime_sec 11.890
  avg_feedback_runtime_sec 7.131
  avg_eval_runtime_sec 16.839
  last_eval_mae 42.858
  best_eval_mae 42.858
  last_eval_simulated_total 38595
  last_eval_simulated_total_ratio 0.2913
  last_eval_hit_rows 1944
  last_spawned_count 132484
  last_spawn_packet_count 27002
  last_theta_nonzero_count 48314

generation_multiplier = 1.5, packet_size = 5:
  avg_iteration_runtime_sec 67.884
  avg_simulation_runtime_sec 20.160
  avg_feedback_runtime_sec 10.995
  avg_eval_runtime_sec 28.203
  last_eval_mae 37.507
  best_eval_mae 37.507
  last_eval_simulated_total 56699
  last_eval_simulated_total_ratio 0.4280
  last_eval_hit_rows 2089
  last_spawned_count 198726
  last_spawn_packet_count 40990
  last_theta_nonzero_count 53697
```

解釈:

```text
g100 では再現量が約29.1%、g150 では約42.8%まで上がった。
50%再現には g150 でも少し足りない。
単純外挿では generation_multiplier = 1.7 前後が候補になる。
一方で、g150 は 1 iteration 約68秒であり、評価付きの長期学習には重い。
hit_rows は g150 で 2089 / 2228 まで増え、未到達観測セルはかなり減った。
```

注意:

```text
g150 の avg_eval_runtime_sec は約28秒で、評価だけでもかなり重い。
今後 20-50 iteration を回す場合は、毎 iteration 評価を避ける必要がある。
また、g を上げるだけでは観測総量50%に近づくが、計算量も大きく増えるため、発生位置・経路探索・packet split の改善も検討する。
```

出力:

```text
results/road_db_training_mesh_uniform_500_g100_packet5_compare
results/road_db_training_mesh_uniform_500_g150_packet5_compare
```

## generation_multiplier = 1.5 / 20 iteration の確認

`generation_multiplier = 1.5` の5 iteration時点で改善が続いていたため、同じ条件で20 iterationまで延長した。
計算時間削減のため、固定seed評価は5 iterationごとに実行した。

条件:

```text
source_mode = mesh_uniform
mesh_size_meter = 500
generation_multiplier = 1.5
duration_min = 40
iterations = 20
eval_interval = 5
base_seed = 9600
eval_seed = 19601
vehicle_packet_size = 5
```

固定seed評価の推移:

```text
iteration 5:
  eval_mae 37.507
  eval_simulated_total 56699
  eval_simulated_total_ratio 0.4280
  eval_hit_rows 2089
  eval_correlation 0.1327
  theta_nonzero_count 53697
  theta_max 0.249

iteration 10:
  eval_mae 35.156
  eval_simulated_total 63329
  eval_simulated_total_ratio 0.4780
  eval_hit_rows 2136
  eval_correlation 0.1653
  theta_nonzero_count 62691
  theta_max 0.497

iteration 15:
  eval_mae 32.920
  eval_simulated_total 69568
  eval_simulated_total_ratio 0.5251
  eval_hit_rows 2157
  eval_correlation 0.2068
  theta_nonzero_count 67685
  theta_max 0.744

iteration 20:
  eval_mae 31.251
  eval_simulated_total 75766
  eval_simulated_total_ratio 0.5719
  eval_hit_rows 2184
  eval_correlation 0.2217
  theta_nonzero_count 70990
  theta_max 0.990
```

計算時間:

```text
avg_iteration_runtime_sec 46.749
avg_noeval_iteration_runtime_sec 41.376
avg_eval_iteration_runtime_sec 68.240
avg_simulation_runtime_sec 20.425
avg_feedback_runtime_sec 12.427
avg_eval_runtime_sec 28.291
```

active / spawn 制約:

```text
scheduled_spawn_count 198726
spawned_count 198726
dropped_spawn_count 0
last_active_vehicle_weight_max 21955
```

解釈:

```text
20 iteration で固定seed評価の再現量が 57.2% まで上がった。
5 iteration 時点では 42.8% だったため、単純に g を上げる前に iteration を回す効果は大きい。
MAE も 37.507 から 31.251 まで改善しており、20 iteration 時点でも完全な頭打ちではない。
ただし theta_max は 0.99 まで増えており、今後は確率が偏りすぎていないか可視化・分布確認が必要。
```

出力:

```text
results/road_db_training_mesh_uniform_500_g150_packet5_iter20_eval5
```

## generation_multiplier = 1.5 / 40 iteration 相当の確認

20 iteration 後の `theta_final.json` を初期値として、さらに20 iterationを追加した。
評価は引き続き5 iterationごとに固定seedで実行した。

条件:

```text
initial_theta = results/road_db_training_mesh_uniform_500_g150_packet5_iter20_eval5/theta_final.json
source_mode = mesh_uniform
mesh_size_meter = 500
generation_multiplier = 1.5
duration_min = 40
iterations = 20
eval_interval = 5
base_seed = 9620
eval_seed = 19601
vehicle_packet_size = 5
```

固定seed評価の推移:

```text
cumulative iteration 25:
  eval_mae 29.270
  eval_simulated_total_ratio 0.6150
  eval_hit_rows 2190
  eval_correlation 0.2474
  theta_max 1.234

cumulative iteration 30:
  eval_mae 28.454
  eval_simulated_total_ratio 0.6463
  eval_hit_rows 2203
  eval_correlation 0.2798
  theta_max 1.477

cumulative iteration 35:
  eval_mae 27.040
  eval_simulated_total_ratio 0.6851
  eval_hit_rows 2206
  eval_correlation 0.3000
  theta_max 1.719

cumulative iteration 40:
  eval_mae 26.463
  eval_simulated_total_ratio 0.6980
  eval_hit_rows 2207
  eval_correlation 0.3125
  theta_max 1.960
```

計算時間:

```text
avg_iteration_runtime_sec 50.160
avg_noeval_runtime_sec 44.386
avg_eval_iteration_runtime_sec 73.252
avg_eval_runtime_sec 27.952
```

active / spawn 制約:

```text
scheduled_spawn_count 198726
spawned_count 198726
dropped_spawn_count 0
```

theta 確率偏り:

```text
max_probability_avg 0.4824
max_probability_p95 0.5385
max_probability_p99 0.6801
max_probability_max 0.8013
highly_biased_group_count_p70 430
highly_biased_group_count_p80 20
highly_biased_group_count_p90 0
```

解釈:

```text
40 iteration 相当で固定seed評価の再現量は 69.8% まで上がった。
80%目標にはまだ届いていないが、MAE と相関は改善している。
ただし、20 iteration 時点より theta の偏りは強くなり、最大分岐確率は 0.80 まで上がった。
0.9以上の極端な分岐はまだないが、今後は確率偏りと過大推定地点を併せて確認する。
```

出力:

```text
results/road_db_training_mesh_uniform_500_g150_packet5_iter40_eval5
results/theta_probability_analysis_g150_iter40
```

## 40 iteration 評価結果の誤差診断

40 iteration 相当の固定seed評価について、観測点別・時間帯別の誤差診断を行った。

対象:

```text
results/road_db_training_mesh_uniform_500_g150_packet5_iter40_eval5/iteration_020/evaluation/comparison.csv
```

全体:

```text
observed_total 132484
simulated_total 92469
simulated_total_ratio 0.6980
error_total -40015
mae 26.463
rmse 33.069

under_row_count 1687
over_row_count 587
exact_row_count 30
zero_simulated_row_count 97

under_observation_count 257
over_observation_count 30
```

観測点別の特徴:

```text
過小観測点が 257、過大観測点が 30。
過大より過小が支配的。
top 50 の過小合計は -17786。
top 50 の過大合計は +1093。
```

過小が大きい観測点の例:

```text
大島八:
  observed_total 824
  simulated_total 0
  error_total -824

曙橋:
  observed_total 544
  simulated_total 0
  error_total -544

相生橋西:
  observed_total 702
  simulated_total 178
  error_total -524

四谷三:
  observed_total 521
  simulated_total 46
  error_total -475
```

過大が大きい観測点の例:

```text
大手門:
  observed_total 30
  simulated_total 161
  error_total +131

吾妻橋:
  observed_total 339
  simulated_total 463
  error_total +124

木場五:
  observed_total 356
  simulated_total 477
  error_total +121
```

時間帯別の特徴:

```text
08:00-08:05:
  observed_total 15960
  simulated_total 4857
  ratio 0.304
  error_total -11103

08:05-08:10:
  observed_total 16127
  simulated_total 9672
  ratio 0.600
  error_total -6455

08:10以降:
  ratio はおおむね 0.72 から 0.80 程度まで上がる。
```

解釈:

```text
40 iteration 時点で80%に届かない主因は、過大ではなく過小。
特に初期5分binの不足が大きく、シミュレーション開始時に道路上に既存車両が存在しないウォームアップ問題が強く疑われる。
観測点hit自体はかなり埋まっているため、未到達だけではなく、通過量不足が主問題。
次は単純な iteration 追加より、初期車両配置またはウォームアップ時間の導入を検討する。
```

出力:

```text
results/observation_error_diagnostics_g150_iter40_eval/error_diagnostics_summary.json
results/observation_error_diagnostics_g150_iter40_eval/observation_error_by_point.csv
results/observation_error_diagnostics_g150_iter40_eval/observation_error_by_time.csv
results/observation_error_diagnostics_g150_iter40_eval/top_under_observed_points.csv
results/observation_error_diagnostics_g150_iter40_eval/top_over_observed_points.csv
results/observation_error_diagnostics_g150_iter40_eval/top_absolute_error_points.csv
```

## ウォームアップ時間の導入方針

40 iteration 相当の評価結果では、計測開始を後ろにずらすほど再現率が上がった。

```text
08:00開始: 69.8%
08:05開始: 75.2%
08:10開始: 77.6%
08:15開始: 78.8%
08:20開始: 79.1%
08:25開始: 79.7%
08:30開始: 80.2%
08:35開始: 80.3%
```

解釈:

```text
シミュレーション開始直後は道路上の既存車両がゼロであり、観測点まで到達する前の不足が大きい。
そのため、評価対象の前にウォームアップ時間を置く必要がある。
まずは 10分程度のウォームアップを導入し、08:00 からシミュレーションを開始して、08:10 以降を評価対象にする案を採用候補とする。
```

## 観測点ごとの誤差率分布

時間ごとのデータをそのまま使うと、同じ観測点が複数回現れる。
そこでまずは、観測点ごとに評価対象時間の観測量・シミュレーション量を合計し、以下で誤差率を定義した。

```text
error_rate = (simulated_total - observed_total) / observed_total
```

補助的に、観測点×5分bin単位の誤差率分布も出す。
観測値が0のセルでは誤差率が定義できないため、分布計算からは除外する。

対象:

```text
comparison = results/road_db_training_mesh_uniform_500_g150_packet5_iter40_eval5/iteration_020/evaluation/comparison.csv
start_min = 490
```

summary:

```text
all_simulated_total_ratio 0.7763
positive_simulated_total_ratio 0.7603

observation_error_rate:
  mean -0.2319
  std 0.3446
  p10 -0.6758
  p25 -0.4667
  p50 -0.2227
  p75 -0.0233
  p90 0.1297
  p95 0.2146

under_observation_count 218
over_observation_count 70
```

解釈:

```text
10分ウォームアップ相当で見ても、観測点ごとの誤差率中央値は -22.3% で過小側に寄っている。
一方で p90 は +13.0%、p95 は +21.5% であり、一部の観測点では過大も出ている。
分布は正規分布的な左右対称ではなく、過小側に長い。
```

出力:

```text
results/observation_error_distribution_g150_iter40_warmup10/error_rate_distribution_summary.json
results/observation_error_distribution_g150_iter40_warmup10/observation_error_rate_distribution.svg
results/observation_error_distribution_g150_iter40_warmup10/row_error_rate_distribution.svg
results/observation_error_distribution_g150_iter40_warmup10/observation_error_rates.csv
results/observation_error_distribution_g150_iter40_warmup10/time_bin_error_rate_summary.csv
results/observation_error_distribution_g150_iter40_warmup10/row_error_rates.csv
```

## 観測誤差の地図可視化

過小・過大観測点の地域的な偏りを見るため、10分ウォームアップ相当の観測点別誤差率を地図上に表示するビューアを追加した。

対象:

```text
error_rates = results/observation_error_distribution_g150_iter40_warmup10/observation_error_rates.csv
start_min = 490
```

色:

```text
青: 過小
赤: 過大
橙: ほぼ一致
```

点の大きさ:

```text
abs(error_rate) が大きいほど大きい。
```

出力:

```text
viewer/observation_error_map.html
viewer/observation_error_map.js
viewer/data/observation_error_map.json
```

URL:

```text
http://127.0.0.1:8010/observation_error_map.html
```

## 近接する過小・過大ペアの可視化

非常に近い観測点なのに、一方が過大・一方が過小になっているケースを確認するため、観測点間距離で逆符号ペアを抽出した。

条件:

```text
source = viewer/data/observation_error_map.json
max_distance_meter = 150
min_abs_error_rate = 0.1
```

結果:

```text
opposite-sign close pair count = 20
distance_min = 1.01m
distance_median = 36.2m
distance_max = 141.88m
error_rate_gap_median = 0.5487
error_rate_gap_max = 2.6305
```

上位例:

```text
大手門 / 坂下門前:
  distance 32.95m
  over +220.0%
  under -43.0%

新宿五 / 新宿五東:
  distance 14.68m
  over +21.3%
  under -51.9%

小伝馬町 / 馬喰町:
  distance 29.72m
  over +53.4%
  under -31.0%

門前仲町 / 永代二:
  distance 3.17m
  over +34.5%
  under -24.0%
```

解釈:

```text
近接逆符号ペアは、地域的な発生不足だけでは説明しにくい。
候補原因は、上下線・接続方向の割当、分岐確率の局所的な偏り、packet化による経路集中、または観測点マッチングの微妙なズレ。
特に同一道路近傍のペアでは、方向別交通量をうまく分けられているかを確認する必要がある。
```

出力:

```text
viewer/observation_error_pair_map.html
viewer/observation_error_pair_map.js
viewer/data/observation_error_pair_map.json
```

## 観測点と directed_edge 対応の可視化

各観測点がどの `directed_edge` に対応しているかを確認するため、対応edgeと進行方向矢印を表示するビューアを追加した。

表示内容:

```text
背景道路:
  topology edge の道路線。

対応directed_edge:
  観測点に割り当てられた directed_edge を太い線で表示。

矢印:
  directed_edge の shape_points の順序に沿って描画。

観測点→edge:
  観測点座標から matched_link.nearest_point へ破線で接続。
```

summary:

```text
observation_count = 300
matched_directed_edge_count = 289
match_confidence:
  high = 255
  medium = 33
  low = 12
```

出力:

```text
viewer/observation_edge_assignment_map.html
viewer/observation_edge_assignment_map.js
viewer/data/observation_edge_assignment_map.json
```

URL:

```text
http://127.0.0.1:8011/observation_edge_assignment_map.html
```

## 同一 directed_edge ペアによるマッチング補正

4146 小伝馬町と 4147 馬喰町で、同じ `directed_edge` にかなり近い位置でマッチしているにもかかわらず、誤差が過小と過大に分かれている例を確認した。

補正前:

```text
4146 小伝馬町:
  directed_edge = directed_edge_005862
  observed_total = 477
  simulated_total = 329
  error_rate = -31.0%

4147 馬喰町:
  directed_edge = directed_edge_005862
  observed_total = 208
  simulated_total = 319
  error_rate = +53.4%
```

この2点の距離は約29.7mで、従来の `near_pair_threshold_meter = 25` ではペア制約の対象外だった。
しかし同じ `directed_edge` に貼られているため、距離に関係なく conflict 候補として扱う方針に変更した。

補正後:

```text
4146 小伝馬町:
  directed_edge = directed_edge_005862
  bearing = 54.4 deg

4147 馬喰町:
  directed_edge = directed_edge_043679
  bearing = 234.4 deg
```

同じ theta と評価 seed で再評価した結果、4147 の 08:10 以降の誤差は以下のように改善した。

```text
補正前:
  observed_total = 208
  simulated_total = 319
  error_rate = +53.4%

補正後:
  observed_total = 208
  simulated_total = 293
  error_rate = +40.9%
```

一方で、4146 は同じ edge のままなので、誤差は変化しない。
この補正は現在のシミュレーションカウント上では改善するが、マッチング規則としては実観測の時間変化、上下線方向、候補edgeの距離を合わせて判断する必要がある。

## 地図境界バッファの可視化

道路DBの切り出し範囲が観測点を十分に包含していない場合、境界付近の観測点では到達可能な上流・下流道路が不足し、観測点カウントや学習フィードバックが不安定になる。
この問題を確認するため、道路DB geometry 全体の bbox から 500m / 1000m 内側の境界線を描画するビューアを追加した。

```text
viewer/observation_boundary_buffer_map.html
viewer/data/observation_boundary_buffer_map.json
```

集計結果:

```text
全観測点数 = 300
評価対象観測点数 = 288

boundary_distance < 500m:
  全観測点 = 14
  評価対象 = 4

boundary_distance < 1000m:
  全観測点 = 27
  評価対象 = 15
```

500m 条件で除外候補になる評価対象観測点:

```text
2885 大島八: boundary_distance = 0.0m
2893 大島八: boundary_distance = 398.3m
595 千登世橋: boundary_distance = 421.1m
4124 神宮橋: boundary_distance = 491.8m
```

この境界条件は、現時点では診断用であり、学習・評価からの除外を自動適用するものではない。

境界バッファビューアには、観測点が対応している `directed_edge` と、その両端ノードに接続する道路edgeも追加した。
既存レイヤーは削除せず、以下をチェックボックスで切り替える。

```text
背景道路
地図境界
500m / 1000m 境界
対応edge
接続edge
矢印
観測点
ラベル
```

現在の出力では、対応edgeは292本、接続edgeは1797本である。

## 指定観測点のマッチング修正

1194 / 1207 / 536 / 449 / 3959 / 3962 / 4183 を確認し、以下の補正を入れた。

```text
初期マッチング:
  最近傍が細街路で、近くに幹線道路候補がある場合は幹線候補へ寄せる。

ペア制約:
  反対方向だけでなく、道路種別、edge端、距離をスコアに含める。

通過判定:
  edge終端にある観測点を取りこぼさないよう、終端位置を通過判定に含める。

手動補正:
  dataset-specific な観測点を、可視確認に基づいて暫定補正する。公開版では具体的な観測点ID・edge IDは省略する。
```

修正後の 08:10 以降の確認結果:

```text
449 特定観測点（公開版では名称を省略）:
  directed_edge = 補正先 directed_edge（公開版では具体IDを省略）
  observed/simulated = 324 / 355
  error_rate = +9.6%

536 入船橋:
  directed_edge = directed_edge_056860
  observed/simulated = 264 / 92
  error_rate = -65.2%

1194 緑三:
  directed_edge = directed_edge_022822
  observed/simulated = 258 / 85
  error_rate = -67.1%

1207 菊川駅前:
  directed_edge = directed_edge_022675
  observed/simulated = 295 / 194
  error_rate = -34.2%

3959 曙橋:
  directed_edge = directed_edge_039894
  observed/simulated = 382 / 35
  error_rate = -90.8%

3962 住吉町:
  directed_edge = directed_edge_047393
  observed/simulated = 311 / 364
  error_rate = +17.0%

4183 渋谷警察署前:
  directed_edge = directed_edge_070125
  observed/simulated = 274 / 105
  error_rate = -61.7%
```

4183 はマッチング自体ではなく、edge終端 `position_ratio = 1.0` の通過判定漏れが主因だった。
端点を通過判定に含めたことで、simulated_total は 0 から 105 に増えた。

境界バッファビューアでは、対応edgeと接続edgeを hover 時に描画する設定を追加した。
デフォルトでは hover 時のみ表示し、必要に応じてチェックボックスで常時表示へ切り替える。

観測点番号検索も追加した。
番号を入力して `Show point` を押すと、該当観測点だけを表示し、表示位置を自動で中央へ寄せる。
複数番号は空白またはカンマ区切りで入力できる。
