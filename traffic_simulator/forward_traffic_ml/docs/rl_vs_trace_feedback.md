# 強化学習と現行 trace feedback の違い

## 目的

このメモは、現行の `trace-based feedback` と、今後検討する強化学習ベースの分岐確率学習の違いを整理するためのものです。

結論として、どちらも車両の trace を使う。
違いは、trace を使って `theta` を直接ルールで更新するのか、報酬を最大化する policy 更新として扱うのかにある。

## 現行 trace feedback

現行方式では、車両が観測点を踏んだあと、その車両が過去に通った分岐履歴へ観測誤差を戻す。

```text
車両が観測点を通過
↓
観測点ごとの observed / simulated を比較
↓
過小なら、その観測点へ来た trace を増やす方向へ theta 更新
過大なら、その観測点へ来た trace を減らす方向へ theta 更新
```

基本的な考え方:

```text
error = simulated - observed

error < 0:
  過小。もっと車を流したい。

error > 0:
  過大。車を流しすぎている。
```

この方式は直感的で、現在のシミュレータと相性がよい。
一方で、更新式はかなりルールベースである。

現行方式の特徴:

```text
更新対象:
  theta table

更新根拠:
  観測点誤差を分岐履歴へ戻す手作りルール

主な調整項:
  learning_rate
  error_floor
  distance decay
  delta clip
  theta min / max
```

## 強化学習として見る場合

強化学習では、交差点での分岐選択を「行動」として扱う。
その行動の結果として観測交通量に近づいたかどうかを「報酬」として評価する。

```text
交差点で分岐を選ぶ
↓
車両が移動する
↓
観測点交通量との差を計算する
↓
良かった分岐選択の確率を上げる
悪かった分岐選択の確率を下げる
```

## 用語

```text
state:
  状態。分岐判断に使う情報。
  例: 交差点ID、進入edge、出口候補、道路種別、車線数、速度、時刻。

action:
  行動。今回の場合は、どの outgoing edge へ進むか。

policy:
  方策。状態から各行動の選択確率を出す関数。
  今の theta table も、softmax を通せば policy と見なせる。

reward:
  報酬。行動の良し悪しを表す数値。
  観測交通量に近づくほど高く、遠ざかるほど低くする。

episode:
  1回のシミュレーション実行。
  例: 08:00-08:40 を1回走らせる。

trajectory:
  車両の軌跡。発生から消滅までの分岐履歴と観測点通過履歴。

log probability:
  選んだ行動の確率の対数。
  policy gradient では、この値を使って「選んだ行動の確率をどう変えるか」を計算する。

baseline:
  報酬の基準値。
  報酬そのものではなく、平均より良いか悪いかを見るために使う。

advantage:
  reward - baseline。
  平均よりどれだけ良かったかを表す。

entropy:
  確率分布のばらけ具合。
  低すぎると特定の道に固定され、探索が止まる。
```

## 今の trace と RL trace の違い

trace を保存する点は同じ。
違いは、trace に含めたい情報と、更新の意味である。

現行 trace:

```text
どの分岐を通ったか
どの観測点を踏んだか
観測点までの距離
```

RL trace:

```text
どの分岐を選んだか
その時の選択確率
log probability
どの観測点を踏んだか
その観測点から得た reward
```

現行方式:

```text
観測誤差
→ trace に沿って theta を直接増減する
```

RL方式:

```text
観測誤差
→ reward を作る
→ reward が高い行動の選択確率を上げる
→ reward が低い行動の選択確率を下げる
```

## theta table での最小RL

最初からNNに行かず、現在の `theta` を policy parameter と見なす。

分岐確率:

```text
P(outgoing | intersection, incoming) = softmax(theta)
```

車両がある分岐で action `a` を選ぶ。
そのときの確率を `P(a)` とする。

報酬が正なら、選んだ action の確率を上げる。
報酬が負なら、選んだ action の確率を下げる。

REINFORCE風の更新:

```text
theta[action] += learning_rate * advantage * weight * (1 - P(action))
theta[other]  -= learning_rate * advantage * weight * P(other)
```

ここで、

```text
advantage = reward - baseline
weight = 観測点から分岐までの距離減衰
```

現行方式とかなり似た形になるが、確率分布全体を考慮している点が違う。

## 報酬の初期案

観測点 `o` の誤差を以下で定義する。

```text
error_rate[o, t] = (simulated[o, t] - observed[o, t]) / max(observed[o, t], error_floor)
```

車両が観測点を踏んだ場合の報酬:

```text
reward = -abs(error_rate[o, t])
```

意味:

```text
simulated が observed に近い:
  reward は 0 に近い。

simulated が observed から遠い:
  reward は負に大きくなる。
```

この報酬だけでは「過小なので増やす」と「過大なので減らす」の方向を直接持たない。
現在の最小RLでは、baseline との差で「相対的に良かった trace」を強める設計として扱っている。
ただし、この報酬設計は単純すぎる可能性があり、今後は過小・過大の方向を別項で持たせる案も検討する。

## 現行方式との比較

| 観点 | 現行 trace feedback | 強化学習 |
|---|---|---|
| trace | 使う | 使う |
| 更新対象 | theta | policy parameter |
| 更新根拠 | 手作りルール | reward 最大化 |
| 選択確率の扱い | 弱い | 明示的に使う |
| 平均より良い/悪い | 扱いにくい | baseline / advantage で扱う |
| 探索維持 | epsilon が中心 | entropy も使える |
| NN化 | 接続しにくい | 自然に接続できる |

## mixed_auto baseline

固定の mixed baseline は、global baseline と observation baseline の混合割合を人が決める必要がある。
この割合を職人的な調整値にしないため、最初の実装では全観測点共通の `lambda` を iteration ごとに自動更新する。

定義:

```text
baseline[o] =
  (1 - lambda) * global_baseline
  + lambda * observation_baseline[o]
```

ここで、

```text
lambda = 0.0:
  global baseline のみ。

lambda = 1.0:
  observation baseline のみ。
```

`lambda` は、その iteration の reward サンプルから、`reward - baseline` のばらつきが小さくなる値を推定する。
ただし、観測点別 baseline を同じサンプルで作って同じサンプルに当てると、最小二乗の性質で `lambda_raw` が1.0へ寄りやすい。
そのため実装では、lambda 推定時だけ、その行自身を除いた観測点平均を使う。

```text
lambda_raw =
  sum((reward - global_baseline) * (observation_baseline[o] - global_baseline))
  / sum((observation_baseline[o] - global_baseline)^2)
```

その後、`0.0 - 1.0` に丸める。
急に値が変わると学習が不安定になるため、移動平均と最大変化幅で制限する。

```text
lambda_next =
  lambda_current
  + smoothing * (lambda_raw - lambda_current)

lambda_next は 1 iteration あたり max_step までしか動かさない。
```

初期設定:

```text
baseline_mode = mixed_auto
baseline_lambda_initial = 0.0
baseline_lambda_smoothing = 0.2
baseline_lambda_max_step = 0.1
baseline_min_samples = 100
```

サンプル数が `baseline_min_samples` 未満の場合は、観測点別 baseline を信用しすぎないため、`lambda` を更新しない。

ログとして以下を `iteration_metrics.csv` に残す。

```text
baseline_lambda
rl_mixed_baseline_lambda_raw
rl_mixed_baseline_lambda_next
rl_mixed_baseline_lambda_status
rl_advantage_mean
rl_advantage_std
```

この方式の狙いは、global baseline の全体補正力を残しつつ、観測点別 baseline をどの程度信用するかを reward から自動推定すること。
最初は全観測点共通の `lambda` とし、必要になったら観測点ごとの `lambda[o]` に拡張する。

## NNへ進む場合

NNを使う場合、theta table を直接教師にするのは避ける。
それは rule-based theta の模倣になり、ルールの限界を超えにくい。

NN policy の形:

```text
features(intersection, incoming, outgoing, time)
→ NN
→ score
→ softmax
→ 分岐確率
```

NNの更新:

```text
loss = - advantage * log_probability
```

`loss` は小さくしたい値。
報酬が平均より良い行動は、log probability が大きくなるように更新される。
報酬が平均より悪い行動は、log probability が小さくなるように更新される。

## 最小RL構成のたたき台

まずはNNなしで、theta table を使う。

```text
policy:
  theta table + softmax

episode:
  start_min = 480
  duration_min = 40
  warmup_min = 10

source:
  mesh_uniform
  generation_multiplier = 1.5
  vehicle_packet_size = 5

reward:
  warmup 後の観測点 error_rate から作る
  reward = -error_rate

credit assignment:
  backtrace_mode = distance
  max_backtrace_distance_meter = 1000
  backtrace_decay_meter = 350

baseline:
  まずは全 observation event の平均 reward

update:
  REINFORCE風 theta update
  learning_rate は現行より小さめから始める
  theta_min / theta_max は維持

evaluation:
  各iterationごとに固定 eval_seed で再実行
```

## 最初に決めるべきこと

実装前に最低限、以下を決める必要がある。

```text
1. reward を観測点単位にするか、車両単位に集約するか
2. baseline を全体平均にするか、観測点別平均にするか
3. 境界リスク観測点を reward から外すか、重みを下げるか
4. 手動補正点や match_confidence を reward weight に使うか
5. entropy を最初から入れるか、epsilon だけで始めるか
6. 現行 trace feedback と同じ条件で比較する評価セット
```

## 推奨

最初の実装では、NNを使わずに `theta table + REINFORCE風 update` を作る。
目的は、NNの前に reward 設計と credit assignment が交通シミュレーション上で機能するかを確認することである。

この段階で現行 trace feedback より悪い場合、NNへ進んでも問題が解決しない可能性が高い。
逆に、theta table RL が現行方式と同等以上に動けば、NN policy へ置き換える根拠になる。

## 最小RL検証仕様

最初の検証では、観測点マッチング信頼度や境界補正を複雑に扱わず、使う観測点を明確に絞ったうえで、交差点分岐の `theta` をRLで更新できるかを見る。

```text
reward:
  観測点・5分bin単位
  reward = - abs((simulated - observed) / max(observed, 1))

baseline:
  各iterationの全 reward 平均

advantage:
  reward - baseline

境界リスク観測点:
  道路DB bbox 境界から 1000m 未満の観測点は除外
  reward計算、学習、評価のすべてから外す

match_confidence:
  reward weight には使わない
  high / medium のような自動信頼度で学習重みを変えない

探索:
  epsilon のみ
  entropy は入れない

policy:
  P = (1 - epsilon) * softmax(theta) + epsilon * uniform
```

この構成では、境界付近の問題はRL側で重みを下げて吸収しない。
道路DBの切り出し範囲が足りない観測点は、学習対象から外すことで扱う。

`match_confidence` も使わない。
距離が近いことが必ず正しい対応を意味するわけではなく、手動補正やペア制約で少し遠いedgeへ対応させた点が低信頼とは限らないためである。

## 実装

最小RL用に以下を追加した。

```text
src/road_db_rl_trainer.py
  reward / baseline / advantage を作り、
  REINFORCE風の theta delta を計算する。

src/run_road_db_rl_training.py
  道路DBシミュレーションを反復実行し、
  最小RL更新と固定seed評価を行う。
```

比較条件は現行 trace feedback と揃える。

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

境界1000m除外後の現在の対象観測点数:

```text
除外前 = 288
除外後 = 273
除外数 = 15
```

## 最小RL 20 iteration 実行結果

compact 出力で最小RLを20 iteration実行した。

```text
出力:
  results/road_db_rl_minimal_mesh_uniform_500_g150_packet5_iter20_boundary1000_compact

条件:
  source_mode = mesh_uniform
  mesh_size_meter = 500
  generation_multiplier = 1.5
  vehicle_packet_size = 5
  start_min = 480
  duration_min = 40
  warmup_min = 10
  boundary_exclude_meter = 1000
  eval_interval = 5
```

固定seed評価の warmup 後結果:

```text
iteration 5:
  simulated_total_ratio = 0.540
  MAE = 36.783
  Bias = -26.970

iteration 10:
  simulated_total_ratio = 0.689
  MAE = 36.072
  Bias = -18.227

iteration 15:
  simulated_total_ratio = 0.826
  MAE = 36.928
  Bias = -10.170

iteration 20:
  simulated_total_ratio = 0.935
  MAE = 37.759
  Bias = -3.780
```

解釈:

```text
再現率:
  iterationが進むにつれて大きく改善した。
  warmup後の固定seed評価では 0.54 -> 0.94 まで上がった。

MAE:
  iteration 10 付近が最小で、その後はやや悪化した。
  これは単に通過量を増やす方向には学習できているが、
  観測点別の配分最適化はまだ弱いことを示す。

Bias:
  大きな過小からほぼ中立に近づいた。
```

この結果から、最小RLは「車を観測点へ届かせる方向」には十分に機能している。
一方で、観測点ごとの誤差配分を改善するには、reward設計またはbaseline設計を次に見直す必要がある。

## 観測点別baseline実験

global baseline の次に、観測点別baselineを試した。

```text
出力:
  results/road_db_rl_observation_baseline_mesh_uniform_500_g150_packet5_iter20_boundary1000_compact

変更点:
  baseline_mode = observation

その他条件:
  global baseline 実験と同一
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

global baseline との比較:

```text
global baseline iteration 20:
  simulated_total_ratio = 0.935
  MAE = 37.759
  Bias = -3.780

observation baseline iteration 20:
  simulated_total_ratio = 0.504
  MAE = 36.664
  Bias = -29.027
```

解釈:

```text
観測点別baseline単独:
  観測点ごとの相対改善を見るため、全体の過小を押し上げる力が弱い。
  そのため再現率は 50% 程度で止まった。

global baseline:
  全体過小を押し上げる力が強く、再現率は大きく改善する。
  ただし後半は観測点別配分が崩れてMAEが悪化する。
```

この結果から、観測点別baselineだけに置き換えるのは不十分である。
次は、global と observation を混ぜる mixed baseline、または reward に全体過小補正項を入れる方法を検討する。

### 観測点別baselineが伸びなかった原因

観測点別baselineでは、各観測点ごとの平均 reward を基準にする。
このため、各観測点で共通して起きている「全体的に車が足りない」という問題がbaselineに吸収されやすい。

例:

```text
ある観測点が全時間帯で同じように過小:
  08:10 reward = -0.70
  08:15 reward = -0.75
  08:20 reward = -0.72
  08:25 reward = -0.76
  08:30 reward = -0.70
  08:35 reward = -0.74

observation_baseline ≒ -0.73
```

この場合、どの時間binもbaselineと近いため、advantage が小さくなる。
本来は「この観測点は全体的に過小なので、もっと車を流す」という信号が必要だが、観測点別baselineは「この観測点の中では普通」と判断しやすい。

そのため、観測点別baseline単独では以下の挙動になった。

```text
全体過小を押し上げる力:
  弱い

観測点ごとの配分暴走を抑える力:
  ある程度ある

結果:
  MAEはglobal baseline iteration 20より少し良いが、
  simulated_total_ratio は 0.504 に留まり、Bias も -29.027 と大きく過小のまま。
```

一方、global baseline は全体平均からの差を見るため、全体が過小な初期状態では、観測点に車を通した経路が強く褒められる。
そのため再現率は大きく上がるが、後半では一部観測点に流れすぎてMAEが悪化する。

整理すると:

```text
global baseline:
  量の学習に強い
  配分制御に弱い

observation baseline:
  配分制御に少し効く
  量の学習に弱い
```

また、観測点別baselineでは `rl_observation_baseline_min` が -50 から -70 程度まで極端になるiterationがあった。
これは、観測値が小さい観測点で simulated が大きくなった場合、現在の error_rate 定義により reward が非常に小さくなるためである。

```text
error_rate = (simulated - observed) / max(observed, 1)
reward = - abs(error_rate)
```

低交通量・外れ値観測点の影響を受けやすいことも、観測点別baseline単独の不安定要因である。

次の方針:

```text
mixed baseline を試す。

候補:
  baseline = 0.7 * observation_baseline + 0.3 * global_baseline
  baseline = 0.5 * observation_baseline + 0.5 * global_baseline
  baseline = 0.3 * observation_baseline + 0.7 * global_baseline
```

目的は、global baseline の全体量を押し上げる力と、observation baseline の配分暴走を抑える力を両方残すことである。
