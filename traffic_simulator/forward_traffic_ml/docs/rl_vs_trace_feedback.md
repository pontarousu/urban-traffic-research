# 強化学習と現行 trace feedback の違い

## 目的

このメモは、現行の `trace-based feedback` と、強化学習ベースの分岐確率学習の違いを整理するためのものです。

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

この方式は直感的で、現在のシミュレータと相性がよい。
一方で、更新式はルールベースであり、将来ニューラルネットワークへ接続するには整理が必要になる。

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

trajectory:
  車両の軌跡。発生から消滅までの分岐履歴と観測点通過履歴。

log probability:
  選んだ行動の確率の対数。
  policy gradient では、この値を使って選んだ行動の確率をどう変えるかを計算する。

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

## theta table での最小RL

最初からニューラルネットワークに行かず、現在の `theta` を policy parameter と見なす。

分岐確率:

```text
P(outgoing | intersection, incoming) = softmax(theta)
```

車両がある分岐で action `a` を選ぶ。
そのときの確率を `P(a)` とする。

報酬が基準より良ければ、選んだ action の確率を上げる。
報酬が基準より悪ければ、選んだ action の確率を下げる。

REINFORCE 風の更新:

```text
theta[action] += learning_rate * advantage * weight * (1 - P(action))
theta[other]  -= learning_rate * advantage * weight * P(other)
```

ここで、

```text
advantage = reward - baseline
weight = 観測点から分岐までの距離減衰
```

## 現行方式との比較

| 観点 | trace feedback | 強化学習 |
|---|---|---|
| trace | 使う | 使う |
| 更新対象 | theta | policy parameter |
| 更新根拠 | 手作りルール | reward 最大化 |
| 選択確率 | 更新式では弱い | 明示的に使う |
| 平均より良い/悪い | 扱いにくい | baseline / advantage で扱う |
| 探索維持 | epsilon が中心 | entropy も使える |
| NN化 | 接続しにくい | 自然に接続できる |

## 最小構成の方針

- reward は観測点単位で作る。
- baseline はまず全体平均から始める。
- 境界リスク観測点は、道路DBの切り出し範囲を十分に広く取ることで対処し、最小実験では reward から外す。
- match confidence は最小RLでは reward weight に使わない。
- 探索は最初は epsilon のみで行う。
- 評価条件は trace feedback と完全にそろえる。

## NNへ進む場合

NNを使う場合、rule-based theta をそのまま教師にするのは避ける。
それは rule-based theta の模倣になり、ルールの限界を超えにくいためである。

NN policy の形:

```text
features(intersection, incoming, outgoing, time)
→ NN
→ score
→ softmax
→ 分岐確率
```

RLであれば、NNは教師ラベルではなく reward によって更新される。
そのため、trace feedback の限界を超える余地がある。
