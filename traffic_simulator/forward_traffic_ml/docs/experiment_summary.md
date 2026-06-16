# forward_traffic_ml 実験サマリ

このメモは、詳細ログを読まなくても主要な実験結果と現在の課題が分かるように整理したものです。

数値は公開可能な範囲の集計指標として記録しています。実交通量データ、観測点位置、観測点対応JSON、シミュレーション結果CSV/JSONは公開版に含めていません。

## 1. OSM Way ベースの最小実装

最初は、OSM Way をそのまま道路単位として扱い、車両を発生・移動・分岐させる最小モデルを作りました。

分かったこと:

```text
- 順方向に車を流して観測点通過を数える最小系は作れる。
- ただし、OSM Way / node をそのまま使うと、交差点単位の分岐学習が不安定になる。
- 細かすぎる道や行き止まりが多く、対象道路の選択が結果に強く影響する。
```

このため、道路DB directed edge ベースへ移行しました。

## 2. 道路DB directed edge ベースへの移行

道路DBでは、車両移動に使う topology と、描画用 geometry を分けました。

分岐確率は次の単位で扱います。

```text
(intersection node, incoming directed edge, outgoing directed edge)
```

分かったこと:

```text
- OSM node をそのまま交差点として扱うより、学習単位が明確になる。
- 観測点マッチング、車両trace、分岐traceを同じ道路DB上で扱える。
- 一方で、道路DB範囲の境界近くでは観測点対応や到達性に注意が必要。
```

## 3. 観測点マッチングとビューア

観測点の緯度経度と道路DBの directed edge を対応付ける過程で、位置ずれ、上下線ペア、道路境界近くの観測点が問題になりました。

対応:

```text
- 観測点と道路の対応を地図上で確認するビューアを追加。
- 近接観測点ペアの交通量プロファイルを確認。
- 同じ directed edge に対応してしまう観測点ペアを診断。
- 道路DB bbox 境界から近い観測点は評価から除外する方針を導入。
```

公開版では、ビューア本体だけを含め、観測点位置を含む `viewer/data/*.json` は含めていません。

## 4. trace feedback

車両が観測点を通過したとき、その車両が過去に通った分岐履歴へ観測誤差を戻す方式を試しました。

分かったこと:

```text
- 観測点周辺では分岐確率を更新できる。
- 観測点に届かない車両や、観測点が疎な地域には学習信号が届きにくい。
- backtrace距離、発生位置、観測点密度が学習範囲を強く左右する。
```

この段階で、発生位置と計算量が大きな課題になりました。

## 5. 発生分布と packet simulation

観測点上流だけから車両を発生させると、学習範囲が観測点周辺に偏りました。そこで、メッシュ単位で発生源を分散させる `mesh_uniform` を試しました。

また、1台ずつのシミュレーションでは計算量が大きいため、複数台を1つの代表車両として扱う packet simulation を導入しました。

分かったこと:

```text
- 発生分布は、どの地域に学習信号が届くかを大きく左右する。
- packet simulation により、より大きな generation_multiplier と iteration を試しやすくなった。
- ただし、発生分布が単純だと地域別の過大・過小が残る。
```

## 6. 最小RL更新

trace feedback を、policy gradient に近い形で整理しました。

基本式:

```text
advantage = reward - baseline
```

`reward` は観測点・時間binごとの誤差率から作り、`baseline` はその基準値として使います。`advantage` が正なら、そのtraceで選ばれた分岐を相対的に強め、負なら弱めます。

分かったこと:

```text
- global baseline は全体量を押し上げやすい。
- observation baseline は観測点別の暴走を抑えやすいが、全体過小を押し上げにくい。
- mixed baseline はその中間として有望。
```

## 7. no_outgoing 構造ペナルティ

一部領域で観測点到達率が低かったため、次の outgoing が存在しない edge を選びにくくする構造 prior を入れました。

```text
score = theta + structural_penalty
structural_penalty = no_outgoing_penalty if 次の outgoing がない else 0
```

分かったこと:

```text
- 観測点到達率や再現量の立ち上がりは改善した。
- ただし、長く回すと一部地域が過大になりやすい。
- no_next_edge の数そのものよりも、地域別の過大・過小バランスが重要である。
```

## 8. 現在の課題

現時点の主要課題は、全体量を増やすことではなく、地域別の過大・過小を抑えることです。

特に、次の要因が効いている可能性があります。

```text
- 観測点密度の偏り
- 道路網の連続性の偏り
- mesh_uniform 発生分布の単純さ
- 昼間人口・業務地・商業地などの地域需要 prior がないこと
```

次の方向性:

```text
- 道路周辺人口
- 昼間人口
- 従業者数
- 建物用途・延床面積
- 道路容量・車線数・速度
```

これらを地域別 prior として使い、車両発生分布や reward weight を補正することを検討しています。

## 9. この公開版での読み方

主要な流れだけ見る場合:

```text
research_timeline.md
spec.md
experiment_summary.md
```

RL更新の意味を見る場合:

```text
rl_vs_trace_feedback.md
```

詳細な実験ログを見る場合:

```text
technical_decisions.md
phase3_road_db_forward_simulation.md
phase4_trace_feedback_training.md
```
