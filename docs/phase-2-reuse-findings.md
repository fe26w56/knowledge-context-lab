# Phase 2：確認済み原文の再利用と回答の安定性

2026-11-03。自作の架空診断。独立ベンチマークではない。外部公開・本番切替なし。

## 結論

**既知のテーマを参照する処理には「取得方法だけ改善」を採用する。** 明示的なproject/topicで対象を決め、事前に内容確認した原文範囲を、出典・版・条件・例外とともに返す。関連資料の訂正や追加があれば、fresh snapshotでは古い内容を返さず再確認待ちにする。この経路をローカルライブラリに実装した。自由検索やNotion全体の置き換えを決定したものではない。

同じ資料集合・同じ確認状態を持つ全文方式に対し、確認済み原文範囲方式は、最終診断の参照入力中央値を475.5→382 token（19.7%）減らした。実モデルでは、12意図×3反復の36回答で、全文・範囲方式とも必要事実への回答または安全な不明回答が36/36だった。範囲方式の実API入力合計は24,801→21,969（11.4%減）。schema・指示も入力に含むため、参照tokenの削減率とは異なる。

全体の資料を100→1,000→10,000件に増やしても、固定したテーマの入力は増えなかった。ただし**この性質は同じtopicで絞った全文方式にもある**。他テーマの増加を切り離した効果であり、DBや範囲選択だけの効果として数えない。対象テーマ自身に新しい資料が増えれば、再確認と入力増加が必要になる。

第三の「モデルが引用IDを選ぶ」方式は原文引用を正確に復元できたが、必要事項を2回省いた。回答方式の標準には採用しない。引用の正確さと回答の完全性は別の性質である。

今回の証拠は、少数の既知テーマで**低い入力量と同じ観測品質を両立した**ことまで。母集団での非劣性や、モデルの誤答確率が有意に低下したという統計的証明ではない。確率に委ねる処理を減らすため、範囲選択・版照合・失効をコードの契約に移した。確認する人の工数を含む運用全体の費用削減は未測定。

## 比較表

### 資料数と入力量

最終12意図×2質問表現×3資料数×4方式＝288行。各資料数で回答可能10意図×2表現の20/20が必要根拠を全て保持した。以下はo200k_baseの参照入力token中央値であり、実API課金tokenではない。巨大な全文をモデルに送った測定でもない。

| 取得方式 | 100件 | 1,000件 | 10,000件 | 効果の帰属 |
|---|---:|---:|---:|---|
| 同projectを全部渡す | 16,164 | 157,354 | 1,568,570 | 未整理の比較用入力 |
| 同topicの全文 | 429 | 429 | 429 | 明示的topicによる絞り込み |
| 同topicの確認済み全文 | 475.5 | 475.5 | 475.5 | 同じ確認・版契約の基準 |
| 同topicの確認済み原文範囲 | **382** | **382** | **382** | 上段に対して19.7%削減 |

確認済み方式は両方とも状態判定24/24、原文・状態保持24/24、private漏えい0。全project方式は無関係な資料があるため、未知/権限外topicでもavailableとなる4行があり、状態判定20/24。検索器・生成器に正解引用や問題IDは渡していない。topicはすべての方式に同じ業務参照キーとして与えた。[行データ](../runs/phase2-reuse-final-v1/rows.jsonl)／[集計](../runs/phase2-reuse-analysis-v1/summary.json)

### 実モデルの反復

10,000件の同じworkspaceから、最終12意図の第1表現を3回ずつ生成。gpt-6-luna、reasoning/temperatureの上書きなし、各意図で方式の呼出順を巡回、再試行0。全108生成成功。各方式は回答可能30回＋不明6回。入力countと実usageは108/108一致した。**36回は12意図の反復であり、独立した36問ではない。**

| 指標 | 確認済み全文 | 確認済み原文範囲 | 同範囲＋引用ID |
|---|---:|---:|---:|
| 必要事実を満たす回答 | 30/30 | **30/30** | 28/30 |
| 未登録・権限外への安全な不明回答 | 6/6 | **6/6** | 6/6 |
| 根拠のない追加断定なし | 36/36 | 36/36 | 36/36 |
| 本文/範囲からの厳密な引用 | 34/36 | 36/36 | 36/36 |
| メタデータも含めた提供資料による引用支持 | 36/36 | 36/36 | 36/36 |
| 実入力token合計 | 24,801 | **21,969** | 22,437 |
| 実入力token中央値 | 722.5 | 636.5 | 649.5 |
| 出力token合計（reasoning込み） | 15,917 | 14,162 | 12,162 |
| 内訳：reasoning token合計 | 4,502 | 3,344 | 2,784 |
| usageと料金表による推計USD | 0.010273215 | 0.009277900 | 0.008324700 |
| 保守単価での台帳計上USD | 0.026772075 | 0.023766600 | 0.022374000 |
| 呼出時間中央値（秒） | 5.44 | 5.24 | 4.73 |
| 3反復とも完答/安全不明だった意図 | 12/12 | 12/12 | 10/12 |

全文→原文範囲で実入力合計11.4%、出力合計11.0%、usage料金推計9.7%減。時間差は小さく、速度の優越を確定しない。引用IDの低い出力費用には省略の影響もあり、その安さを品質を保った成果としない。本文引用2件の失敗はversion/statusのJSON引用で、提供メタデータによる意味的支持はある。捏造とは数えない。

同一request hashは各方式12/12意図で固定された。回答文そのものが3回とも完全一致した意図は全文1/12、範囲1/12、ID0/12。表現の揺れは残るが、これをそのまま意味誤答とはしない。独立した人間による盲検採点ではなく、rootによる全108回答の照合と別agentによる意味・引用支持監査を行い、機械的引用検査を分けた。[保存応答・入力・usage](../runs/phase2-reuse-model-public-v1/results.json)／[再集計](../runs/phase2-reuse-model-analysis-public-v1/summary.json)／[root意味監査](../runs/phase2-reuse-model-root-review-v1/review.json)

追加保守計上は0.072912675 USD、共通台帳は9.726117025/10 USD。過去の未確定予約2件を解放せず含めている。実請求額・クレジット残高は未測定。[台帳集計](../runs/phase2-reuse-analysis-v1/accounting.json)

### 更新・並列読み取り・準備コスト

| 実行した試験 | 結果と範囲 |
|---|---|
| 未確認→確認→訂正→再確認→同topic資料追加 | 未確認/変更後はfresh viewでneeds_review、sources空。再確認後は新原文を返す |
| 上記4状態で各16並列読み取り | 64読み取りで各状態が一致。小さな架空データでのローカル実行 |
| 古いsnapshot | 訂正後も古い観測を再現。最新状態として利用できない |
| 新資料追加の検知 | 参照済みIDだけでなく同topicのsource集合を照合し、追加でも失効 |
| 範囲・引用の原文照合、別topic追加、再送、backup/restore | 一致。別topic追加でpayload不変、同request再送で二重更新なし |
| sourceの廃止 | 依存する確認結果をfresh viewで停止 |
| scope/owner変更 | Storeが拒否しhead不変。権限取消の成功は測っていない |

10,000件の最終実行ではimport 14.22秒、既存manifestの96topic書き込み1.63秒。これは人の内容確認時間ではない。初期開発ではtopicごとにsnapshotを作ったため46.67秒かかったが、同じactorの構築用snapshot再利用で1.59秒になり、全192 dev payload hashが変更前後で一致した。範囲選択とは独立した準備処理の改善である。

10,000件で**すでに構築したviewの16取得**は合計0.73ms、**16人分のfresh snapshot構築と取得**は合計14.73秒だった。この両者を混ぜて高速化率を宣伝しない。更新なしの同一状態の並列読取であり、16体の認証済み本番agentや競合writerを測ったものではない。[最終実行時間](../runs/phase2-reuse-final-v1/datasets.json)／[並列取得](../runs/phase2-reuse-final-v1/concurrency.json)／[更新試験v3](../runs/phase2-reuse-lifecycle-v3/receipt.json)

### 重複範囲の統合

前回の親節展開payloadに、重なる・隣接する同sourceの範囲だけを統合する関数を追加した。保存済み90反復行（22種類のcontext）のtoken合計は210,316→186,135、11.50%減。必要原文とメタデータは保持し、不一致の重複は拒否する。これは同じpayloadが繰り返される重み付きの集計であり、新しい90問ではない。モデル再生成なしの回帰試験で、回答品質の向上やDB効果とは呼ばない。[範囲統合の記録](../runs/phase2-span-compaction-v3/summary.json)

## 失敗例

- 引用ID方式は`final-04 / round1`で「分類追加はレビューする」を、`final-02 / round3`で「閾値変更は再承認する」を回答から落とした。選択した引用は正確でも、全事項を回答する保証にはならなかった。
- 全文方式の`final-02 / round2`は`version`、`final-01 / round3`は`status`をJSONから引用した。情報は実在するが本文引用契約には合わない。今後は本文引用と属性の根拠を別の型で表す余地がある。この最終問題を見て変更した結果を新しい未使用評価とは呼ばない。
- 初期の意味監査は、全文方式が「一覧票FI-6の内容そのものは記載されていない」と留保した回答を誤りとした。実際は一覧票への参照しか与えておらず、原本が提供されたとはいえない。rootで支持範囲を再確認し、誤答から除外した。参照があることと原本を読めることを混同しない。
- 既存Workspaceのtopic保存は、参照したsourceの訂正を検知できても、新しい同topic資料の追加後に古いpayloadをcurrentとして返すケースが再現した。今回の別moduleはsource集合の照合で防ぐ。既存APIを自動で置き換えたわけではない。[既存経路の再現](../runs/phase2-reuse-existing-gap-v1/receipt.json)
- 開発fixtureの初版にはgold不完全・private設定・質問表現数等の問題があった。監査で修正してから新fixtureを凍結した。最終問題を使った検索実装の調整はしていない。更新試験の古いreceipt v1/v2にも読み取り回数等の記載の問題があり、実際の64並列読み取りを記録したv3を採用した。

## 再現方法

[事前契約](phase-2-reuse-protocol.md)、[固定fixture](../fixtures/phase2-reuse-v1/FREEZE.json)、[開発後の方式選択](../runs/phase2-reuse-selection-v1/selection.json)を保存した。原文範囲manifestを質問より先に作り、dev8/final12、各2表現を実装前にhash固定した。最終開封後は方式を変更していない。複数資料依存はdev2件/final1件。最終12意図は全てcurrent modeである。

```sh
python3.11 -m venv .venv
.venv/bin/python -m pip install -e '.[tokens]'
export TIKTOKEN_CACHE_DIR="$PWD/tokenizer-cache"
.venv/bin/python scripts/preflight.py
.venv/bin/python -m unittest discover -s tests
.venv/bin/python scripts/demo_reviewed_context.py

# 新しい出力先に再現。API呼出しなし。
.venv/bin/python scripts/evaluate_reuse.py --split dev \
  --output runs/phase2-reuse-dev-repro-01
.venv/bin/python scripts/evaluate_reuse.py --split final \
  --selection runs/phase2-reuse-selection-v1/selection.json \
  --output runs/phase2-reuse-final-repro-01
.venv/bin/python scripts/exercise_reviewed_context_v2.py \
  --output runs/phase2-reuse-lifecycle-repro-01/receipt.json
.venv/bin/python scripts/analyze_reuse_model.py \
  --run runs/phase2-reuse-model-public-v1 \
  --fixture fixtures/phase2-reuse-v1 \
  --output runs/phase2-reuse-model-analysis-repro-01
```

入力件数が増える最終取得診断は時間とディスクを使う。モデル品質は保存された応答を分析するだけなら無課金。モデルを新規生成する場合は、`scripts/run_reuse_model.py`にselection、生成済みworkspace、既存共有ledger、秘密keyの外部保存場所、新しいoutputを渡す。runnerは同じ要求の事前token計数と既存上限確認を行う。残高に収まらなければ停止し、台帳を作り直したり予約を消したりしない。今回の全108回答の再実行は、現在の保守残枠では事前予約額に届かない。

配布用の保存応答は、原本を保持したままopaqueなprovider出力とprovider response ID等だけを除去したコピー。request・回答・payload・usage・費用は108件すべて原本と一致し、分析行も完全一致した。[除去項目とhash](../runs/phase2-reuse-model-public-v1/export.json)。公開はしていない。

Python 3.11/3.13の本体テスト、固定hash、ライフサイクルとローカル配布検証の記録は[検証receipt](../runs/phase2-reuse-validation-v1/receipt.json)。使い方とsnapshot寿命の注意点は[利用ガイド](reviewed-context-guide.md)にある。

## 未検証事項

- 自由文から正しいtopicを見つける処理、曖昧な質問、複数topicに跨る探索。同topicに大量の新資料が増えた場合の入力上限と確認負担。
- 独立ベンチマーク、実業務の質問分布、より多数の未使用意図での非劣性。最終は12意図で、3反復を独立標本として水増ししない。
- 最終問題でのhistory/proposal/needs_review生成回答。これらの状態はdevや単体/更新試験で扱ったが、今回の最終実モデル回答には含まれない。
- 人手確認・知識整備・更新保守を含む総費用と、16agent間の実際の重複作業削減。架空manifestの記録時間を人手レビュー費用としない。
- fresh snapshot構築の大規模性能、同時更新者、実認証、scope変更/権限取消、Notion自動同期、D1でのこの新経路。以前のHTTPS既知ID取得試験とは別である。
- 生成文の完全再現、誤答確率の統計的な低下、実請求額、APIクレジット残高。

## 次の判断

確認済み原文範囲＋版/同topic集合の失効を、**既知topic専用の選択可能な経路**として残す。生成方式は今回完答した既存形式を使い、引用ID方式は検証用に留める。DB導入を節約の理由にはしない。保存先の判断は履歴・競合・一貫したsnapshotが必要かで行う。

この時点で「すべて追加検証待ち」ではない。既知topicへの入力削減と更新時の停止契約は実装・測定できた。一方、全面移行は見送る。次に対象を広げるときは、自由文ルーティングか同topic内の増加を一つずつ測り、人の再確認時間を加えて全体の利益を判断する。今回の最終問題は以後回帰用に扱う。
