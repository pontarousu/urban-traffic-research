# forward_traffic_ml

`forward_traffic_ml` は、都市道路ネットワーク上で車両を通常の順方向に発生・移動・分岐させ、その結果として得られる観測点通過台数を実測の断面交通量に近づけるための研究・実装プロジェクトです。

このプロジェクトでは、観測点から車両を直接生成するのではなく、観測交通量を **発生分布・分岐確率・評価関数を補正するための信号** として扱います。

## まず読むもの

初めて見る場合は、次の順番で読むと全体像を追いやすいです。

```text
1. docs/README.md
   ドキュメント全体の案内。

2. docs/research_timeline.md
   なぜ順方向シミュレーション、道路DB、trace feedback、RLへ進んだのかの時系列。

3. docs/spec.md
   現在の技術仕様とファイル構成。

4. docs/experiment_summary.md
   主要な実験結果と、何が分かって何が課題として残っているか。

5. docs/rl_vs_trace_feedback.md
   trace feedback と最小RL更新の違い。
```

詳細な作業ログを追いたい場合は、以下を参照してください。

```text
docs/technical_decisions.md
docs/phase3_road_db_forward_simulation.md
docs/phase4_trace_feedback_training.md
```

`phase3` / `phase4` は研究途中の内部フェーズ名です。公開版では、まず上記の `docs/README.md` と `docs/research_timeline.md` を読む前提にしています。

## 公開版の位置づけ

この公開版は、完成済みの交通シミュレータではありません。研究途中の設計、実装、検証結果を、公開可能な範囲で整理したものです。

公開版で確認できるもの:

```text
- 順方向交通シミュレーションの考え方
- OSM Way ベースから道路DB directed edge ベースへ移行した理由
- 車両 trace を使った分岐確率更新
- REINFORCE風の最小RL更新
- mixed baseline と no_outgoing 構造ペナルティの実験方針
- 可視化ビューア本体
```

公開版に含めていないもの:

```text
- 実交通量データ本体
- 観測地点コードと緯度経度の対応表
- 観測点と道路を対応付けた生成済みJSON
- viewer/data/*.json
- results/* のシミュレーション結果
- data/* の前処理済みデータ
- 道路DBの生成済みスナップショット
```

これらは、観測点位置情報や実交通量に由来する派生データを含む可能性があるため、公開対象から除外しています。

## 研究上の基本方針

```text
道路ネットワーク
  ↓
車両発生
  ↓
道路上を移動
  ↓
交差点で分岐
  ↓
観測点通過を集計
  ↓
観測交通量との差を評価
  ↓
発生分布・分岐確率・評価関数を補正
```

重要なのは、観測交通量を「車両を直接置く命令」として使わないことです。観測値は、順方向シミュレーションのパラメータを調整するための信号として使います。

## 現在の主な実装

```text
src/road_db_forward_simulator.py
  道路DB directed edge ベースの順方向シミュレーション。

src/road_db_network_loader.py
  道路DBスナップショットをシミュレーション用に読み込む。

src/road_db_feedback_trainer.py
  車両 trace に基づく trace feedback 更新。

src/road_db_rl_trainer.py
  reward / baseline / advantage に基づく最小RL更新。

src/run_road_db_rl_training.py
  最小RL学習ループの実行。

viewer/*.html, viewer/*.js
  観測点対応、誤差、発生位置、no_next_edge などの確認ビューア。
```

古い最小実装として、`preprocess.py`、`simulate_forward.py`、`compare_observed.py` も残しています。これらは研究初期の OSM Way ベース実装です。現在の主な検証は道路DB版へ移っています。

## 実行について

公開版には入力データと生成済み結果を含めていないため、多くのスクリプトはそのままでは最後まで実行できません。

実行する場合は、利用規約上問題のない入力データを別途用意し、各スクリプトの引数で明示的に指定してください。viewer も `viewer/data/*.json` をローカルで生成してから使う前提です。

## データとライセンス

断面交通量情報の数値データについては、公益財団法人日本道路交通情報センター（JARTIC）の利用規約に従い、出典表記と加工表記を行う方針です。一方で、観測地点の詳細な位置情報およびそれに由来する派生データは、この公開版には含めていません。

一部の実験では OpenStreetMap データを利用します。OSM由来データを使う場合は、以下の帰属表示が必要です。

```text
© OpenStreetMap contributors
https://www.openstreetmap.org/copyright
```

## 現在の課題

現時点では、全体の交通量再現を押し上げるだけでなく、地域ごとの過大・過小を抑えることが課題です。

特に、観測点密度、道路網の連続性、車両発生分布の単純さが、地域別の偏りを生んでいる可能性があります。次の方向性として、道路周辺人口、昼間人口、建物用途、道路容量などを使った地域別 prior の導入を検討しています。
