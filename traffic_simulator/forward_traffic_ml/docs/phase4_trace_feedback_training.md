# Phase 4: Trace-based Feedback Training

## 目的

Phase 4 では、観測点ごとの誤差を車両の分岐 trace に戻し、交差点の分岐確率 `theta` を更新する。

学習対象は以下の単位。

```text
theta[intersection_node_id, incoming_directed_edge_id, outgoing_directed_edge_id]
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

1つの分岐寄与の更新量は、学習率、誤差、観測点までの距離減衰、更新量の上限で制御する。

## trace の扱い

車両ごとに以下を記録する。

- 発生 edge
- 通過した directed edge
- 交差点で選んだ incoming / outgoing
- 観測点通過イベント
- 観測点までの距離と時間

距離ベースの backtrace では、観測点から上流方向へ一定距離までの分岐履歴に誤差を戻す。
edge 数だけで戻すと、道路DBの分割粒度に強く依存するため、距離ベースの方が扱いやすい。

## evaluation run

training run は iteration ごとに seed を変えるため、指標変化が `theta` の効果なのか乱数差なのか切り分けにくい。
そのため、各 iteration の更新後に同じ `eval_seed` で evaluation run を追加する。

```text
training run:
  seed = base_seed + iteration
  theta 更新に使う

evaluation run:
  seed = eval_seed
  theta 更新後に実行する
  theta は更新しない
```

## 主な評価指標

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

theta_updated_count:
  その iteration で更新された theta 数。
```

## 現時点の課題

- 観測点の近くに発生を寄せすぎると、観測点近傍だけが強く学習される。
- 発生源を広げすぎると、観測点に届く車両が減り、trace が不足する。
- 観測点密度が低い地域では、誤差をどこまで上流へ戻すかが難しい。
- 境界付近の観測点は、道路DBの切り出し範囲によって到達可能性が歪む。

公開版では、具体的な実測値、観測点別の診断値、生成済み結果ファイルは含めない。
