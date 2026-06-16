# forward_traffic_ml docs guide

このディレクトリには、順方向交通シミュレーション研究の設計、実験、判断ログを置いています。

初見の人がいきなり詳細ログを読むと分かりにくいため、読む順番を分けています。

## 初めて読む場合

```text
1. research_timeline.md
2. spec.md
3. experiment_summary.md
4. rl_vs_trace_feedback.md
```

### `research_timeline.md`

研究の流れを時系列で説明します。

```text
順方向シミュレーションへ移った理由
道路DBへ移行した理由
trace feedback を作った理由
最小RL更新へ進んだ理由
現在の地域別補正課題
```

### `spec.md`

現在の技術仕様とファイル構成をまとめた公開向けの仕様書です。

```text
何を補正するのか
道路DBとどう関係するのか
src/ と viewer/ の各ファイルが何をするのか
公開版で除外しているデータは何か
```

### `experiment_summary.md`

主要な実験結果だけを短くまとめています。

```text
trace feedback
packet simulation
最小RL
baseline比較
no_outgoing構造ペナルティ
現在の課題
```

### `rl_vs_trace_feedback.md`

trace feedback と最小RL更新の違いを説明します。RL用語の意味や、`reward`、`baseline`、`advantage` の考え方もここにまとめています。

## 詳細ログ

以下は研究中の詳細な判断ログです。初見では先に読む必要はありません。

```text
technical_decisions.md
phase3_road_db_forward_simulation.md
phase4_trace_feedback_training.md
```

### `technical_decisions.md`

かなり長い技術判断メモです。発生量、分岐確率、観測点マッチング、道路DB移行、RL実験などの判断が時系列で残っています。

### `phase3_road_db_forward_simulation.md`

道路DB directed edge ベースの順方向シミュレーションへ移行した段階の詳細ログです。

`Phase 3` は研究中の内部フェーズ名であり、公開版の読み順を意味するものではありません。

### `phase4_trace_feedback_training.md`

trace feedback、発生分布、packet simulation、観測点誤差診断などの詳細ログです。

`Phase 4` も研究中の内部フェーズ名です。

## 公開版の注意

この公開版には、実交通量データ、観測点コードと緯度経度の対応表、観測点と道路を対応付けた生成済みJSON、シミュレーション結果CSV/JSONを含めていません。

そのため、実験を再実行するには、利用者自身が権利上問題のない入力データを用意する必要があります。
