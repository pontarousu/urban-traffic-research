# 技術判断メモ

> このファイルは研究中の詳細な技術判断ログです。初見の場合は先に `docs/README.md`、`docs/research_timeline.md`、`docs/spec.md`、`docs/experiment_summary.md` を読んでください。

このメモは、順方向交通シミュレーション + 分岐確率学習プロジェクトで、現時点で合意した設計方針を記録するものです。

## 目的

このプロジェクトの主目的は、観測断面交通量に近づくように、車両の移動アルゴリズムを学習・補正することです。

現段階では、入口重みや発生量を学習対象にせず、交差点での分岐確率に集中します。

```text
固定するもの:
  発生総量
  入口 Way の重み
  消滅条件の基本ルール

学習対象:
  交差点における次 Way 選択確率
```

## 順方向シミュレーションの基本構造

順方向シミュレーションは、以下のイベントで構成します。

1. 車両発生
2. 道路上の移動
3. 交差点での分岐
4. 観測点通過の記録
5. 車両消滅

観測点データは、車両を直接生成する命令としては使いません。観測値は、発生量のスケール決定、評価、分岐確率のフィードバックに使います。

## 観測総量の定義

観測総量は、次の定義を採用します。

```text
観測総量 O_t =
  対象領域内の観測点について、
  時刻 t の 5 分交通量を合計したもの
```

式で書くと以下です。

```text
O_t = sum(observed_count[obs_i, t])
```

ここでの観測総量は、ユニークな車両数ではありません。同じ車両が複数の観測点を通過した場合、複数回カウントされます。

したがって、観測総量は「対象領域内で観測された延べ断面通過台数」として扱います。

## 発生台数

5 分ごとの発生台数は、観測総量の倍率で決めます。

```text
発生台数 N_t = generation_multiplier * O_t
```

初期構想では、以下を候補にしていました。

```text
generation_multiplier = 1.5
```

理由は、今回の観測データが主要道路の断面交通量であり、都市内の全車両数を表しているわけではないためです。

現在の road DB ベース実装では、この値を「その5分枠で追加するフロー量」として使います。

```text
requested_spawn_t = generation_multiplier * O_t
```

ここで `O_t` は延べ断面通過台数であり、ユニーク車両数ではありません。
したがって、`generation_multiplier = 1.0` は「観測断面の延べ通過台数と同数の車を発生させる」という意味であって、「真の都市内車両需要に一致する」という意味ではありません。

最終的な値は、固定値として 1 に決め打ちしません。
まずは以下を見ながら段階的に決めます。

```text
simulated_total_ratio = simulated_total / observed_total
観測点到達率
active_vehicle_avg / active_vehicle_max
渋滞・滞留の発生
theta 学習の安定性
```

現在の小規模・少台数実験では `generation_multiplier = 0.03` を使っています。
これは学習ループと可視化を軽く検証するための値であり、最終値ではありません。
今後は `0.1 -> 0.3 -> 0.7 -> 1.0 -> 1.5` のように段階的に上げて確認します。

この値は現段階では学習対象にしません。

## 入口 Way の扱い

入口 Way の重みは、初期段階では学習対象にしません。

理由は、入口重みと分岐確率を同時に学習すると、観測誤差が改善したときに、改善要因が発生場所なのか移動アルゴリズムなのか分からなくなるためです。

初期段階では、入口 Way はルールベースで選びます。現在の第一候補は「対象領域の境界にある幹線道路からの流入」です。

ただし、幹線道路だけから車両を発生させると、都市交通として不自然になります。そのため、発生源は最初から複数カテゴリに分けます。

```text
boundary_major:
  対象領域の境界にある幹線道路からの流入

boundary_minor:
  対象領域の境界にある非幹線道路からの流入

internal:
  対象領域内部からの発生
```

発生源カテゴリの配分比率は、初期段階では固定します。これは分岐確率の学習に集中するための仮定であり、交通需要を正確に推定したものではありません。

初期配分の候補:

```text
boundary_major: 0.60
boundary_minor: 0.25
internal:       0.15
```

この配分は学習対象にしません。観測誤差が改善したとしても、この段階では入口重みや発生源配分が正しいことを意味しません。

入口候補の例:

- 対象領域の境界付近にある Way
- 道路種別が大きい Way
- 車線数が多い Way
- 速度制限が高い Way
- 領域内へ流入しやすい向きの Way

幹線道路の判定には、OSM の `road_type` と `lane_count` の両方を使います。`motorway`, `trunk`, `primary`, `secondary` などの道路種別を優先しつつ、車線数が多い Way も高く評価します。

入口重みの初期案:

```text
source_weight ∝ road_type_weight * lane_count * speed_weight * boundary_score
```

内部発生の場合は、境界スコアではなく内部発生候補としての妥当性を使います。

```text
internal_weight ∝ road_type_weight * lane_count * speed_weight * local_access_score
```

`local_access_score` は、接続数、容量、行き止まりでないこと、観測点に近すぎないことなどから作る候補です。

重要な注意として、これらの入口選択ルールと重みはハードコーディングされた近似です。現段階では、発生場所の正確性を保証するものではありません。将来的には、入口重みや発生源カテゴリ配分も推定対象または学習対象にする余地があります。

ただし、入口 Way の抽出ルールはまだ確定していません。特に以下を設計する必要があります。

- 幹線道路をどの `road_type` まで含めるか
- 対象領域の境界をどう定義するか
- Way の向きが領域外から領域内へ向いているかをどう判定するか
- 入口候補が少なすぎる場合の補完方法
- 入口候補が多すぎる場合の絞り込み方法
- `boundary_major`, `boundary_minor`, `internal` の固定配分比率

## 分岐確率の単位

分岐確率は、交差点ノードだけでなく、進入 Way も含めて持ちます。

```text
(node_id, incoming_way_id) -> outgoing_way_id の確率分布
```

理由は、同じ交差点でも、どの方向から入ってきたかによって直進・左折・右折の候補と自然な選択確率が変わるためです。

内部パラメータは、確率そのものではなく `theta` として持ちます。

```text
theta[node_id, incoming_way_id, outgoing_way_id]
```

実際の分岐確率は、候補 outgoing Way に対して softmax を取って得ます。

```text
P(outgoing_way | node, incoming_way) = softmax(theta)
```

この形にすると、確率が負になる問題や、合計が 1 にならない問題を避けられます。

## 観測誤差の定義

観測点ごと・時間帯ごとの誤差は以下で定義します。

```text
error[obs_i, t] = observed_count[obs_i, t] - simulated_count[obs_i, t]
```

意味は以下です。

```text
error > 0:
  シミュレーションが観測より少ない。
  その観測点へもっと車を流したい。

error < 0:
  シミュレーションが観測より多い。
  その観測点へ流れる車を減らしたい。
```

## 分岐確率へのフィードバック

初期段階では、車両の通過履歴を使う `trace-based feedback` を採用します。

各車両について、以下を記録します。

```text
branch_trace:
  どの時刻に
  どの node に入り
  どの incoming_way から
  どの outgoing_way を選んだか

observation_trace:
  どの時刻に
  どの観測点を通過したか
```

シミュレーション後、ある分岐を通った車両が、その後どの観測点を通過したかを集計します。

```text
downstream_influence[branch, obs] =
  その branch を通った車両のうち、
  後で obs を通過した割合
```

そして、観測誤差を使って `theta` を更新します。

```text
delta_theta =
  learning_rate
  * downstream_influence[branch, obs]
  * normalized_error[obs, t]
```

不足している観測点に流れやすい分岐は強め、過剰な観測点に流れやすい分岐は弱めます。

### trace-based feedback の初期設定

観測誤差の正規化は、以下を採用します。

```text
normalized_error =
  (observed_count - simulated_count)
  / max(observed_count, minimum_volume)
```

初期値:

```text
minimum_volume = 10
```

これにより、交通量の大きい観測点だけが更新を支配することを避けます。また、観測値が 0 に近い場合でも更新量が不安定になりにくくします。

分岐履歴のうち、観測点通過に対して責任を戻す範囲は、直近 5 回の分岐までに制限します。

```text
max_trace_back_steps = 5
```

古い分岐ほど観測点通過への直接的な関係が弱くなるため、時間差に応じて影響を減衰させます。

```text
time_decay = exp(-delta_time_sec / tau)
tau = 300
```

1 台の車両が複数の観測点を通過した場合は、観測点通過イベントごとにフィードバックします。ただし、1 台の車両が更新を支配しないように、車両単位の総フィードバック量に上限を設けます。

```text
vehicle_feedback_cap = 1.0
```

`theta` の更新率は、初期段階では小さく設定します。

```text
learning_rate = 0.05
```

1 回の反復で分岐確率が急激に変わることを避けるため、`theta` の更新量をクリップします。

```text
delta_theta_clip = 0.2
```

分岐確率が極端に偏ることを防ぐため、正則化を入れます。

```text
regularization_strength = 0.01
```

これは各反復で `theta` を少し 0 に戻す処理として実装します。

```text
theta *= (1 - regularization_strength)
```

また、softmax 後の分岐確率には下限を設けます。

```text
min_branch_probability = 0.02
```

この下限により、ある候補 Way の確率が完全に 0 に近づき、その後の探索ができなくなることを防ぎます。

初期実装では、以下の値を採用します。

```text
minimum_volume = 10
max_trace_back_steps = 5
tau = 300
vehicle_feedback_cap = 1.0
learning_rate = 0.05
delta_theta_clip = 0.2
regularization_strength = 0.01
min_branch_probability = 0.02
```

## 消滅条件

消滅条件は、初期実装では以下を採用します。

- 次の Way がない場合は消滅
- 次の Way が容量上限で入れない場合は消滅
- 5分枠ごとの `target_active_cars` を上回る場合は、差分を整理する
- シミュレーション終了時に残っている車両は終了扱い

`target_active_cars` 超過時の整理では、観測点をまだ通っていない車、かつ分岐回数が多い車を優先して消します。これは「観測点を満たすのに邪魔になりにくい車」を消すための暫定ルールです。

ただし、この消滅ルールも自然な交通現象を厳密に表しているわけではありません。将来的には待ち行列、領域外流出、最大走行時間などをより明示的に扱う必要があります。

現在の road DB ベース実装では、容量上限による即時消滅と `target_active_cars` 超過整理は使っていません。
車両は、次 edge がない、最大走行時間を超える、またはシミュレーション終了まで残る、という形で終了します。

## 評価指標

初期実装では、反復ごとに以下を記録します。

- 観測点ごとの MAE
- 全観測点・全時間帯の MAE
- RMSE
- Bias
- 観測合計とシミュレーション合計の差
- 学習前後の誤差改善率
- 発生台数
- 整理台数
- 平均アクティブ車両数
- 更新された分岐数
- `theta` の最大更新量

全体合計だけが合っていても、場所ごとの再現性が低ければ成功とは見なしません。

主指標は MAE とします。まずは、均等分岐に近い初期状態よりも MAE が下がるかを確認します。

## 実装ファイル構成

分岐確率学習の最小実装は、以下の構成で進めます。

```text
src/preprocess.py
  小領域データを作成する。
  発生源候補を boundary_major, boundary_minor, internal_major, internal_minor に分類する。

src/branch_policy.py
  theta を保持し、softmax によって分岐確率を計算する。

src/simulate_forward.py
  順方向シミュレーションを実行する。
  車両発生、移動、分岐、観測点通過、消滅を扱う。
  分岐 trace と観測点通過 trace を出力する。

src/feedback_trainer.py
  観測誤差と車両 trace から theta を更新する。

src/run_training.py
  simulate -> evaluate -> update theta を複数回反復する。

src/compare_observed.py
  観測値とシミュレーション値を比較する。
```

出力先:

```text
results/training/iteration_metrics.csv
results/training/final_branch_theta.json
results/training/final_simulation_counts.csv
results/training/final_comparison.csv
results/training/final_traces.json
```

## 初期実装の検証結果

OSM ベースの小領域データで、分岐確率 `theta` の反復更新が実行できることを確認しました。

標準設定:

```text
中心観測点: obs_300C_2010 財務省上
時間帯: 480 分から 510 分まで
ノード数: 2519
Way 数: 3913
観測点数: 10
generation_multiplier: 1.5
```

5 iteration の結果:

```text
iteration=0 mae=51.283 rmse=64.946 sim_total=680
iteration=1 mae=50.417 rmse=63.625 sim_total=736
iteration=2 mae=51.633 rmse=64.835 sim_total=671
iteration=3 mae=51.383 rmse=65.296 sim_total=696
iteration=4 mae=50.967 rmse=63.958 sim_total=693
```

学習ループは動作していますが、MAE は安定して改善していません。現時点では以下が課題です。

- 発生源カテゴリ比率が固定で粗い
- 発生した車両が観測点へ到達する割合が低い
- trace-based feedback の更新信号がまだ弱い
- 境界候補を含めるため、前処理の `max_ways` を 5000 に上げる必要があった
- 観測点到達性を考慮した発生源候補の改善が必要

## 探索強化と混雑速度モデルの試行

観測点通過イベントが少なく、分岐確率 `theta` へ返る学習信号が弱い問題に対して、探索量を増やす試行を行いました。

### 試行した設定

```text
generation_multiplier = 3.0
duration_min = 60
active_cap_multiplier = 2.0
epsilon = 0.2
iterations = 10
```

`epsilon` は、分岐選択時に一様ランダム探索を混ぜる割合です。

```text
P(outgoing) =
  (1 - epsilon) * softmax(theta)
  + epsilon * uniform(outgoing)
```

`epsilon = 0.2` では、80% は現在の `theta` に従い、20% は候補 outgoing Way を一様に探索します。これは事前に正解分岐を与えるものではなく、未探索の分岐を試すための探索項です。

### 容量上限による即消滅の変更

以前の実装では、次の Way が容量上限に達している場合、車両を即消滅させていました。

```text
next_way が容量上限:
  車両を消滅
```

この挙動は観測点に届く前の車両を減らしすぎる可能性があるため、初期試行では廃止しました。

代わりに、Way 上の車両数に応じて走行速度を下げる簡略 BPR 型の速度モデルを採用しました。

```text
occupancy_ratio =
  current_car_count / storage_capacity_cars

current_speed_kmh =
  free_speed_kmh / (1 + 2.0 * occupancy_ratio^4.0)

minimum_speed_kmh = 3.0
```

この変更により、混雑した Way では車両が遅く進みますが、容量超過だけを理由に即消滅することはありません。

### 10 iteration の結果

60分・3倍発生・探索強化・BPR速度モデルで 10 iteration を実行しました。

```text
best iteration: 3
MAE: 49.854
RMSE: 57.174
simulated_total: 7178
improvement_from_baseline: 約 3.3%

last iteration: 9
MAE: 50.507
RMSE: 57.267
simulated_total: 7162
improvement_from_baseline: 約 2.1%
```

観測合計とシミュレーション合計:

```text
observed_total: 9479
simulated_total: 7162
```

発生カテゴリ別の実績:

```text
boundary_major: 4161
boundary_minor: 1067
internal_major: 3827
internal_minor: 1606
```

終了ステータス:

```text
no_next_way: 8723
simulation_end: 1938
```

### 現時点の解釈

容量上限による即消滅は解消されましたが、`no_next_way` が非常に多く残っています。

これは、車両が小領域の切り出し境界や行き止まりに到達し、次に進む Way が見つからず消滅していることを意味します。

今後確認すべきこと:

- `no_next_way` を自然な領域外流出として扱ってよいか
- 観測点へ届く前に境界で消えている車両が多すぎないか
- 小領域の切り出し半径や `max_ways` が十分か
- 発生源カテゴリ比率が観測点到達に対して妥当か
- `duration_min = 60` でも境界流出が多いなら、対象領域を広げるべきか

この試行では、発生量と探索量を増やすことで `simulated_total` は増えましたが、分岐確率学習の改善はまだ限定的です。次は可視化で発生源、流量、観測点誤差、`no_next_way` の位置関係を確認します。

## 道路選択 pattern_2 と balanced 発生の試行

可視化確認により、現状の道路網には `service` などの細街路が多く含まれ、本来シミュレーション対象にすべきでない狭い道へ車両が初期配置される問題が確認されました。

そこで、道路選択を `pattern_2_major_plus` に絞る方針を採用しました。

```text
pattern_2_major_plus:
  採用:
    motorway
    trunk
    primary
    secondary
    tertiary

  条件付き採用:
    unclassified かつ lane_count >= 2
    residential かつ lane_count >= 2

  除外:
    service
    living_street
    その他の細街路
```

`preprocess.py` に `--road-filter` を追加し、実データ生成でも道路フィルタを指定できるようにしました。

実行条件:

```text
road_filter = pattern_2_major_plus
source_pattern = balanced
generation_multiplier = 3.0
duration_min = 60
epsilon = 0.2
active_cap_multiplier = 2.0
iterations = 20
```

balanced 発生比率:

```text
boundary_major: 0.40
boundary_minor: 0.10
internal_major: 0.35
internal_minor: 0.15
```

前処理後のデータ:

```text
中心観測点: obs_300C_4275 馬場先門
ノード数: 904
Way数: 1157
観測点数: 12
```

20 iteration の結果:

```text
iteration 0:
  MAE: 68.049
  RMSE: 79.592
  observed_total: 9479
  simulated_total: 10824

best iteration 19:
  MAE: 65.924
  RMSE: 77.120
  observed_total: 9479
  simulated_total: 10644
  improvement_from_baseline: 約 3.1%
```

上位 iteration:

```text
iteration 19: MAE 65.924
iteration 14: MAE 66.250
iteration 5:  MAE 66.354
iteration 7:  MAE 66.354
iteration 1:  MAE 66.458
```

### 現時点の解釈

`pattern_2_major_plus` により細街路は大きく削減され、道路網は以前より現実的になりました。一方で、今回の結果では `simulated_total` が `observed_total` を上回っており、以前の「過小だけ」の状態とは異なる挙動になっています。

ただし MAE はまだ大きく、全体量が近づいたとしても観測点ごとの分布が合っていない可能性があります。

次に確認すべきこと:

- 可視化で、過大観測点と過小観測点の空間分布を見る
- balanced 発生で内部幹線に偏りすぎていないか確認する
- `generation_multiplier = 3.0` が大きすぎないか確認する
- `pattern_2_major_plus` で観測点 matched Way が自然に残っているか確認する
- 次の実験では `generation_multiplier` を 2.0 から 2.5 程度に下げる可能性がある

## 観測点数ベースの自動半径

中規模実験では、半径を先に固定すると、その範囲に含まれる観測点数が不安定になります。

そのため、前処理に観測点数ベースで半径を決める仕組みを追加しました。

```text
中心観測点を決める
全観測点を中心からの距離で並べる
target_observation_count 番目の観測点までの距離を求める
radius_padding_meter を足す
その半径で道路網を切り出す
```

追加したオプション:

```text
--target-observation-count
--radius-padding-meter
```

`--target-observation-count` を指定した場合、`--radius-meter` は直接使わず、観測点数から `radius_meter` を自動決定します。

中規模データ生成の試行:

```text
road_filter = pattern_2_major_plus
generation_multiplier = 3.0
duration_min = 60
target_observation_count = 50
radius_padding_meter = 200
```

生成結果:

```text
中心観測点: obs_300C_4275 馬場先門
半径: 2051.48 m
ノード数: 4044
Way数: 5000
観測点数: 50
```

道路種別の内訳:

```text
tertiary: 1543
secondary: 1267
motorway: 832
primary: 694
trunk: 615
residential: 31
unclassified: 17
service: 1
```

発生候補数:

```text
boundary_major: 20
boundary_minor: 1
internal_major: 3747
internal_minor: 1232
```

注意点として、今回の設定では `max_ways = 5000` の上限に到達しています。そのため、道路網が途中で切られている可能性があります。

また、boundary 系の発生候補が少ない一方で internal 系が非常に多くなっています。中規模学習を回す前に、以下を検討する必要があります。

- `max_ways` を増やす
- 主要道路を優先しつつ境界 Way を十分に残す抽出順に変える
- boundary 候補が少なすぎる場合の補完ルールを入れる
- internal 候補が多すぎる場合の間引きや重み調整を行う

## max_ways 制限の廃止

中規模以上の実験では、`max_ways` による上限制限が道路網を途中で切断し、余計な行き止まりや発生源候補の偏りを作ることが分かりました。

そのため、`preprocess.py` の `--max-ways` はデフォルトで無制限に変更しました。

```text
max_ways = None
```

指定された場合だけ上限をかけますが、通常の中規模実験では指定しません。

50観測点データを `max_ways` 無制限で再生成した結果:

```text
中心観測点: obs_300C_4275 馬場先門
半径: 2051.48 m
ノード数: 7195
Way数: 9364
観測点数: 50
```

道路種別の内訳:

```text
tertiary: 3483
secondary: 2094
motorway: 1350
primary: 1326
trunk: 1005
residential: 69
unclassified: 36
service: 1
```

発生候補数:

```text
boundary_major: 2638
boundary_minor: 1603
internal_major: 3848
internal_minor: 1275
```

`max_ways = 5000` のときは boundary 候補が極端に少なかったため、無制限化により道路網切断と発生源偏りはかなり改善しています。

## 今後決めること

今後、次の項目を具体化する必要があります。

- 入口 Way の抽出ルール
- 入口 Way の固定重みの計算式
- `downstream_influence` を時間差込みで扱うか
- 誤差の正規化方法
- `theta` の更新率
- 分岐確率が極端になることを防ぐ正則化
- 容量上限時に消滅させるか、待ち行列を作るか
- 何回反復して評価するか

消滅条件と評価方法は、後続の議論で別途確定します。

## 当面の実装方針

次の実装では、現在の `way_score` による分岐をやめ、明示的な分岐確率テーブルを導入します。

実装順序:

1. `(node_id, incoming_way_id, outgoing_way_id)` の候補を列挙する
2. `theta` を均等分岐で初期化する
3. softmax によって分岐確率を計算する
4. 車両ごとに分岐履歴と観測点通過履歴を記録する
5. 観測誤差を計算する
6. trace-based feedback で `theta` を更新する
7. 複数回反復して誤差が下がるか確認する

この段階では機械学習モデルはまだ導入しません。まずは、分岐確率テーブルを反復補正することで、移動アルゴリズムを学習可能な形にします。

## 道路DB移行ロードマップ

これまでの実験では、OSM 由来の細かい node や way を `forward_traffic_ml` 側で直接切り出していました。

しかし、この方式では道路の曲線表現用 node や分岐を持たない node が学習 trace に大量に入り、交差点での分岐確率を学習するという目的から外れやすいことが分かりました。

今後は、`road_database_project/output/prototype_tokyo_core_small` を読み取り専用の道路データ源として使います。`road_database_project` は別プロジェクトとして開発中のため、`forward_traffic_ml` からは変更・移動・上書きしません。

### Phase 1: 道路DB取り込み

`road_database_project` の出力を、順方向シミュレーション用の内部データへ変換します。

利用する主なファイル:

```text
directed_edges.geojson
topology_edges.geojson
topology_nodes.geojson
intersections.geojson
intersection_approaches.geojson
turn_relations.json
```

役割:

```text
directed_edges.geojson:
  車両が走る有向道路リンク。
  directed_edge_id, from_node_id, to_node_id, length_meter, road_type,
  lane_count_total, speed_limit_kmh を使う。

topology_nodes.geojson:
  node_type により intersection, dead_end, direction_change を区別する。

intersections.geojson:
  分岐確率を学習する交差点集合として使う。

intersection_approaches.geojson:
  各交差点に入る incoming directed edge と、出ていく outgoing directed edge を取得する。

turn_relations.json:
  OSM turn restriction に基づく禁止 turn のマスクとして使う。
```

この段階では、`turn_relations.json` は全 turn 候補ではなく、禁止 turn の情報として扱います。

したがって、分岐候補は次の手順で作ります。

```text
1. intersection_approaches.geojson から、交差点ごとに incoming / outgoing を集める
2. 同じ intersection_id 内で incoming x outgoing の候補を作る
3. turn_relations.json にある禁止 turn を候補から外す
4. Uターンは道路を消すのではなく、初期実験では分岐候補から抑制する
```

Phase 1 の実装では、道路DBを毎回直接読むのではなく、`forward_traffic_ml` 側に固定スナップショットを作ります。

```text
road_database_project/output/prototype_tokyo_core_small
  -> forward_traffic_ml/data/road_db_snapshots/<snapshot_id>/
```

道路DB側は今後も開発が続くため、学習や評価ではライブ出力を直接読まず、明示的に作成したスナップショットを使います。

スナップショットには、元ファイルの `sha256`、サイズ、更新時刻を `manifest.json` に記録します。これにより、道路DBが更新されても、過去の学習がどの入力に基づいていたかを再現できます。

スナップショット出力は、ネットワーク計算用と描画用を分けます。

```text
network_core.json:
  シミュレーションと学習が通常読む軽量な中核データ。
  topology_nodes, directed_edges, intersections, branch_options を持つ。
  geometry は持たない。

network_geometry.json:
  描画や観測点マッチング検討で使う形状データ。
  topology_edge, directed_edge, intersection, approach の座標列を持つ。

network_reference.json:
  検査・参照用データ。
  topology_edges, intersection_approaches, turn_relations を持つ。
  通常のシミュレーション実行では必須ではない。

branch_candidates.json:
  incoming x outgoing の全候補。
  Uターンや禁止 turn を含む候補全体を確認するために使う。
```

この分割により、ネットワーク計算では交差点と有向 edge の接続情報だけを読み、地図描画や観測点マッチングを行うときだけ geometry を読む構成にします。

### Phase 2: 観測点の再対応

道路グラフが OSM の細切れ way から `directed_edge` ベースへ変わるため、観測点も新しい道路リンクへ対応付け直す必要があります。

初期案:

```text
観測点の緯度経度
  -> 近傍 directed_edge を探索
  -> 距離、方向、道路種別を使って候補を評価
  -> matched_directed_edge_id と position_ratio を作る
```

観測点対応には信頼度を持たせます。

```text
match_confidence:
  high / medium / low

warning_flags:
  far_from_edge
  ambiguous_parallel_edges
  direction_uncertain
  road_type_mismatch
```

低信頼の観測点は、最初から除外するのではなく、評価時に別集計できるようにします。

#### 近接観測点ペアと時間変化プロファイル

近接する 2 つの観測点は、同一道路の上り線・下り線を別々に見ている可能性があります。
単純な最近傍 `directed_edge` だけで対応付けると、2 点が同じ進行方向へ誤対応するリスクがあります。

初期診断では、以下を可視化してから対応付けルールを決めます。

```text
空間情報:
  2 観測点間の距離
  暫定リンク先 directed_edge の進行方向
  方向差
  同一 directed_edge へ対応していないか

時間変化:
  24 時間の時間別交通量プロファイル
  朝ピーク比率
  夕方ピーク比率
  morning_heavy / evening_heavy / flat の分類
```

ただし、時間変化プロファイルは確定的な正解ラベルではありません。
都心部では道路の性質や地点によって朝夕の偏りが弱い場合が多く、現在の暫定しきい値では `flat` が大半になります。
そのため、最初は「強い朝夕偏りがある観測点ペアだけを補助情報として使う」方針にします。

ペア制約付きマッチングを導入する場合も、観測量の時間変化だけで上り・下りを決め打ちしません。
道路方向、近傍候補、道路種別、車線数、時間変化を合わせて、候補の信頼度を上げるための診断情報として扱います。

#### ペア制約付きマッチングの初期仕様

近接する 2 つの観測点が `direction_conflict` になった場合、両方を同じ `directed_edge` や同じ進行方向へ貼るのを避けます。
対象は、最初は `usable_for_initial_matching == true` の青い観測点だけに限定します。

処理単位:

```text
pair_status == direction_conflict
2 点間距離 <= 25m
左右とも nearest_candidates を持つ
```

候補探索:

```text
left_candidate x right_candidate
各観測点の nearest_candidates 上位 5 件を使う
```

スコア:

```text
score =
  left_distance
  + right_distance
  + abs(180 - direction_diff_deg) * 0.2
  + same_directed_edge_penalty
  + weak_direction_penalty
  + opposite_same_topology_bonus
```

暫定値:

```text
same_directed_edge_penalty = 1000
weak_direction_penalty = 100 if direction_diff_deg < 90
opposite_same_topology_bonus = -20 if same_topology_edge and direction_diff_deg >= 135
```

採用条件:

```text
同一 directed_edge ではない
方向差が 135 度以上
左右候補の距離がどちらも 30m 以下
```

採用できた場合、観測点には以下を付けます。

```text
matched_link
match_method = pair_constrained
match_confidence = high / medium
warning_flags += direction_conflict_resolved
```

採用できない場合は最近傍の `provisional_link` を維持し、以下を付けます。

```text
match_method = nearest
match_confidence = low または既存値
warning_flags += pair_constraint_unresolved
```

時間変化プロファイルは主判定には使いません。
明確に `morning_heavy` と `evening_heavy` が対になる場合だけ、補助的に `volume_profile_supports_opposite` を付けます。

この段階では、ペア単位の局所解として実装します。
同じ観測点が複数の conflict ペアにまたがって矛盾した場合は、無理に全体最適化せず `multi_pair_conflict` として残します。

### Phase 3: 順方向シミュレーションの移行

車両状態は `directed_edge_id` と edge 内の進捗で管理します。

```text
vehicle:
  current_directed_edge_id
  position_meter_on_edge
  speed_kmh
  entered_edge_time_sec
  branch_trace
  observation_trace
```

車両が edge 終端に到達したら、`to_node_id` を見ます。

```text
to_node_id が intersection:
  (intersection_id, incoming_directed_edge_id) に対する outgoing 候補から選択する

to_node_id が direction_change:
  進める edge が一意なら deterministic に通過する

to_node_id が dead_end:
  車両を消滅させる
```

分岐確率学習の対象は、原則として `intersection` のみです。`dead_end` や `direction_change` は学習対象にしません。

### Phase 4: ルールベース学習の再実験

学習パラメータは次の単位で持ちます。

```text
theta[intersection_id, incoming_directed_edge_id, outgoing_directed_edge_id]
```

分岐確率は、候補 outgoing に対して softmax を取って得ます。

```text
P(outgoing | intersection, incoming) = softmax(theta)
```

最初は既存の trace-based feedback を、新しい道路DB構造に移植します。

```text
1. 車両ごとに branch_trace を記録する
2. 観測点通過を observation_trace に記録する
3. 観測誤差を計算する
4. 観測点通過前の直近分岐へ誤差を戻す
5. theta を更新する
6. 複数 iteration で MAE / RMSE / Bias を比較する
```

この段階では、入口重みや発生源配分は引き続き学習対象にしません。まずは、道路DBによって整理された交差点分岐だけで改善するかを確認します。

### Phase 5: 可視化更新

新しい道路DB構造に合わせて可視化を更新します。

表示したいもの:

```text
directed_edges:
  車両が走る道路線

intersections:
  学習対象の交差点

intersection_approaches:
  交差点ごとの incoming / outgoing

turn_relations:
  禁止 turn の位置

observation_points:
  観測点と matched_directed_edge

simulated_flow:
  directed_edge ごとのシミュレーション通過量

branch_probability:
  交差点ごとの分岐確率
```

`intersection_approaches.geojson` はファイルサイズが大きいため、通常のビューアでは必要範囲だけを切り出して表示します。

### Phase 6: 中規模学習

`prototype_tokyo_core_small` の範囲で、観測点数と時間を増やして学習を回します。

初期目安:

```text
duration_min >= 60
iterations >= 50
epsilon = 0.1 - 0.2
generation_multiplier = 3.0 前後
```

評価指標:

```text
MAE
RMSE
Bias
観測点別誤差
時間帯別誤差
学習前後の改善率
```

計算時間が重い場合は、iteration ごとのシミュレーションを並列化できるか確認します。ただし、同じ theta を更新する逐次学習部分は並列化しにくいため、まずはシミュレーション試行や評価処理の並列化を検討します。

### Phase 7: NN化

ルールベースの theta 更新で改善が確認できた後に、分岐スコアの計算をニューラルネットへ置き換えます。

入力特徴量候補:

```text
intersection geometry:
  degree
  incoming / outgoing の角度
  turn_type

road attributes:
  road_type
  lane_count_total
  speed_limit_kmh
  length_meter

time:
  時刻
  曜日
  時間帯

local error context:
  周辺観測点の誤差
  直近 iteration の通過量

movement context:
  incoming_directed_edge
  outgoing_directed_edge
```

出力は outgoing 候補ごとのスコアとし、softmax によって分岐確率に変換します。

```text
score = NN(features)
P(outgoing | intersection, incoming) = softmax(score)
```

NN化の前に、観測点マッチング、分岐候補生成、trace 記録、評価指標が安定していることを確認します。

## Phase 3 実装状況

road DB ベースの最小順方向シミュレーションを追加しました。

詳細は [phase3_road_db_forward_simulation.md](phase3_road_db_forward_simulation.md) に記録します。

追加ファイル:

```text
src/road_db_network_loader.py
src/road_db_forward_simulator.py
src/run_road_db_simulation.py
src/compare_road_db_counts.py
```

現時点で確認済み:

```text
directed_edge 上の車両移動
branch_options による分岐
matched_link による観測点通過判定
branch_trace / observation_trace の出力
simulation_counts.csv と観測値の比較
```

初回の小規模検証では、`matched_edges` 発生モードで観測点通過イベントが出ることを確認しました。
`major` 発生モードでは観測点到達が少ないため、次に発生源設計を改善する必要があります。

## Phase 4 実装状況

trace-based feedback による theta 更新の最小実装を追加しました。

詳細は [phase4_trace_feedback_training.md](phase4_trace_feedback_training.md) に記録します。

追加ファイル:

```text
src/road_db_theta_policy.py
src/road_db_feedback_trainer.py
src/run_road_db_training.py
```

現時点で確認済み:

```text
iteration ごとに seed を変えて simulation を実行
comparison から feedback_error を計算
車両の observation_trace から直近5分岐へ誤差を戻す
theta を更新し、clamp / regularization を適用
iteration_metrics.csv を出力
backtrace_diagnostics.csv と backtrace_summary.csv を出力
```

初回 smoke training では、5 iteration で theta が 3862 個まで更新されました。
5分岐 backtrace は平均で約270-290m、24秒前後に相当します。

各 iteration の theta 更新後に固定 `eval_seed` で evaluation run を実行する仕組みも追加しました。
これにより、training seed の乱数差ではなく、theta 更新後の挙動変化を同じ発生条件で比較できます。

距離ベース backtrace も試行しました。
従来の「直近5分岐」ではなく、観測点から上流 1000m 以内の分岐へ距離減衰付きで誤差を戻す方式です。

```text
backtrace_mode = distance
max_backtrace_distance_meter = 1000
backtrace_decay_meter = 350
min_backtrace_weight = 0.05
```

この方式では更新対象 theta が大きく増え、観測点が疎な領域にも学習信号を届けやすくなりました。
ただし、10 iteration の最終評価では直近5分岐方式より安定して良いとはまだ言えません。
時間規模を広げる前後で、learning_rate と距離減衰の調整を続けます。

40分スケールでも distance backtrace の学習を確認しました。

```text
duration_min = 40
iterations = 5
source_mode = observation_upstream
upstream_min_distance_meter = 300
upstream_max_distance_meter = 1000
generation_multiplier = 0.03
backtrace_mode = distance
```

固定seed評価では、iteration 1 から 5 にかけて `eval_mae` が 56.587 から 56.480 へ下がり、
`eval_simulated_total` は 2354 から 2615 へ増えました。
theta は clamp に達しておらず、40分条件では実行上の破綻は見られません。
ただし全体の再現率はまだ約2%で、発生量と発生位置の検討は引き続き必要です。

## メッシュ発生方式

観測点上流発生だけでは、観測点密度が高い地域や発生位置近傍に学習作用が偏る。
そのため、観測点ではなく道路網をもとに対象領域をメッシュ化し、メッシュ単位では一様に車両を発生させる方式を追加する。

初期仕様:

```text
source_mode = mesh_uniform
mesh_size_meter = 500
```

方式:

```text
1. directed_edge の中点を 500m メッシュに割り当てる
2. 発生候補 edge が存在するメッシュだけを使う
3. メッシュごとの総発生重みは一様にする
4. メッシュ内では道路種別、車線数、速度、長さで edge を重み付けする
5. edge 上の発生位置は端点付近を避けてランダムに置く
```

メッシュ内 edge 重み:

```text
edge_weight =
  road_type_weight
  * lane_weight
  * speed_weight
  * sqrt(length_meter)
```

この方式では、`internal_major` や `boundary_major` を直接決める代わりに、まず空間密度を制御する。
道路種別や車線数は、メッシュ内でどの道路に置くかの重みとして使う。

最初の確認条件:

```text
start_min = 480
duration_min = 40
generation_multiplier = 0.03
source_mode = mesh_uniform
mesh_size_meter = 500
```

初期発生位置の確認結果:

```text
spawn_vehicle_count = 3975
spawn_edge_count = 3054
spawn_mesh_count = 471
vehicles_with_observation_trace = 640
```

観測点上流発生より観測点通過数は下がる。
これは想定通りであり、メッシュ発生は空白地帯にも車両を流す代わりに、観測点到達率が下がる。
学習に使う場合は、`generation_multiplier` を段階的に上げるか、観測点上流発生との混合を検討する。

実際に `generation_multiplier = 0.03` と `0.1` で training を実行した。

```text
mesh_uniform g003:
  eval_simulated_total_ratio 0.0090
  eval_mae 57.043
  eval_hit_rows 770

mesh_uniform g010:
  eval_simulated_total_ratio 0.0317
  eval_mae 55.846
  eval_hit_rows 1590
```

`mesh_uniform g010` は、同じ40分条件の `observation_upstream g003` より MAE が良く、更新 intersection 数も広がった。
ただし再現量はまだ小さいため、今後は `generation_multiplier` の増加、または `mesh_uniform` と `observation_upstream` の混合を比較する。

## 車両パケット化

再現量を上げると計算量が増えるため、複数台を1つの代表車両として扱う方式を追加しました。

```text
vehicle_packet_size = 1:
  従来通り、1 trace が1台を表す。

vehicle_packet_size = 5:
  1 trace が最大5台を代表する。
```

観測点通過量は `vehicle.weight` で加算し、feedback も `vehicle.weight` を掛けて戻します。
最初の実装では、代表車両は分岐時に分割せず、packet 全体が同じ outgoing edge を選びます。

比較結果:

```text
packet_size = 1:
  avg_iteration_runtime_sec 19.395
  last_eval_mae 55.875
  last_eval_hit_rows 1574

packet_size = 5:
  avg_iteration_runtime_sec 5.070
  last_eval_mae 56.007
  last_eval_hit_rows 705
```

`packet_size = 5` は約3.8倍高速ですが、hit_rows が減るため、空間的な探索量は落ちます。
今後 `generation_multiplier` を 0.3 以上に上げる試行では、まず `packet_size = 5` を使い、必要に応じて `packet_size = 2` や分岐時 split を検討します。

## generation_multiplier = 0.3 の試行

`mesh_uniform` の発生量不足を確認するため、`vehicle_packet_size = 5` のまま `generation_multiplier` を `0.3` に上げた。

```text
generation_multiplier = 0.3
vehicle_packet_size = 5
duration_min = 40
iterations = 5
base_seed = 9600
eval_seed = 19601
```

結果:

```text
avg_iteration_runtime_sec = 14.724
last_eval_mae = 52.777
last_eval_simulated_total_ratio = 0.0903
last_eval_hit_rows = 1294
last_theta_nonzero_count = 34307
```

`generation_multiplier = 0.1, packet_size = 5` と比べると、計算時間は約2.9倍に増えたが、MAE、観測点到達、theta 更新範囲はいずれも改善した。
ただし観測総量に対する再現量はまだ約9%であり、今後も発生量を段階的に上げる必要がある。

## generation_multiplier = 0.5 の試行

`generation_multiplier = 0.3` で改善が見られたため、同じ条件で `0.5` まで上げた。

```text
generation_multiplier = 0.5
vehicle_packet_size = 5
duration_min = 40
iterations = 5
base_seed = 9600
eval_seed = 19601
```

結果:

```text
avg_iteration_runtime_sec = 22.213
last_eval_mae = 49.497
last_eval_simulated_total_ratio = 0.1546
last_eval_hit_rows = 1649
last_theta_nonzero_count = 40004
```

`generation_multiplier = 0.3` と比べると、計算時間は約1.5倍に増えたが、MAE、観測点到達、theta 更新範囲はいずれも改善した。
5 iteration の範囲では eval_mae がまだ下がり続けているため、学習は頭打ちではない。
一方で、再現量は観測総量の約15.5%にとどまっており、絶対量はまだ不足している。

## generation_multiplier = 0.75 の試行

`generation_multiplier = 0.5` でも再現量が不足していたため、同じ条件で `0.75` を試した。

```text
generation_multiplier = 0.75
vehicle_packet_size = 5
duration_min = 40
iterations = 5
base_seed = 9600
eval_seed = 19601
```

結果:

```text
avg_iteration_runtime_sec = 35.706
last_eval_mae = 45.933
last_eval_simulated_total_ratio = 0.2251
last_eval_hit_rows = 1833
last_theta_nonzero_count = 45500
```

`generation_multiplier = 0.5` と比べると、計算時間は約1.6倍に増えたが、MAE、再現量、hit_rows、theta 更新範囲はいずれも改善した。
ただし、1 iteration が約36秒になっており、評価付きで多数 iteration を回すには重い。
今後は、学習中の評価頻度を下げる、または評価を別ジョブに分ける構成を検討する。

## generation_multiplier = 1.0 / 1.5 の試行

観測総量に対する再現量 50% 程度を目標に、`generation_multiplier = 1.0` と `1.5` を試した。

```text
vehicle_packet_size = 5
duration_min = 40
iterations = 5
base_seed = 9600
eval_seed = 19601
```

結果:

```text
generation_multiplier = 1.0:
  avg_iteration_runtime_sec = 41.420
  last_eval_mae = 42.858
  last_eval_simulated_total_ratio = 0.2913
  last_eval_hit_rows = 1944
  last_theta_nonzero_count = 48314

generation_multiplier = 1.5:
  avg_iteration_runtime_sec = 67.884
  last_eval_mae = 37.507
  last_eval_simulated_total_ratio = 0.4280
  last_eval_hit_rows = 2089
  last_theta_nonzero_count = 53697
```

`generation_multiplier = 1.5` でも再現量は約42.8%であり、50%には届かなかった。
単純外挿では `generation_multiplier = 1.7` 前後が次の候補になる。
ただし、`g = 1.5` では 1 iteration が約68秒になり、評価付きで長期学習を回すには重い。
今後は評価頻度削減、発生位置改善、または packet split を含む高速化を検討する。

## active vehicle と発生抑制の計測

`vehicle_packet_size > 1` では、シミュレーション内部の active 数は実車台数ではなく packet 数になる。
そのため、`max_active_vehicles` が発動したかを判断しやすいように、training metrics に以下を追加した。

```text
scheduled_spawn_count:
  本来その run で発生予定だった代表前の車両台数。

spawned_count:
  実際に発生できた代表前の車両台数。

dropped_spawn_count:
  max_active_vehicles 制約などにより発生できなかった台数。

active_packet_avg / active_packet_max:
  active な packet 数の平均・最大。

active_vehicle_weight_avg / active_vehicle_weight_max:
  packet weight を合計した実車換算 active 台数の平均・最大。
```

`dropped_spawn_count = 0` であれば、少なくとも発生予定台数は削られていない。
`active_packet_max` と `active_vehicle_weight_max` を併せて見ることで、packet 数としての混雑と実車換算の混雑を分けて確認する。

## 評価頻度の制御

長い iteration を回す場合、毎 iteration 固定seed評価を行うと計算時間が大きく増える。
そのため `run_road_db_training.py` に `--eval-interval` を追加した。

```text
--eval-interval 1:
  従来通り、毎 iteration 評価する。

--eval-interval 5:
  5 iteration ごと、および最終 iteration で評価する。

--eval-interval 0:
  最終 iteration のみ評価する。
```

iteration metrics には `evaluated` を出力する。
評価を実行しない iteration では `eval_*` 系の列は空になる。

## generation_multiplier = 1.5 の長めの学習

`generation_multiplier = 1.5` で20 iterationまで学習を延長した。
評価は `--eval-interval 5` により、5 iterationごとに固定seedで実行した。

```text
generation_multiplier = 1.5
vehicle_packet_size = 5
duration_min = 40
iterations = 20
eval_interval = 5
```

固定seed評価:

```text
iteration 5:
  eval_mae = 37.507
  eval_simulated_total_ratio = 0.4280
  eval_hit_rows = 2089

iteration 10:
  eval_mae = 35.156
  eval_simulated_total_ratio = 0.4780
  eval_hit_rows = 2136

iteration 15:
  eval_mae = 32.920
  eval_simulated_total_ratio = 0.5251
  eval_hit_rows = 2157

iteration 20:
  eval_mae = 31.251
  eval_simulated_total_ratio = 0.5719
  eval_hit_rows = 2184
```

20 iteration によって、固定seed評価で再現量50%を超えた。
`dropped_spawn_count = 0` であり、発生予定台数は削られていない。
最終 `theta_max` は約0.99で、現時点では clamp 上限には遠いが、今後は分岐確率の偏りを確認する。

## theta の再開学習

各 iteration の `theta.json` と、最終状態の `theta_final.json` を保存している。
20 iteration 実験では以下が続き学習の開始点になる。

```text
results/road_db_training_mesh_uniform_500_g150_packet5_iter20_eval5/theta_final.json
```

`run_road_db_training.py` に `--initial-theta` を追加した。
これにより、保存済み theta を初期値として追加 iteration を実行できる。

例:

```text
python3 src/run_road_db_training.py \
  --initial-theta results/road_db_training_mesh_uniform_500_g150_packet5_iter20_eval5/theta_final.json \
  --output-dir results/road_db_training_mesh_uniform_500_g150_packet5_iter40_eval5 \
  --iterations 20 \
  --eval-interval 5 \
  ...
```

この場合、出力先の iteration 番号は新しい run 内で `1` から始まる。
意味としては「20 iteration 後の theta から追加で20 iteration学習する」扱いになる。

## theta 分岐確率の偏り分析

`src/analyze_theta_probabilities.py` を追加した。
学習済み theta を読み込み、各 `(node, incoming_edge)` に対する outgoing 確率を `softmax(theta)` と `epsilon` から計算する。

20 iteration 後の分析結果:

```text
theta = results/road_db_training_mesh_uniform_500_g150_packet5_iter20_eval5/theta_final.json
epsilon = 0.2
branch_group_count = 56450
theta_nonzero_count = 70990
theta_min = -0.9896
theta_max = 0.9896
theta_abs_mean = 0.0468

max_probability_avg = 0.4791
max_probability_p50 = 0.5000
max_probability_p90 = 0.5090
max_probability_p95 = 0.5244
max_probability_p99 = 0.6135
max_probability_max = 0.7062

highly_biased_group_count_p70 = 3
highly_biased_group_count_p80 = 0
highly_biased_group_count_p90 = 0
```

現時点では、最大確率が0.7を超える分岐グループは3件のみで、0.8以上はない。
したがって、20 iteration 後の theta は極端に一方向へ潰れている状態ではない。

出力:

```text
results/theta_probability_analysis_g150_iter20/theta_probability_summary.json
results/theta_probability_analysis_g150_iter20/theta_probability_rows.csv
results/theta_probability_analysis_g150_iter20/top_biased_branches.csv
```

## generation_multiplier = 1.5 の追加学習

20 iteration 後の theta から再開し、さらに20 iterationを追加した。
これにより累計40 iteration相当の学習結果を確認した。

```text
initial_theta = results/road_db_training_mesh_uniform_500_g150_packet5_iter20_eval5/theta_final.json
generation_multiplier = 1.5
vehicle_packet_size = 5
duration_min = 40
iterations = 20
eval_interval = 5
```

固定seed評価:

```text
cumulative iteration 25:
  eval_mae = 29.270
  eval_simulated_total_ratio = 0.6150
  eval_hit_rows = 2190

cumulative iteration 30:
  eval_mae = 28.454
  eval_simulated_total_ratio = 0.6463
  eval_hit_rows = 2203

cumulative iteration 35:
  eval_mae = 27.040
  eval_simulated_total_ratio = 0.6851
  eval_hit_rows = 2206

cumulative iteration 40:
  eval_mae = 26.463
  eval_simulated_total_ratio = 0.6980
  eval_hit_rows = 2207
```

40 iteration相当では再現量が約69.8%まで上がった。
80%目標には届いていないが、MAE、相関、hit_rows は改善した。
`dropped_spawn_count = 0` であり、発生抑制は発動していない。

theta 確率偏り:

```text
max_probability_p95 = 0.5385
max_probability_p99 = 0.6801
max_probability_max = 0.8013
highly_biased_group_count_p70 = 430
highly_biased_group_count_p80 = 20
highly_biased_group_count_p90 = 0
```

20 iteration時点より偏りは強くなったが、0.9以上の極端な分岐はまだない。
次に続ける場合は、再現率だけでなく、過大推定地点と分岐確率の偏りを合わせて確認する。

## 40 iteration 評価の誤差診断

40 iteration 相当の固定seed評価に対して、`src/diagnose_observation_errors.py` で誤差診断を行った。

```text
comparison = results/road_db_training_mesh_uniform_500_g150_packet5_iter40_eval5/iteration_020/evaluation/comparison.csv
output_dir = results/observation_error_diagnostics_g150_iter40_eval
```

全体:

```text
simulated_total_ratio = 0.6980
error_total = -40015
under_row_count = 1687
over_row_count = 587
zero_simulated_row_count = 97
under_observation_count = 257
over_observation_count = 30
```

主要な解釈:

```text
過大より過小が支配的。
特に最初の5分binが大きく不足している。
08:00-08:05 の ratio は 0.304 で、error_total は -11103。
08:10以降は ratio が 0.72 から 0.80 程度まで上がる。
```

この結果から、80%未達の主因は「観測点に全く届かない」だけではなく、開始直後の車両不足と一部観測点の通過量不足である可能性が高い。
次に検討する候補は、単純な iteration 追加ではなく、ウォームアップ時間または初期車両配置である。

## ウォームアップ時間の扱い

40 iteration 相当の評価結果を使い、計測開始時刻を5分ずつ遅らせて再集計した。

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

この結果から、開始直後の不足は大きく、ウォームアップ時間を導入する必要がある。
暫定方針として、まずは10分ウォームアップを採用候補とする。

```text
simulation_start = 08:00
evaluation_start = 08:10
```

ただし、評価開始を後ろにずらすほど評価対象bin数が減るため、80%超えだけをもって全体改善とは判断しない。

## 観測点ごとの誤差率分布

誤差率分布は `src/plot_observation_error_distribution.py` で出力する。
時間方向は、まず観測点ごとに評価対象時間を合計して扱う。

```text
error_rate = (simulated_total - observed_total) / observed_total
```

10分ウォームアップ相当、つまり `time_min >= 490` での結果:

```text
all_simulated_total_ratio = 0.7763
positive_simulated_total_ratio = 0.7603

observation_error_rate mean = -0.2319
observation_error_rate std = 0.3446
observation_error_rate p50 = -0.2227
observation_error_rate p90 = 0.1297
observation_error_rate p95 = 0.2146

under_observation_count = 218
over_observation_count = 70
```

観測点単位の分布は正規分布的な左右対称ではなく、過小側に寄っている。
今後は、全体再現率だけでなく、誤差率分布の中央値・分散・過小側tailも評価指標に含める。

## 観測誤差の地図可視化

観測点別の誤差率を地図上にプロットするビューアを追加した。

```text
viewer/observation_error_map.html
viewer/data/observation_error_map.json
```

地図では、過小を青、過大を赤、ほぼ一致を橙で表示する。
点の大きさは `abs(error_rate)` に対応する。
これにより、過小・過大が特定地域に偏っているかを確認する。

## 近接する逆符号観測点ペア

近い位置にあるにもかかわらず、一方が過小・一方が過大になっている観測点ペアを抽出するビューアを追加した。

```text
viewer/observation_error_pair_map.html
viewer/data/observation_error_pair_map.json
```

抽出条件:

```text
max_distance_meter = 150
min_abs_error_rate = 0.1
```

結果:

```text
pair_count_all = 20
distance_median = 36.2m
error_rate_gap_median = 0.5487
```

このタイプの誤差は、単なる地域的な発生不足だけでは説明しにくい。
上下線対応、観測点マッチング、局所的な分岐確率、packet化による経路集中を疑う。

## 観測点と directed_edge 対応の矢印付き可視化

各観測点がどの `directed_edge` に対応しているかを確認するため、対応edgeを進行方向矢印付きで表示するビューアを追加した。

```text
viewer/observation_edge_assignment_map.html
viewer/data/observation_edge_assignment_map.json
```

表示内容:

```text
背景道路:
  道路DBの geometry を薄い線で表示

対応 directed_edge:
  観測点に割り当てられた directed_edge を太い橙色の線で表示

進行方向:
  directed_edge の shape_points の順序に沿って矢印を表示

対応関係:
  観測点から matched point までを破線で表示

観測点:
  warmup 後の誤差率に応じて過小を青、過大を赤、ほぼ一致を橙で表示
```

このビューアは、観測点マッチングの妥当性を確認するための診断用であり、現時点ではマッチング計算そのものは変更しない。

## 同一 directed_edge 観測点ペアの補正

近接距離だけでペア判定すると、同じ道路上に少し離れて配置された上下線ペアを見落とす可能性がある。
そのため、観測点ペアの検出条件に「同じ `directed_edge` に暫定マッチしていること」を追加した。

この判定では、観測点間距離に関係なく、同じ `directed_edge` に複数観測点が貼られていれば conflict 候補として扱う。
conflict になったペアは、既存の反対方向候補探索に渡し、同一 `directed_edge` への重複割当を避ける。

4146 小伝馬町 / 4147 馬喰町では、両方が `directed_edge_005862` に貼られていた。
補正後は以下の対応にした。

```text
4146 小伝馬町:
  directed_edge_005862
  bearing = 54.4 deg

4147 馬喰町:
  directed_edge_043679
  bearing = 234.4 deg
```

現行 theta と同じ評価 seed で確認したところ、08:10 以降の 4147 の誤差率は `+53.4%` から `+40.9%` に改善した。
ただし、この改善は現在のシミュレーション結果に依存するため、一般化したマッチング規則としては、実観測の時間変化や上下線方向の整合性も併用して判断する。

## 地図境界バッファによる観測点診断

道路DBの範囲が観測点範囲を十分に包含していない場合、境界付近の観測点では上流・下流の道路が切れてしまい、分岐学習では説明できない過小誤差が発生する。
そのため、道路DB geometry 全体の bbox から内側 500m / 1000m の境界線を可視化し、観測点の境界距離を診断する。

```text
viewer/observation_boundary_buffer_map.html
viewer/data/observation_boundary_buffer_map.json
```

現在の道路DBでは、評価対象観測点について以下の結果になった。

```text
boundary_distance < 500m:
  excluded_evaluation_count = 4
  included_evaluation_count = 284

boundary_distance < 1000m:
  excluded_evaluation_count = 15
  included_evaluation_count = 273
```

この条件は、現段階では除外を即時適用するものではなく、境界影響を受けている可能性が高い観測点を診断するためのものとする。

ビューアは、既存の表示機能を削らずにレイヤーを追加していく方針とする。
情報量が多い場合は、チェックボックスやフィルタで表示対象を選択できるようにする。

境界バッファビューアには、観測点の対応 `directed_edge` と、その両端ノードに接続する `directed_edge` を追加した。

```text
matched_edge_count = 292
connected_edge_count = 1797
```

接続edgeは、観測点の対応edgeの `from_node_id` / `to_node_id` に接続する directed edge として定義する。
対応edge、接続edge、矢印はそれぞれ表示ON/OFFできる。

## 観測点マッチングの端点・道路種別補正

観測点マッチングで以下の問題が見つかったため、暫定補正を追加した。

```text
1. service / residential などの細街路に吸われる
2. position_ratio が 0.0 / 1.0 付近の edge 端へ貼られる
3. ペア制約が反対方向だけを優先し、距離や道路種別を無視して不自然なedgeへ飛ぶ
```

対応:

```text
初期マッチング:
  最近傍が非幹線で、近くに primary / trunk / secondary がある場合は幹線候補を優先する。

ペア制約:
  反対方向だけでなく、道路種別ペナルティと edge端ペナルティをスコアに入れる。

通過判定:
  edge終端の観測点も通過として拾えるように、target <= next_position を許容する。

暫定手動補正:
  公開版では dataset-specific な観測点ID・edge IDは省略
```

この補正後、指定観測点の 08:10 以降のカウントは以下になった。

```text
449 特定観測点（公開版では名称を省略）:
  補正先 directed_edge（公開版では具体IDを省略）
  observed/simulated = 324 / 355
  error_rate = +9.6%

536 入船橋:
  directed_edge_056860
  observed/simulated = 264 / 92
  error_rate = -65.2%

4183 渋谷警察署前:
  directed_edge_070125
  observed/simulated = 274 / 105
  error_rate = -61.7%
```

449 の手動補正は、可視化と現行シミュレーション通過量に基づく暫定対応であり、恒久ルールではない。

境界バッファビューアでは、対応edgeと接続edgeを常時表示すると情報量が多すぎるため、デフォルトでは観測点に hover した時だけ描画する。
チェックボックスを外せば、従来通り可視観測点すべての対応edgeを表示できる。

観測点番号を入力して対象観測点だけを表示する検索機能を追加した。
複数番号は空白またはカンマ区切りで入力できる。
検索中は該当観測点だけを表示し、その観測点の対応edgeと接続edgeも表示対象にする。

## 最小RL学習の検証仕様

trace-based feedback から強化学習へ進む前段階として、NNなしの `theta table + REINFORCE風 update` を追加した。
目的は、観測断面交通量を報酬として使ったときに、交差点の分岐確率 `theta` を安定して更新できるかを確認することである。

採用する仕様:

```text
reward:
  観測点・5分bin単位
  reward = - abs((simulated - observed) / max(observed, 1))

baseline:
  iteration 内の全 reward 平均

advantage:
  reward - baseline

境界リスク観測点:
  道路DB bbox 境界から 1000m 未満の観測点は除外
  reward計算、学習、評価から外す

match_confidence:
  reward weight には使わない

探索:
  epsilon のみ
  entropy は使わない
```

境界1000m除外は、信頼度を下げる重み付けではなく、対象観測点集合を明確に切るための条件として扱う。
これは、地図切り出し範囲不足という入力データ側の問題を、RL側の重み調整で吸収しないためである。

`match_confidence` は学習重みに使わない。
自動スコア上の距離や順位が、人の目で見た対応の自然さと一致しないケースがあるため、confidence 設計に学習結果を依存させない。

実装ファイル:

```text
src/road_db_rl_trainer.py
src/run_road_db_rl_training.py
```

検証条件:

```text
source_mode = mesh_uniform
mesh_size_meter = 500
generation_multiplier = 1.5
vehicle_packet_size = 5
start_min = 480
duration_min = 40
warmup_min = 10
epsilon = 0.2
eval_interval = 5
```

smoke run では、境界1000m除外により対象観測点が 288 から 273 に減った。
除外された15点は `excluded_boundary_observations.csv` に出力する。

最小RLの20 iterationを compact 出力で実行した。

```text
results/road_db_rl_minimal_mesh_uniform_500_g150_packet5_iter20_boundary1000_compact
```

固定seed評価の warmup 後再現率:

```text
iteration 5:  0.540
iteration 10: 0.689
iteration 15: 0.826
iteration 20: 0.935
```

固定seed評価の warmup 後 MAE:

```text
iteration 5:  36.783
iteration 10: 36.072
iteration 15: 36.928
iteration 20: 37.759
```

再現率は大きく改善したが、MAEは iteration 10 付近で最小になり、その後はやや悪化した。
現時点の最小RLは、過小だった全体通過量を増やす方向には強く働く一方、観測点別の配分改善はまだ不十分である。

観測点別baselineも実装して試行した。

```text
baseline_mode = observation
output = results/road_db_rl_observation_baseline_mesh_uniform_500_g150_packet5_iter20_boundary1000_compact
```

固定seed評価の warmup 後結果:

```text
iteration 5:
  simulated_total_ratio = 0.446
  MAE = 38.817
  Bias = -32.454

iteration 10:
  simulated_total_ratio = 0.453
  MAE = 38.300
  Bias = -32.044

iteration 15:
  simulated_total_ratio = 0.495
  MAE = 37.719
  Bias = -29.593

iteration 20:
  simulated_total_ratio = 0.504
  MAE = 36.664
  Bias = -29.027
```

観測点別baselineは、観測点ごとの相対的な良し悪しを見るため、global baseline と比べて全体過小を押し上げる作用が弱い。
その結果、MAEはglobal baselineの20 iterationより少し良いが、再現率は50%程度で止まり、Biasも大きく過小のままだった。

原因の考察:

```text
1. 全体過小の信号が観測点別baselineに吸収される

   各観測点で全時間帯が同じように過小な場合、
   observation_baseline 自体も低い reward になる。
   その結果、reward - baseline が小さくなり、
   「もっと車を流す」方向の advantage が弱くなる。

2. warmup後の評価binが少ない

   今回は warmup 後が 6 bin であり、
   観測点別平均との差分だけでは学習信号が小さくなりやすい。

3. 低交通量・外れ値観測点でbaselineが極端になる

   error_rate = (simulated - observed) / max(observed, 1)
   reward = -abs(error_rate)

   のため、observed が小さい観測点で過大になると、
   観測点別baselineが極端に小さくなる。
```

この結果は、global baseline と observation baseline が逆の性質を持つことを示している。

```text
global baseline:
  全体量を押し上げる力が強い
  ただし観測点別配分が崩れやすい

observation baseline:
  観測点別配分の暴走を抑えやすい
  ただし全体過小を押し上げる力が弱い
```

次の候補:

```text
mixed_auto baseline:
  baseline =
    (1 - lambda) * global_baseline
    + lambda * observation_baseline

  lambda は固定値にせず、iteration ごとに自動更新する。

または:
  reward に全体過小を補正する項を追加する
```

## mixed_auto baseline の実装方針

固定の混合比を手で選ぶと職人的な調整になりやすいため、最初の実装では全観測点共通の `lambda` を iteration ごとに更新する。

`lambda` の意味:

```text
lambda = 0.0:
  global baseline のみ

lambda = 1.0:
  observation baseline のみ
```

各 iteration の reward サンプルから、`advantage = reward - baseline` のばらつきが小さくなる `lambda_raw` を最小二乗で推定する。
ただし、観測点別baselineを同じサンプルで作って同じサンプルに当てると、`lambda_raw` が数式上ほぼ1.0へ寄る。
そのため、lambda 推定時だけは対象行自身を除いた観測点平均を使う。

```text
lambda_raw =
  sum((reward - global_baseline) * (observation_baseline[o] - global_baseline))
  / sum((observation_baseline[o] - global_baseline)^2)
```

ただし、`lambda` が急変すると学習が不安定になるため、以下を入れる。

```text
baseline_lambda_initial = 0.0
baseline_lambda_smoothing = 0.2
baseline_lambda_max_step = 0.1
baseline_min_samples = 100
```

`baseline_min_samples` に満たない場合や、観測点別baselineがglobal baselineとほぼ同じで分母が0になる場合は、`lambda` を更新しない。

実装上は以下の mode を追加した。

```text
baseline_mode = mixed_fixed:
  --baseline-lambda を固定の observation baseline 重みとして使う。

baseline_mode = mixed_auto:
  iteration ごとに --baseline-lambda-initial から始めた lambda を更新する。
```

ログには、現在使った `baseline_lambda`、推定値 `rl_mixed_baseline_lambda_raw`、次回値 `rl_mixed_baseline_lambda_next`、`rl_advantage_mean`、`rl_advantage_std` を残す。

## mixed_auto baseline 20 iteration 結果

`mixed_auto` を、既存の global / observation baseline と同じ条件で20 iteration実行した。

```text
baseline_mode = mixed_auto
iterations = 20
duration_min = 40
warmup_min = 10
generation_multiplier = 1.5
vehicle_packet_size = 5
source_mode = mesh_uniform
eval_interval = 5
```

出力:

```text
results/road_db_rl_mixed_auto_mesh_uniform_500_g150_packet5_iter20_boundary1000_compact
```

固定seed評価の warmup 後結果:

```text
iteration 5:
  lambda = 0.2583
  eval_warmup_simulated_total_ratio = 0.5489
  eval_warmup_mae = 36.006
  eval_warmup_bias = -26.426

iteration 10:
  lambda = 0.3335
  eval_warmup_simulated_total_ratio = 0.6776
  eval_warmup_mae = 35.427
  eval_warmup_bias = -18.888

iteration 15:
  lambda = 0.2908
  eval_warmup_simulated_total_ratio = 0.7862
  eval_warmup_mae = 35.613
  eval_warmup_bias = -12.523

iteration 20:
  lambda = 0.2768
  eval_warmup_simulated_total_ratio = 0.9177
  eval_warmup_mae = 38.145
  eval_warmup_bias = -4.823
```

比較:

```text
global baseline 20 iteration:
  eval_warmup_simulated_total_ratio = 0.9355
  eval_warmup_mae = 37.759
  eval_warmup_bias = -3.780

observation baseline 20 iteration:
  eval_warmup_simulated_total_ratio = 0.5044
  eval_warmup_mae = 36.664
  eval_warmup_bias = -29.027

mixed_auto baseline 20 iteration:
  eval_warmup_simulated_total_ratio = 0.9177
  eval_warmup_mae = 38.145
  eval_warmup_bias = -4.823
```

解釈:

```text
mixed_auto は、global baseline と同程度に総量を押し上げることはできた。
ただし iteration 20 では MAE が悪化しており、総量再現を強めすぎて観測点別配分が崩れている可能性がある。
iteration 10-15 では MAE が比較的低く、再現率も 68%-79% まで上がっているため、停止タイミングや総量ペナルティの導入が次の検討点になる。
```

## ファイル整理方針

`results` 配下の容量が大きくなりすぎたため、実験再現に必要な軽量ファイルを残し、車両単位の詳細traceや一時診断ファイルは削除対象にする。

残すファイル:

```text
iteration_metrics.csv
training_config.json
theta_final.json
iteration_*/theta.json
iteration_*/comparison.csv
iteration_*/comparison_summary.json
iteration_*/simulation_counts.csv
boundary_filter_summary.json
excluded_boundary_observations.csv
```

削除対象:

```text
vehicle_traces.json
backtrace_diagnostics.csv
rl_diagnostics.csv
*.bak*
```

理由:

```text
vehicle_traces.json:
  車両1台またはpacket単位の詳細履歴で、再計算可能。
  過去run全体で約37GBを占める。

backtrace_diagnostics.csv:
  分岐フィードバックの詳細行で、集計結果は iteration_metrics.csv と backtrace_summary.csv に残っている。
  過去run全体で約2.8GBを占める。

rl_diagnostics.csv:
  最小RLの初期試行で全件保存してしまった診断ファイル。
  compact版では保存しない設計に変更済み。

*.bak*:
  実装途中の一時バックアップ。
  主要な技術決定は現在のmdに統合済み。
```

重要な実験結果は以下に集約して残す。

```text
trace feedback 40 iteration:
  results/road_db_training_mesh_uniform_500_g150_packet5_iter40_eval5
  eval_warmup_simulated_total_ratio = 0.698
  eval_warmup_mae = 26.463

最小RL 20 iteration:
  results/road_db_rl_minimal_mesh_uniform_500_g150_packet5_iter20_boundary1000_compact
  eval_warmup_simulated_total_ratio = 0.935
  eval_warmup_mae = 37.759
```

この整理では、実験の比較に必要な指標とthetaは残し、巨大な詳細ログのみ削る。

## no_outgoing 直前 edge への固定ペナルティ

NW方向の到達率低下を調べたところ、観測点が少ない領域では `no_next_edge` で終了する車両が多かった。
これに対して、まずは複雑な downstream 探索ではなく、直近の構造だけを見る固定ペナルティを導入した。

仕様:

```text
対象:
  outgoing edge の先に次の outgoing が存在しない場合、
  その outgoing edge を選ぶ score に固定ペナルティを加える。

適用範囲:
  NWだけではなく全域。

適用位置:
  softmax前の score。

式:
  score = theta + structural_penalty
  structural_penalty = no_outgoing_penalty if next outgoing がない else 0

今回の試行値:
  no_outgoing_penalty = -1.0
```

この方法は、確率そのものを固定するものではない。
theta の学習は残したまま、初期状態から行き止まり方向を選びにくくする構造 prior として扱う。

実装箇所:

```text
src/road_db_network_loader.py
  RoadDbNetwork.choose_next_edge
  structural_penalty_for_outgoing

src/road_db_forward_simulator.py
  run_road_db_simulation(..., no_outgoing_penalty)

src/road_db_rl_trainer.py
  policy_log_gradient 内の softmax 確率計算

src/run_road_db_rl_training.py
  --no-outgoing-penalty
```

検証条件:

```text
baseline_mode = mixed_auto
source_mode = mesh_uniform
generation_multiplier = 1.5
vehicle_packet_size = 5
duration_min = 40
warmup_min = 10
iterations = 20
eval_interval = 5
boundary_exclude_meter = 1000
no_outgoing_penalty = -1.0
```

出力:

```text
results/road_db_rl_mixed_auto_no_outgoing_penalty_m100_mesh_uniform_500_g150_packet5_iter20_boundary1000_compact
```

固定seed評価の warmup 指標:

```text
ペナルティなし mixed_auto:
  iter 5:  ratio=0.5489, MAE=36.006, Bias=-26.426
  iter 10: ratio=0.6776, MAE=35.427, Bias=-18.888
  iter 15: ratio=0.7862, MAE=35.613, Bias=-12.523
  iter 20: ratio=0.9177, MAE=38.145, Bias=-4.823

no_outgoing_penalty = -1.0:
  iter 5:  ratio=0.6879, MAE=33.893, Bias=-18.279, no_next_weight_ratio=0.8549
  iter 10: ratio=0.8860, MAE=35.339, Bias=-6.677,  no_next_weight_ratio=0.8498
  iter 15: ratio=1.0594, MAE=38.377, Bias=3.482,   no_next_weight_ratio=0.8497
  iter 20: ratio=1.1781, MAE=40.473, Bias=10.432,  no_next_weight_ratio=0.8527
```

解釈:

```text
no_outgoing ペナルティは、再現量を早く押し上げる効果はある。
iteration 10 時点では ratio=0.886 で、目標としていた80%以上を超えた。

ただし no_next_weight_ratio は 0.85 前後からほとんど下がっていない。
つまり、今回の固定ペナルティは「袋小路終了そのものを大きく減らす」効果は弱い。

20 iteration まで回すと過大側に振れ、MAEも悪化する。
この条件では iteration 10 前後で止める、または総量過大を抑える reward / early stopping が必要。
```

暫定判断:

```text
直近 no_outgoing edge への固定ペナルティは、簡単な構造 prior として有用。
ただし、これだけで空白地帯や袋小路問題を解決するものではない。
次は「再現率を80%-100%程度に保ちながら、観測点別MAEを下げる」方向で、
early stopping、総量過大ペナルティ、または発生分布の再調整を検討する。
```
