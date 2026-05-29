# Phase 3: Road DB ベース順方向シミュレーション

## 目的

Phase 3 では、OSM way ベースの旧シミュレーションから、道路DBの `directed_edge` ベースへ移行する。

この段階の目的は精度最適化ではなく、以下の動作を確認すること。

- 車両が `directed_edge` 上を前進する
- edge 終端で分岐候補に従って次の edge を選ぶ
- 観測点の対応 edge と位置比率に基づいて通過を記録する
- 観測値と simulated count を5分単位で比較できる
- 分岐 trace と観測 trace が次フェーズの学習に使える形式で出る

## 入力

公開版では、道路DBスナップショット、観測点対応、観測交通量を含む生成済み JSON は含めない。
ローカル実験では、次の種類の非公開入力を明示的に渡す。

```text
network_core.json
network_geometry.json
observation_alignment.json
private_inputs/scenario.json
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
```

非公開の元シナリオ JSON から使うもの:

```text
observation_points[].traffic_volume
```

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
  CLI から短時間の順方向シミュレーションを実行する。
```

## 車両発生

初期の道路DB版では、観測点を直接発生点にしない。
観測点の上流やメッシュ上に配置した候補 edge から車両を発生させ、通常の分岐で観測点へ到達するかを見る。

発生タイミングは5分単位の一斉発生ではなく、対象時間内に分散させる。
これにより、観測点通過時刻が不自然に固まることを避ける。

## 消滅条件

最小実装では、以下の場合に車両を終了させる。

- 次の edge がない
- 最大走行時間を超えた
- シミュレーション時間を超えた
- 経路上で有効な分岐候補がない

容量上限による即時消滅は避け、混雑が必要な場合は速度低下で表現する方針にする。

## 評価

Phase 3 では、精度そのものよりも以下を確認する。

- 観測点通過が記録されるか
- 5分binごとの比較表が生成できるか
- 分岐 trace が学習に使える形式で保存されるか
- 発生位置と観測点の距離が極端に不自然でないか

実験結果の具体的な数値ログは公開版には含めない。
