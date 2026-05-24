# inverse_traffic_simulator 技術仕様

## 1. 目的

`inverse_traffic_simulator` は、観測された断面交通量を手がかりに、都市道路ネットワーク上の車両流を構成するための逆問題型交通シミュレーションです。

通常の交通シミュレーションでは、車両が出発地・目的地・経路選択ルールを持ち、その結果として各地点の交通量が生まれます。一方、この試作では、観測点で得られる「5分間に何台通過したか」という断面交通量を制約として扱い、その制約に近づくように車両の移動過程を構成します。

この仕様書では、公開版に含まれるコードの設計意図、データ構造、アルゴリズム、制約、公開版で除外しているデータを整理します。

## 2. 問題設定

### 2.1 順方向シミュレーションとの違い

順方向シミュレーションでは、一般に次の流れになります。

```text
OD需要 → 車両発生 → 経路選択 → 道路上の移動 → 観測交通量
```

しかし、本プロジェクトで利用したい情報は、主に観測点ごとの断面交通量です。つまり、出発地・目的地の完全なOD需要ではなく、道路上のいくつかの断面で「いつ・何台通過したか」が与えられます。

そこで、この試作では次のように問題を捉えます。

```text
観測交通量 → 必要な通過需要 → 車両の予約・移動 → 車両流の構成
```

これは厳密なOD推定ではありません。観測点の通過台数を満たすように、道路ネットワーク上の車両軌跡を構成する実験的なアプローチです。

### 2.2 難しさ

断面交通量だけから車両流を構成する場合、次の難しさがあります。

- ある観測点を通過した車両が、どこから来てどこへ向かったかは直接分からない
- 複数の観測点を同じ車両が通過する可能性がある
- 観測点が疎な地域では、周辺の流れを一意に決められない
- 観測値に合わせすぎると、車両挙動が不自然になりやすい
- 広域OSMではWay数が多く、経路探索の計算量が大きい

そのため、本仕様では「完全な現実再現」ではなく、観測点の需要を満たす過程を、できるだけ自然な道路移動として構成することを目標にします。

## 3. 基本思想

### 3.1 観測点を需要として扱う

各観測点は、時刻ごとに「直前5分で何台通過してほしいか」という需要を持ちます。この需要を `RequestWindow` と呼びます。

たとえば、ある観測点に対して `10:00 に 100台` という観測値がある場合、これは `9:55〜10:00` の5分間に100台の通過が必要だった、という需要として扱います。

### 3.2 車両は需要を予約する

車両は交差点に到達したタイミングで、将来満たすべき `RequestWindow` を1つ選んで予約します。予約した後は、その観測点へ向かう最短時間経路を進みます。

```text
交差点到達
  ↓
候補RequestWindowを評価
  ↓
1つ予約
  ↓
予約先まで最短経路で移動
  ↓
観測点通過時に需要を消化
```

この方式により、毎ステップで進路を変える不自然な挙動を避けます。

### 3.3 予約できない場合は standby 移動する

予約可能な需要がない場合、車両はすぐに消えるのではなく、将来需要が強くなりそうな方向へ保留移動します。これを standby 移動と呼びます。

standby 移動は、観測点が疎な地域や、需要の発生時刻が少し先にある場合に、車両を自然に待機・移動させるための仕組みです。

## 4. 入力データモデル

入力JSONは、静的な道路ネットワーク、観測点、シミュレーション設定を持ちます。車両状態やイベントログは入力には含めません。

```json
{
  "schema_version": "1.0",
  "meta": {},
  "graph": {
    "nodes": [],
    "ways": []
  },
  "observation_points": [],
  "simulation_config": {}
}
```

### 4.1 meta

```json
{
  "scenario_id": "tokyo_test_area_001",
  "scenario_name": "Tokyo Test Area 001",
  "start_time_min": 0,
  "view_box": {
    "x_min": 0,
    "y_min": 0,
    "x_max": 1000,
    "y_max": 1000
  }
}
```

`meta` はシナリオの識別情報と描画用の基準情報を持ちます。

### 4.2 graph.nodes

`Node` は交差点または道路リンクの接続点を表します。

```json
{
  "id": "node_001",
  "lat": 35.0,
  "lon": 139.0,
  "view_x": 412.3,
  "view_y": 288.7,
  "connected_way_ids": ["way_001", "way_014"],
  "turn_permissions": [
    {
      "from_way_id": "way_001",
      "to_way_id": "way_014",
      "allowed": true
    }
  ]
}
```

主な役割は次の通りです。

- 車両が交差点に到達したかを判定する
- 次に進めるWayを列挙する
- Uターンや右左折禁止などの制約を表す
- ブラウザ上の描画位置を持つ

### 4.3 graph.ways

`Way` は単方向の道路リンクです。双方向道路は、向きの異なる2本のWayとして扱います。

```json
{
  "id": "way_001",
  "osm_way_id": "257233109",
  "from_node_id": "node_001",
  "to_node_id": "node_002",
  "shape_points": [
    {"lat": 35.0, "lon": 139.0, "view_x": 412.3, "view_y": 288.7},
    {"lat": 35.0, "lon": 139.0, "view_x": 430.1, "view_y": 300.2}
  ],
  "road_type": "secondary",
  "lane_count": 2,
  "length_meter": 42.8,
  "speed_limit_kmh": 60,
  "storage_capacity_cars": 20
}
```

Wayには、移動・描画・容量計算に必要な情報を持たせます。

| 項目 | 意味 |
|---|---|
| `from_node_id` / `to_node_id` | このWayの始点・終点 |
| `shape_points` | 地図上に描画する折れ線 |
| `length_meter` | Wayの長さ |
| `speed_limit_kmh` | 自由流速度の基準 |
| `storage_capacity_cars` | 同時に存在できる車両数の目安 |

容量は初期実装では次の式で近似します。

```text
storage_capacity_cars = max(lane_count, floor(length_meter / 4) * lane_count)
```

### 4.4 observation_points

`ObservationPoint` は断面交通量を比較するための観測点です。観測点は、単方向Way上の位置として対応付けます。

```json
{
  "id": "obs_001",
  "lat": 35.0,
  "lon": 139.0,
  "view_x": 438.4,
  "view_y": 305.9,
  "matched_way_id": "way_001",
  "matched_position_ratio": 0.62,
  "traffic_volume": [
    {"time_min": 480, "volume_5min": 100},
    {"time_min": 485, "volume_5min": 120}
  ]
}
```

`time_min` はシミュレーション開始からの分を表します。`volume_5min` は、その時刻直前5分の通過台数です。

公開版では、実際の観測点座標や実交通量を含むJSONは同梱していません。上記は形式説明用の例です。

### 4.5 simulation_config

```json
{
  "random_seed": 42,
  "time_step_sec": 1,
  "request_horizon_min": 20,
  "standby_horizon_min": 25,
  "standby_total_time_limit_min": 10,
  "standby_score_threshold": 0.1,
  "unassigned_fail_limit": 3,
  "request_window_min": 5,
  "u_turn_allowed": false,
  "score_model": {
    "type": "discounted_sum",
    "travel_decay_a": 0.12,
    "slack_decay_b": 0.08
  }
}
```

この設定は、予約対象にする将来時間、standby移動の上限、score計算の減衰係数などを制御します。

## 5. 実行時データ構造

### 5.1 CarState

`CarState` はシミュレーション中の車両状態です。

概念的には次の情報を持ちます。

```text
CarState {
  id,
  current_way_id,
  position_ratio,
  speed_mps,
  status,
  reserved_request_id,
  route,
  standby_elapsed_min
}
```

主な状態は次の通りです。

| 状態 | 意味 |
|---|---|
| `moving` | 予約済み、または通常移動中 |
| `unassigned` | 予約先がなく、standby移動中 |
| `retired` | シミュレーションから除外済み |

### 5.2 RequestWindow

`RequestWindow` は、1つの観測値から生成される需要窓です。

```text
RequestWindow {
  id,
  observation_point_id,
  matched_way_id,
  time_min,
  window_start_min,
  window_end_min,
  target_count,
  assigned_count,
  reserved_count,
  failed_count
}
```

各カウントの意味は次の通りです。

| 項目 | 意味 |
|---|---|
| `target_count` | その5分窓で必要な通過台数 |
| `assigned_count` | すでに実際に通過した台数 |
| `reserved_count` | 将来この窓を担当すると予約済みの車両数 |
| `failed_count` | 予約したが締切に間に合わなかった台数 |

## 6. 需要の表し方

### 6.1 累積目標

5分間に必要な台数を、時間内で平均的に満たすと考えます。時刻 `now` における累積目標は次のように定義します。

```text
elapsed_ratio =
  clamp((now - window_start_min) / (window_end_min - window_start_min), 0, 1)

target_cumulative(now) =
  target_count * elapsed_ratio

effective_deficit(now) =
  max(0, target_cumulative(now) - assigned_count - reserved_count)

deficit_ratio(now) =
  clamp(effective_deficit(now) / target_count, 0, 1)
```

`effective_deficit` は、現在時点で追加で満たす必要がある台数です。予約済み台数も差し引くことで、同じ需要へ車両が過剰に集中することを防ぎます。

### 6.2 スロット方式

小さい観測値でも自然な生成タイミングを作るため、5分窓内に等間隔の整数スロットを置きます。

```text
slot_interval_min =
  (window_end_min - window_start_min) / target_count

due_count(time) =
  clamp(
    floor((time - window_start_min) / slot_interval_min + 0.5),
    0,
    target_count
  )

needed_reservation_count(arrival_time) =
  max(0, due_count(arrival_time) - assigned_count - reserved_count)
```

`needed_reservation_count(arrival_time) >= 1` のとき、その時刻に到着する車両を予約する価値があると判断します。

## 7. Request score

車両がどの需要を担当するべきかを評価するため、`score_request` を定義します。

```text
score_request(car, request, now)
= deficit_ratio(request, now)
 * exp(-a * travel_time_min)
 * exp(-b * slack_min)
```

ここで、

```text
slack_min = window_end_min - now - travel_time_min
```

です。

| 変数 | 意味 |
|---|---|
| `travel_time_min` | 現在位置から観測点までの最短所要時間 |
| `slack_min` | 締切までの余裕時間 |
| `a` | 所要時間に対する減衰係数 |
| `b` | 余裕時間に対する減衰係数 |

次の条件では score を 0 とします。

- すでに需要が満たされている
- 到着予想時刻で追加予約が不要
- `slack_min < 0`
- 経路が存在しない

score は「どの需要を優先するか」を決める値であり、生成・予約の必要台数判定そのものには使いません。必要台数判定には、前節のスロット方式を使います。

## 8. 予約ルール

### 8.1 予約の単位

車両は一度に1つの `RequestWindow` だけを予約します。複数の観測点をまとめて予約することはしません。

### 8.2 予約のタイミング

予約は、車両が交差点ノードに到達したタイミングで行います。道路リンクの途中では基本的に予約先を変更しません。

### 8.3 予約後の挙動

予約に成功した車両は、予約先の観測点へ向かう最短時間経路を進みます。途中の交差点でも、原則として予約先へ向かう経路を維持します。

これにより、毎交差点で需要scoreを見直して進路が揺れる挙動を避けます。

### 8.4 予約解除

予約は次の場合に解除します。

1. 観測点通過に成功した場合
2. 締切までに到達できないことが分かった場合
3. 車両が `retired` になった場合

通過に成功した場合、カウントを次のように更新します。

```text
assigned_count += 1
reserved_count -= 1
```

予約に失敗した場合は、必要に応じて `failed_count` を更新します。

## 9. 車両生成と standby 移動

### 9.1 車両生成

新車生成は、特定の観測点不足へ直接反応させるのではなく、空間グリッド上の将来需要から決めます。

概念的には、各グリッドセルについて次を計算します。

```text
future_request_mass(cell, now..now + standby_horizon)
cell_need = future_request_mass - current_car_count
```

`cell_need` が大きいセルでは、将来その周辺で需要が強くなると考え、車両生成候補にします。

### 9.2 standby 移動

予約先が見つからない車両は、すぐに消滅せず、将来需要が強い方向へ移動します。

standby 移動には次の制限を設けます。

- 一定時間以上予約できない場合は `retired` とする
- 連続予約失敗回数が上限を超えた場合も `retired` とする
- standby score が低い場合は無理に移動しない

この仕組みにより、需要が少ない時間帯や観測点が疎な地域で、車両が不自然に残り続けることを防ぎます。

## 10. 経路探索

### 10.1 自由流所要時間

経路探索の重みには、初期実装では自由流所要時間を使います。

```text
travel_time_min = length_meter / speed_limit_m_per_min
```

混雑による速度低下は車両移動の更新では考慮できますが、経路木には反映しません。

### 10.2 逆向き最短経路木

広域OSMでは、車両ごと・需要ごとに毎回ダイクストラ法を実行すると計算量が大きくなります。

そのため、目的地となる `matched_way_id` ごとに、逆向きの最短経路木を作ります。

```text
shortest_path_tree[target_way_id] = {
  distance_min_by_node,
  next_way_id_by_node
}
```

車両が現在いるノードから予約先へ向かうときは、`next_way_id_by_node[current_node_id]` を参照することで、次に進むWayを高速に取得します。

### 10.3 採用した近似

経路木は自由流所要時間で作ります。実際の混雑速度を経路木に反映すると、時間変化に応じて経路木を再生成する必要があり、広域実験では計算量が大きくなりすぎるためです。

## 11. 観測点通過判定

観測点は、対応する単方向Way上の `matched_position_ratio` に配置されます。

車両が同じWay上を移動し、前ステップから現ステップの間に観測点位置を跨いだ場合、観測点通過とみなします。

```text
previous_position_ratio < matched_position_ratio <= current_position_ratio
```

通過した観測点が予約先であり、かつ対応する `RequestWindow` の時間窓に間に合っていれば、需要達成として `assigned_count` を増やします。

## 12. OSM・観測点前処理

### 12.1 OSM道路網の変換

OSMの道路データは、シミュレーション用に次の流れで変換します。

1. OSM XMLから車道系 `highway` のWayだけを抽出する
2. OSM Wayを隣接Node間のセグメントへ分割する
3. 各セグメントを単方向Wayとして生成する
4. 双方向道路は正方向Wayと逆方向Wayの2本に分ける
5. `length_meter`, `lane_count`, `speed_limit_kmh`, `storage_capacity_cars` を付与する
6. 描画用の `view_x`, `view_y` を計算する

### 12.2 観測点マッチング

観測点は緯度経度を持つ点として与えられます。これを、最も近い単方向Wayへ対応付けます。

```text
ObservationPoint(lat, lon) → matched_way_id + matched_position_ratio
```

広域では観測点数とWay数が多くなるため、全組み合わせの距離計算は高コストです。そこで、Wayのbboxをグリッドセルに登録し、観測点周辺の候補Wayだけを精密計算します。

```text
計算量の素朴な形 = 観測点数 N × Way 数 M
```

グリッド索引により、実際に距離計算する候補Way数を減らします。

### 12.3 観測方向の扱い

初期実装では、元データの方向情報を十分に保持できない場合があるため、観測点を最近傍の単方向Wayへ仮対応付けします。

これは暫定仕様です。将来的には、元データのリンク番号や方向情報を保持し、正方向・逆方向のどちらのWayに載せるべきかをより正確に決める必要があります。

## 13. 可視化と playback

ブラウザビューアでは、道路ネットワーク、観測点、車両、通過イベントを確認できるようにします。

広域OSMでは、ブラウザ側で毎回シミュレーションを再計算すると重くなるため、Node.js側であらかじめ playback JSON を生成し、ブラウザはそれを再生する方針を取ります。

公開版では、実データ由来の playback JSON は含めていません。ビューア本体と変換スクリプトのみを含めています。

## 14. 公開版で除外しているデータ

公開版には、次のデータを含めていません。

- 実観測地点の緯度経度
- 断面交通量計測地点の詳細な位置情報
- 実交通量と位置情報を結合したJSON
- OSM道路網、観測点、交通量を統合した実験用シナリオJSON
- 大規模再生用の playback JSON
- 長時間ベンチマーク結果の生データ

これは、断面交通量計測地点の位置情報およびそれに由来する派生データに再配布上の制限があるためです。

開発時には `number_to_location.csv` という観測点コードと緯度・経度の対応表を参照していました。この `number` は交通量CSV内で観測地点を識別する観測点コードを表し、`location` はその観測地点の緯度・経度を表します。

想定していた形式は、概念的には次のようなCSVです。

| column | description |
| --- | --- |
| `source_code` | 情報源コード |
| `point_number` | 観測地点を表す観測点コード |
| `point_name` | 観測地点名 |
| `lat` | 緯度 |
| `lon` | 経度 |

この対応表は断面交通量計測地点の詳細な位置情報に該当するため、利用規約上、承認前に第三者へ再配布できない可能性があります。そのため、CSV本体だけでなく、この対応表と交通量CSVを結合して生成した `realdata_all.json`、小規模抽出した `realdata_sample_small.json`、OSM道路網と対応付けた `data/current/*.json` も公開版から除外しています。

公開版では、データそのものではなく、データ構造、変換処理、アルゴリズム、可視化の設計を示します。

## 15. 限界と今後の改善

### 15.1 限界

- 断面交通量だけから完全なOD需要を一意に復元することはできない
- 観測点が疎な地域では、車両流の自由度が高くなりすぎる
- active car 数が5分単位の観測窓に同期して増減し、時間方向に拍動する問題を解決できていない(viewer内のactive_car_graphを参照)
- 最終的には東京都全体の道路ネットワークと観測点を対象にしたいが、現段階で検証できたのは主に約300地点規模の観測点ケースに留まる
- 初期実装では信号制御、車線変更、渋滞波を厳密には扱わない
- 観測方向の扱いは暫定的であり、元データの方向情報をより正確に使う必要がある
- 実データ由来の再生JSONを公開していないため、公開版単体では大規模実験を再現できない

### 15.2 今後の改善

- 承認後に公開可能なサンプルデータを整備する
- 人工データによる完全に再現可能な最小シナリオを追加する
- 5分ごとの需要窓に車両数が過剰に同期しないよう、需要の平滑化、車両生成の慣性、滞留車両の扱いを改善する
- 約300地点規模から東京都全体へ拡張するため、経路探索キャッシュ、playback生成、描画負荷をさらに削減する
- 観測方向を考慮したWayマッチングを実装する
- `forward_traffic_ml` の順方向補正アプローチと比較する
- 道路DB形式へ移行し、トポロジーとジオメトリをより明確に分離する
- 信号、容量制約、混雑速度、車線変更を段階的に導入する
