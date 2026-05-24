# road_database_project 技術仕様

## 1. 目的

`road_database_project` は、交通シミュレーションで使う道路ネットワークを、シミュレーションしやすい内部構造へ変換するための道路DB設計プロジェクトです。

OSMのWayは地図データとしては有用ですが、そのまま交通シミュレーションに使うと、道路形状、交差点接続、進行方向、通行規制、観測点対応が同じ構造に混ざりやすくなります。そこで本プロジェクトでは、道路ネットワークをトポロジーとジオメトリに分け、directed edge ベースで扱う構造を試作しました。

## 2. forward_traffic_ml との関係

このプロジェクトは、`forward_traffic_ml` を進める中で生まれました。

順方向シミュレーションでは、車両を入口から発生させ、道路リンク上を前進させ、交差点で次のリンクを選択します。そのため、交差点での接続関係や分岐候補を明確に扱う必要があります。

当初は OSM Way を直接使っていましたが、次のような問題がありました。

- OSM Wayは地図編集上の単位であり、必ずしもシミュレーション上の移動リンクではない
- 1本のWayに複数の交差点や形状点が含まれることがある
- 双方向道路、右左折規制、交差点接続を扱うには追加処理が必要
- 描画用の滑らかな形状と、経路探索用の接続構造を同じ単位で扱うと複雑になる
- 観測点をどのリンクに対応付けるかを検証しにくい
- 分岐重みを学習・補正するとき、どの分岐を1単位として扱うかが曖昧になる

このため、道路ネットワークをシミュレーション向けに整理する基盤として `road_database_project` を作成しました。

## 3. 基本設計

道路DBでは、道路を次の要素に分けて扱います。

| 要素 | 役割 |
|---|---|
| `topology_node` | 交差点や接続点 |
| `topology_edge` | 接続関係を表す抽象的な道路リンク |
| `directed_edge` | 車両が一方向に移動できるリンク |
| `geometry_edge` | 地図上に描画するための形状 |
| `turn_relation` | 交差点での進行可能・禁止関係 |
| `analysis_segment` | 観測点対応や集計に使う分析単位 |

### 3.1 トポロジー

トポロジーは、車両がどのノードからどのノードへ移動できるかを表します。シミュレーションや経路探索では、道路の見た目よりも、接続関係が重要です。

### 3.2 ジオメトリ

ジオメトリは、道路を画面上で描画するための折れ線形状です。地図として見やすくするために必要ですが、経路探索や分岐選択では必ずしもそのまま使う必要はありません。

### 3.3 directed edge

`directed_edge` は、車両が一方向に進む単位です。双方向道路は、向きの異なる2本の directed edge として扱います。

順方向シミュレーションでは、この directed edge を車両移動と分岐学習の基本単位にします。

### 3.4 turn relation

`turn_relation` は、交差点でどの incoming edge からどの outgoing edge へ進めるかを表します。

OSMの `restriction` relation がある場合は、右左折禁止などの制約を取り込むことを想定しています。公開版のプロトタイプでは、明示的な規制情報を扱うための構造を用意しています。

## 4. 変換スクリプト

### 4.1 `scripts/build_topology_prototype.py`

このスクリプトは、OSM XMLを入力として、道路DB試作用のGeoJSON/JSONを生成します。

主な処理は次の通りです。

1. OSM XMLから車道系WayとNodeを読み込む
2. OSM Wayを隣接Node間の区間へ分解する
3. トポロジー用のNode/Edgeを作る
4. 単方向の directed edge を作る
5. 描画用の geometry edge を作る
6. 交差点と進入方向を抽出する
7. OSM restriction に基づく turn relation を作る
8. 分析用 segment を作る
9. 各レイヤーを GeoJSON/JSON として出力する

出力例は次のようなファイル群です。

```text
output/prototype_xxx/
├── osm_roads.geojson
├── geometry_edges.geojson
├── topology_nodes.geojson
├── topology_edges.geojson
├── directed_edges.geojson
├── intersections.geojson
├── intersection_approaches.geojson
├── turn_relations.geojson
├── turn_relations.json
├── analysis_segments.geojson
└── summary.json
```

公開版では、これらの生成済み出力は含めていません。

## 5. ビューア

`viewer/` は、`scripts/build_topology_prototype.py` で生成したGeoJSON/JSONを確認するための静的ビューアです。

| ファイル | 役割 |
|---|---|
| `viewer/index.html` | 道路DBレイヤーを切り替えて表示するHTML |
| `viewer/app.js` | GeoJSON読み込み、描画、レイヤー切り替え、統計表示 |
| `viewer/styles.css` | ビューアのスタイル |

ビューアでは、次のようなレイヤーを確認することを想定しています。

- OSM roads
- Geometry edges
- Topology edges
- Directed edges
- Intersections
- Intersection approaches
- Turn restrictions
- Analysis segments
- Connected components

公開版には `output/` を含めていないため、ビューアを開いてもそのままではデータ表示できません。生成済みデータを公開しない理由は、OSM由来の加工済みデータや大規模GeoJSONをリポジトリに含めない方針のためです。

## 6. 公開版で除外しているもの

公開版には、次のデータを含めていません。

- OSM XMLの元データ
- OSM由来の加工済みGeoJSON
- 道路DBの生成済み `output/`
- forwardモデルで利用した道路DBスナップショット
- 観測点位置情報や交通量と結合した派生データ

公開版では、データそのものではなく、道路DBの設計方針、変換スクリプト、ビューアの構造を示すことを目的としています。

## 7. 今後の展望

今後は、この道路DBを `forward_traffic_ml` の標準的な道路ネットワーク表現として利用することを想定しています。

具体的には、次の改善が必要です。

- directed edge ベースの経路探索を安定させる
- 観測点を directed edge や analysis segment へ正確に対応付ける
- OSM turn restriction をより正確に扱う
- 車線数、速度制限、道路種別などの属性を補正モデルへ渡す
- トポロジーとジオメトリを分離したまま、ビューアで検証しやすい形式を保つ
- forwardモデルの分岐重み学習と接続する
- e-Stat や国土地理院、国土数値情報などの外部GISデータを統合し、人口、土地利用、施設、行政区域などを道路ネットワークと重ねて扱えるようにする
- 交通シミュレーション用の道路DBに留めず、都市分析や交通需要推定にも使える複合的なGIS基盤へ発展させる
