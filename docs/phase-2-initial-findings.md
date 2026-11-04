# knowledge-context-lab Phase 2 検証結果

測定日: 2026-10-30。架空データのみ。GitHub公開・本番変更なし。

## 結論

**総合判断は「追加検証が必要」。小規模での次の候補は「取得方法だけ改善」とし、DB導入は決めない。**

固定した最終20問のうち、引用による採点対象19問すべてで必須根拠が揃った。選定したBは全文Aに対し、返却JSON全体の参照トークンを33,584から18,924へ43.65%削減した。同じ処理をSQLite保存にしたCのpayloadはBと全120組で一致した。これをDB固有の圧縮・品質効果には数えない。

ただし小規模の全文取得はローカルでは速く、Bの中央値1.618msに対してAは0.276msだった。実モデルの回答品質・usage・課金・応答時間・人の訂正負担は未測定で、「同じ回答品質で費用と時間を減らした」とは結論できない。

さらに1,000・10,000文書の類似・旧版・条件違いを混ぜた試験では、元の出典IDにも一致する引用到達率が0になった。全文Aでも同じで、候補検索の失敗を箇所選択やDBで救えていない。21文書の成功を16 botの実運用に一般化しない。

成果として、保存先を揃えた比較器、調整可能な取得ライブラリとCLI、固定問題、失敗を含む生結果、ソーススナップショット、16並列の更新・障害試験を実装した。最適方式を断定する完成サービスではなく、どの改善が効き、どこで破綻するかを再検証できるローカル公開レビュー候補である。

## 比較表

### 前提と既存結果の再現

Python 3.13.12 / SQLite 3.51.2 / macOS 26.5.1 arm64 / tiktoken 0.14.0、参照符号化はo200k_base。Python 3.11以上が実装上の対象で、全対応バージョンの実行は未検証。

元ZIPのSHA256は`79b04341936d2f88c3686fa26f52b6e8c2c97f59360e90adfcd06e812c174cc3`。27ファイルをmanifest照合し、保存した元実装で270行を再実行した。旧結果と時間以外の指標・全payloadが一致した。再現証跡 (`../runs/phase2-baseline/provenance.json`; historical artifact not included in this preview)、比較結果 (`../runs/phase2-baseline/comparison.json`; historical artifact not included in this preview)。同梱されていない実資料の再現ではない。

新問題は改善実装前に開発20問・最終20問として固定した。凍結は00:59:26 UTC、最終設定の固定は01:28:41 UTC、最終評価は01:30:35 UTC。21文書65節で、元の18文書を再利用した自作診断である。独立ベンチマークではない。[FREEZE](../fixtures/phase2/FREEZE.json)、設定選定 (`../runs/phase2-dev-v3/selection.json`; historical artifact not included in this preview)。

### 最終20問・5反復

「全揃い」は必須引用の全包含。正解回答率ではない。分母は19問、残るprivate質問1問は正答数に算入しない。トークンは20問の1回分合計。時間はwarm索引の100試行、単位ms。Aは同じ候補全文を返すため予算を超える。

| 方式・設定 | 予算/問 | 必須引用全揃い | 条件欠落問 | 参照token合計 | query中央値 | p95 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| A 全文、選定設定 | 制限なし | 19/19 | 0 | 33,584 | 0.276 | 0.366 |
| B 段階0 | 1,000 | 17/19 | 2 | 17,029 | 1.612 | 2.051 |
| B 段階0 | 2,000 | 18/19 | 1 | 36,308 | 2.070 | 2.985 |
| B 段階0 | 4,000 | 19/19 | 0 | 44,755 | 2.445 | 3.616 |
| **B 選定設定** | **1,000** | **19/19** | **0** | **18,924** | **1.618** | **2.296** |
| C 選定設定 | 1,000 | 19/19 | 0 | 18,924 | 1.644 | 2.183 |
| B 選定設定 | 2,000 | 19/19 | 0 | 32,980 | 2.105 | 2.848 |
| B 選定設定 | 4,000 | 19/19 | 0 | 34,959 | 2.085 | 3.589 |

全方式・全設定で指定禁止引用のhitと実行エラーは0。選定B/Cは旧版のみの取得0、追加候補0、探索1round、呼び出し1回、取得再試行0。empty結果を「情報なしの正答」として加点していない。

索引を毎query構築するcold_indexの合計中央値/p95はA 13.400/14.213、B 14.758/15.905、C 14.584/15.583ms。OSキャッシュは消去せず、辞書は事前ロードした。B/Cはquery中の保存先I/Oが0で、共通のインメモリ検索を実行する。このわずかな時間差からDB優位は主張しない。

分類別の選定Bは、条件・例外3/3、複数資料2/2、言い換え2/2、現在決定・履歴・提案・長表・引き継ぎ・短い新規・競合・再送・実測/目標の各1/1、情報不足を説明する根拠3/3。private禁止質問は別の0-hit確認であり正答採点外。各分類は少数で統計的保証はない。分類別生集計 (`../runs/phase2-final-v1/categories.json`; historical artifact not included in this preview)。

全結果: summary (`../runs/phase2-final-v1/summary.json`; historical artifact not included in this preview)、JSON (`../runs/phase2-final-v1/results.json`; historical artifact not included in this preview)、CSV (`../runs/phase2-final-v1/results.csv`; historical artifact not included in this preview)、payload (`../runs/phase2-final-v1/payloads.jsonl`; historical artifact not included in this preview)、B/C一致 (`../runs/phase2-final-v1/backend-parity.json`; historical artifact not included in this preview)。

### 改善を1項目ずつ比較した開発20問

1,000token、B、採点対象18問。chainは上から累積。数字は2反復のうち1回分のtoken合計で、同一payloadの繰り返しを品質の標本数に増やさない。

| 変更 | 全揃い | 条件欠落 | token合計 | 判断 |
| --- | ---: | ---: | ---: | --- |
| 段階0 節選択基準 | 14/18 | 2 | 17,038 | 比較基準 |
| + 出典メタデータ共通化 | 17/18 | 1 | 18,466 | 空いた枠に根拠が入り改善 |
| + 状態・期間を候補選定前へ | 17/18 | 1 | 18,790 | この集計は同数。旧候補の競合回帰を別途検証 |
| + 字面の同義語 | 16/18 | 2 | 18,846 | 悪化、選定せず |
| + 候補拡張 | 16/18 | 2 | 18,760 | 追加候補9件でも改善なし |
| + 長節・表分割 | 17/18 | 1 | 19,140 | 一部回復 |
| + query特徴被覆選択 | 17/18 | 1 | 19,127 | 全揃い増えず |
| 段階2 + 分割だけ | 18/18 | 0 | 19,221 | 小規模候補として選定 |
| その候補 + 特徴被覆 | 16/18 | 0 | 19,232 | 必須根拠を落とし不採用 |
| その候補のcosineをBM25へ | 18/18 | 0 | 19,260 | 増益なし、不採用 |
| その候補 + 定義意図の一般語展開 | 18/18 | 0 | 19,221 | 回帰ゲート改善で選定 |

選定は**出典共通化 + 状態/期間フィルター + 分割 + 定義意図展開、cosine、候補3、予算1,000**。元30問中の引用採点対象26問は、定義意図展開前25/26→後26/26。q22とq30も取得した。意味理解全般の改善ではなく、既知のq22から作った限定的な意図展開である。検索器へ正解や問題IDは渡していない。

tokenが増えた行でも全揃いが増えた場合がある。圧縮率単独で選ばない。候補拡張は3→6→12、被覆率・増分・上限で止め、その処理時間を全て含む。選定では不要になった。段階比較 (`../runs/phase2-dev-v2/chain/summary.json`; historical artifact not included in this preview)、追加比較計画 (`../runs/phase2-development-plan.json`; historical artifact not included in this preview)、選定経緯 (`../runs/phase2-dev-v3/plan.json`; historical artifact not included in this preview)、回帰 (`../runs/phase2-dev-v3/definition-regression/results.json`; historical artifact not included in this preview)。

### 100 / 1,000 / 10,000文書

開発側の固定7問、3反復。類似・条件違い・失効版・相反案・無関係文書を増やした。本文hash重複率は追加文書を分母に20.25% / 48.21% / 61.12%。生成比重・実際の件数・更新前後hashはmetadata (`../runs/phase2-load-v1/metadata.json`; historical artifact not included in this preview)。

| 文書数 | B warm中央値/p95 ms | C warm中央値/p95 ms | B単一query冷起動想定 中央値ms | B/C文字列引用到達率 | B/C元出典一致の引用到達率 |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 100 | 2.128 / 2.970 | 2.107 / 2.950 | 60.190 | 100% | 85.71% |
| 1,000 | 7.662 / 9.502 | 8.423 / 10.298 | 635.638 | 85.71% | 0% |
| 10,000 | 122.032 / 156.562 | 120.326 / 225.420 | 12,673.374 | 85.71% | 0% |

A全文も1,000/10,000で文字列85.71%、元出典0%。この到達率は引用ごとの割合を7問平均した診断で、全揃い問数や回答正解率とは異なる。複製文書の情報が同等でも元出典指標は0になるので、全て誤答とは断定しない。一方、相反案に引用された文でも文字列指標は加点し得る。大規模品質を示すには両指標とも不十分である。

| 10,000文書でのローカル作業 | ファイル | SQLite |
| --- | ---: | ---: |
| 初回取り込み ms | 1,866.455 | 460.522 |
| 初回共通索引作成 ms | 9,037.820 | 10,831.863 |
| 1文書の更新commit ms | 2.927 | 2.355 |
| 更新後の全再索引 ms | 11,665.970 | 13,614.090 |
| 更新後保存量 bytes | 26,795,405 | 35,475,456 |
| 更新1回/16queryの償却 ms/query | 851.338 | 971.354 |
| 更新1回/1600queryの償却 ms/query | 129.325 | 128.837 |

保存量はファイル内容のbyte数で、ファイルシステム実割当量ではない。取り込み・差分更新は各規模/backendで1回の観測。償却はシナリオ計算で、実16 botスループットや金銭費用ではない。SQLiteの一括取り込みは速いが、今回の大規模コストは共通索引再構築が支配的。差分索引未実装のため、DBを置くだけでは解決しない。

負荷試験のcoldは3回の再open/rebuildごとに7問を走らせ、setupを各問へ加えた単一query想定値。7問分として足すとsetupを重複計上する。query試行順は入れ替えるが、cold群→warm群の順で、ホスト負荷の影響は除外していない。全18集計 (`../runs/phase2-load-v1/aggregates.json`; historical artifact not included in this preview)、取り込み・更新 (`../runs/phase2-load-v1/startup-events.json`; historical artifact not included in this preview)、償却式の結果 (`../runs/phase2-load-v1/amortization.json`; historical artifact not included in this preview)、378行の生試行 (`../runs/phase2-load-v1/trials.jsonl`; historical artifact not included in this preview)。

### 16 botの更新・障害試験

隔離ローカルSQLite、16worker・独立接続、5反復。初期競合の後は読み直した内容を明示的にmergeして順次再適用する。

| 試験 | 5反復の観測 |
| --- | --- |
| 同じexpected_versionの競合 | 毎回1commit・15conflict、再適用後16botすべてのevent保持 |
| 同request_idの16並列再送 | 毎回1commit・15replay、revision/request各1件増加 |
| 同request_id・異内容 | 拒否、保存tableは変化なし |
| commit後にACKを喪失 | 例外を注入し照会・必要版参照・再送で元revision確定 |
| 途中のtransaction失敗 | triggerで失敗、3table全て0件、同requestの再試行成功 |
| private/shared | owner参照可、他botの参照/履歴/要求照会/書き込み拒否 |
| backup/restore | 全table・版・request履歴一致、保存済requestの再送保持 |
| 復元と検証の所要時間 | 2.195–2.719ms、小さいローカルDBのみ |
| データ損失範囲 | backup後にACK済みのrevision2件・request2件が毎回消失 |
| taskflowスタブ | 未保存・ACK未確認・異record/version・復元で消えたcommitを完了扱いにしない |

RPO=0や高可用性を達成したとは言わない。HTTP断・process kill・disk障害ではなく、明示的な注入とsnapshot復元。自然文のmerge、分散認証、D1の再現ではない。生イベントJSON (`../runs/phase2-faults-v3/results.json`; historical artifact not included in this preview)、CSV (`../runs/phase2-faults-v3/results.csv`; historical artifact not included in this preview)、測定定義 (`../runs/phase2-faults-v3/metadata.json`; historical artifact not included in this preview)。初期のfaults v1/v2は測定不足があり、採用判断と公開候補から除外した。

## 失敗例

1. **最終p2f09: 複数の条件。** 段階0・1,000tokenは「予報だけで欠航と断定したり、運航すると決めたりしてはならない。」を落とした。短いpayloadだけを成功とすると、風と食事条件を同時に扱う問いの必須例外を失う。選定Bでは取得した。
2. **最終p2f15: 長い表。** 段階0は「長い条件表は見出し・単位・例外を保持して扱う。」を落とした。表を行で分割し、ヘッダーと全体注記を伴わせた候補では取得した。ただし一般文の離れた例外まで自動保存する保証ではない。
3. **開発p2d10: 同義語を増やすほど悪くなる場合。** 同義語・候補拡張付きでは別の関連資料が枠を使い、必要な条件を落とした。query特徴の被覆は正解根拠の被覆ではない。余分な改善を外した比較で18/18へ戻った。
4. **既知q22: 略称を問う言い換え。** 候補3/6/12、cosine/BM25、alias有無の12設定を調べても1,000tokenで落とした。定義意図へ一般語を追加して回帰を通した。診断記録 (`../runs/phase2-q22-diagnostic-v1.json`; historical artifact not included in this preview)。この問題への成功から一般的な意味検索の成功は推定しない。
5. **大規模での候補混雑。** 1,000文書のp2d05「Relay引継ぎと完了判定に必要なものは？」では候補3件が短い担当引き継ぎの複製で埋まり、返答も担当botの文を3回繰り返した。完了判定の必要引用は0件。元IDだけが違う問題に加えて、実際の根拠不足がある。全規模7問、計21payloadを再構成し元測定hashとの一致も確認した。失敗を含むpayload (`../runs/phase2-load-diagnostic-v1/payloads.json`; historical artifact not included in this preview)。SQLiteでも同じなので保存先変更を対策に選べない。
6. **snapshot後の確定書き込みは失われる。** バックアップ後の2件が復元で消えることを実測した。taskflow完了との整合はスタブで拒否できても、運用上の復旧・再処理手順を解決したわけではない。

## 再現方法

[README](../README.md)のPython環境・依存・辞書を用意する。初回取得後はオフライン実行可能。今回の再インストールはローカルにあるbuild backendを使うno-index経路でも通した。手作業で毎回installする必要はなく、まずpreflightを使う。

```bash
export TIKTOKEN_CACHE_DIR="$PWD/tokenizer-cache"
.venv/bin/python scripts/preflight.py
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python scripts/verify_phase2_artifacts.py

# 元実装の再生。現在の改善コードと混ぜない
PYTHONPATH=runs/phase2-baseline/source .venv/bin/python -m context_lab.evaluate \
  --corpus fixtures/synthetic/corpus.json --queries fixtures/synthetic/queries.json \
  --output runs/phase2-baseline-replay --unit o200k_base \
  --budgets 1000,2000,4000 --candidate-documents 3

# 当時の段階比較を保存したソースで再生
PYTHONPATH=runs/phase2-dev-v2/chain/source .venv/bin/python scripts/run_phase2_development.py \
  --output runs/phase2-dev-replay --repeats 2

# 定義意図だけを追加する開発・回帰比較
PYTHONPATH=src .venv/bin/python scripts/run_phase2_regression_selection.py \
  --output runs/phase2-regression-selection-replay

# 当時固定した設定で最終問題を再生
.venv/bin/python -m context_lab.phase2_eval --mode final \
  --selection runs/phase2-dev-v3/selection.json \
  --output runs/phase2-final-replay --repeats 5

.venv/bin/python -m context_lab.load_test --corpus fixtures/phase2/corpus.json \
  --queries fixtures/phase2/dev.json --selection runs/phase2-dev-v3/selection.json \
  --output runs/phase2-load-replay --sizes 100,1000,10000 --repeats 3
.venv/bin/python -m context_lab.faults --output runs/phase2-faults-replay --repeats 5
```

出力が存在したら別名を使う。既存fixture・結果を消して実行しない。最終問題を見た後の新改善には新しい未使用問題が要る。実行時間・timestamp・thread競合の勝者は完全一致を期待しない。

現環境で48テストが通り、保存済み360payloadのtoken・予算・権限・原文spans、全試行のA/B/C候補一致、120組のB/C一致、378行の負荷集計、5回の障害生記録を別スクリプトで検査した。旧fixture・旧結果9ファイル、新fixture3ファイルのhashも維持した。検査証跡 (`../runs/phase2-validation/artifact-audit.json`; historical artifact not included in this preview)。検索実装hashに加え、評価器hashと各実行のsourceコピーを参照する。[測定契約](phase-2-protocol.md)。

wheelを作り、新しい仮想環境へオフラインでインストールして、公開CLIから両backendの永続化・検索・同一payloadと期待した根拠を確認した。このインストール試験は外部依存なしのunicode_chars単位で、トークン評価は上記の本環境で行った。wheel検証 (`../runs/phase2-validation/wheel-smoke.json`; historical artifact not included in this preview)、全検証の記録 (`../runs/phase2-validation/checks.json`; historical artifact not included in this preview)。

## 未検証事項

- **未測定:** 実モデルによる回答・根拠の誤読・回答保留・後続botの作業完了、モデルusageと請求額、キャッシュ課金、end-to-end時間、人の訂正分数。通信許可はあるが、利用するモデル・隔離先・課金上限が固定されていないため実行していない。
- **未測定:** D1、実taskflow、認証済み16botの同時read/write、HTTP喪失、process/disk故障、遠隔バックアップ、継続復旧、長期運用の可用性。ローカルSQLite成功をD1成功としない。
- **未測定:** 独立評価問題、実資料、別言語分布、複数seed、より多い固有事実、10,000以上、独立process冷起動、差分索引、SQL FTS、埋め込み・reranking。DBの一般的な優劣は決まっていない。
- **未実装:** 一般的な条件・例外の意味的束ね、元資料と複製・相反案の同等性判定、source更新の自動同期、二つのstoreの統合。callerのactorは認証済みと仮定する。所有者以外の返却は防いでも索引統計の側信道まで証明していない。
- **未完了:** ライセンス確定、第三者による環境別再現、公開手続き。MITは候補で、同梱元資料の権利確認前にライセンスを付与したとは扱わない。GitHub公開・本番移行・実資料の持ち込みはしていない。

## 次の判断

現在は**ファイル保存の取得改善を小規模試験の基準実装として残す**。SQLiteの比較実装とKnowledgeStoreの整合性部品も残すが、D1正本への移行や本番採用は決定しない。

次は、大規模で失った元出典を追うため、複製の束ねと多様な候補選択を別々に試す。今回の最終問題は回帰へ回し、出典の同等性・相反関係・回答保留を採点できる新しい問題を先に固定する。差分索引は検索品質の改善と別の実験にする。

モデル・料金上限・隔離先を固定できた時点で、同じrequest/payloadを使って全文Aと改善Bの回答正確性、必須条件、出典の一致、usage、p50/p95、訂正時間を比較する。必要品質を満たした場合だけ実費と時間で選ぶ。DBはさらに、更新頻度・同時書き込み・復旧要求を満たす必要性と追加費用を根拠に判断する。

公開レビュー候補の価値は、44%という数字だけでなく、DB効果の混同を避ける比較器、破綻条件が分かるデータ、再現できる障害試験にある。[MIT候補と公開条件](license-candidate.md)を確認してから公開判断を行う。
