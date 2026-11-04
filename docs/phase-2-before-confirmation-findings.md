# Phase 2 findings — 実モデル検証中

実行日: 2026-10-30。架空データのみ。GitHub公開・本番移行はしていない。初回Phase 2の報告は[変更せず別名で保存](phase-2-initial-findings.md)した。本書はその後の改善・測定・公開準備を扱う。

## 結論

**2026-11-02 更新:** 通信設定と既存キーでの認証を確認し、実モデル `gpt-6-luna` で449回（smoke 1、主比較320、16 actor別batch 128）を実行、すべてAPI正常完了した。使用量・費用記録 (`../runs/phase2-live-accounting-20261102-v1/summary.json`; historical artifact not included in this preview)の名目料金推定は0.2176 USD、保守的計上は過去setupの0.02 USD保留を含め1.5526 USD未満。請求書・credit残高は未測定。

主比較の採点 (`../runs/phase2-model-quality-summary-20261102-v1/result.json`; historical artifact not included in this preview)は固定rubricに対してA/Bそれぞれ49/80・53/80だが、問題と資料の意味やdraft状態に矛盾・曖昧さが見つかった。これは信頼できる一般的正答率ではなく、採用結論には使わない。未知問題による確認データを追加している。元のfixture/回答/採点/配布物は変更していない。下の「実モデル未測定」は実行前の履歴であり、[更新前の全文](phase-2-pre-model-findings.md)も保存した。最終判断は追加確認後に更新する。

**継続作業中（2026-10-30、completion 系列）。0.3.0rc1は保存済みの中間成果であり、新しい0.4.0rc1の配布準備も、ユーザーが求めるOSSの完成とは扱わない。** 新しい最終20問では、同候補の全文Aと断片Bの出典付き引用保持が全ペアで一致し、返却tokenは44.0〜61.3%減った。80/100文書では18/18、1,000/10,000文書では17〜18/18で、残り2問は情報不足のため引用保持の成功率から除外している。検索処理は遅くなっており、実モデルの回答品質・実課金・総時間は未測定。**取得方法の改善が有望だが、総合判断は引き続き「追加検証が必要」。**

**総合判断は「追加検証が必要」。DB導入を採用する根拠は得られなかった。** 小規模な取得処理には改善の余地があるが、「16体のエージェントが同じ品質をより安く速く扱える最適解」とは確認できていない。

公開する価値がある部分は、出典・状態・時点・原文位置を保つ予算付き検索ライブラリと、取得方法／保存先／候補数／予算の効果を分けて失敗まで再現できる評価キットである。CLIの実用デモ、同梱された設定、Python API、wheel/sdist、MIT本文、貢献手順、セキュリティ境界、CI設定を用意した。旧0.3.0rc1配布物を保存したまま、新しい0.4.0rc1にcompletion設定を追加している。既定設定は互換性のためreleaseのまま、`--profile completion`で明示的に選ぶ。運用方式の最終採用ではない。

完全一致の複製を索引でまとめ、候補を3件から6件へ増やす構成を開発データで選んだ。別の最終20問のうち採点可能な17問について、86文書では17/17、1,000文書では15〜16/17、10,000文書では3seedとも14/17の**事前定義された出典付き引用**を取得した。未解答3問は成功に数えていない。これは回答の正しさや、質問が本当に要求する根拠全体の完全性とは別の指標である。

特に、短い文書では断片ごとの原文位置・状態メタデータの費用が上回り、BはAより大きくなった。初回Phase 2の43.65%削減は別データでの結果であり、一般化できない。大規模での読み取り時間は短縮したが、参照token増加・索引構築・更新後の再構築を含めた業務上の費用削減は示していない。

## 比較表

### 継続検証の開発結果（採用判断は未完了）

自作の[completion-v7](../fixtures/phase2-completion-v7/README.md)は80文書・160節、開発20問／最終20問。採点対象18問、情報不足2問。問題と正解の意味は実装前のv6と同一だが、本文と節の不一致を17文書で修復し、全文を検索できる節を追加したv7は最初の改善実装より後に固定された。この時系列の制約を隠さない。v1〜v6の不完全な入力と失敗した実行は残してあり、有効な測定の前に修復した。自作診断であり、独立ベンチマークではない。

以下はBの4,000参照token予算、80文書＋1,000文書×3 seed。入力は同一で、各変更を独立した設定で比較した。token合計は情報不足2問を含む20問×4集合の返却JSON全体。取得量の削減だけを回答品質や実課金の削減とは呼ばない。

| 変更 | 必須の出典付き引用を全保持 | 返却token合計 | 測定 |
|---|---:|---:|---|
| 以前の検索、候補6件 | 52/72 | 213,681 | dev-v2 |
| 有効な節に基づく文書順位だけ変更 | 53/72 | 212,714 | dev-v2 |
| 引用範囲の結合・省略可能なnull除去だけ変更 | 52/72 | 198,548 | dev-v2 |
| 上記2変更を組み合わせ | 53/72 | 197,200 | dev-v2 |
| 類似候補の偏りを抑制（重み0.5） | 65/72 | 195,996 | dev-v3 |
| 同じ重みで候補12件へ | 70/72 | 315,391 | dev-v4 |
| 候補12件の重みを0.8へ | 71/72 | 315,212 | dev-v4 |
| 節の種類に依存せず未採用状態を現在ルールから除外 | 71/72 | 315,687 | dev-v5 |
| 各候補文書から順番に断片を選択 | 72/72 | 316,356 | dev-v6 |

生データはruns/phase2-completion-dev-v2 (`../runs/phase2-completion-dev-v2/summary.json`; historical artifact not included in this preview)〜dev-v6 (`../runs/phase2-completion-dev-v6/summary.json`; historical artifact not included in this preview)。各trialでA/B/Cの候補一致とB/Cの完全なpayload一致を検査した。フィルター、順位、候補数、引用形式の寄与はDBの効果に含めない。現在ルールに非採用の断片を返す件数も後続の選定ゲートに追加した。全文Aには節ごとの状態がないため、同じ項目で状態安全性を証明したとは扱わない。

同じ構成を10,000文書でも開発比較 (`../runs/phase2-completion-dev-large-v1/summary.json`; historical artifact not included in this preview)した。3 seedとも18/18で出典付き引用を保持し、20問分の全文Aは121,946 / 137,433 / 137,374 token、B/Cは79,029 / 78,999 / 79,019 tokenだった。返却量は35.2% / 42.5% / 42.5%減少した。一方、Bの検索p95は173 / 132 / 131ms、同候補全文Aは113 / 84 / 85msで、検索処理だけならBの方が遅い。モデル待ち時間を含めた改善は未測定。選定設定とコードhash (`../runs/phase2-completion-selection-v1/selection.json`; historical artifact not included in this preview)を固定してから最終問題を実行した。

### 継続系列の最終20問

最終測定 (`../runs/phase2-completion-final-v1/summary.json`; historical artifact not included in this preview)は各条件2反復。以下は選定予算4,000、tokenは1反復の20問合計。最終問題は選定後に初めて実行し、この結果を検索の再調整には使っていない。

| 文書数 | 以前のB：出典付き引用全保持 | 選定A/B：同指標 | 同候補全文Aからのtoken削減 | 検索p95 A→B |
|---|---:|---:|---:|---:|
| 80 | 18/18 | 18/18 | 56.6% | 8→42ms |
| 100 | 18/18 | 18/18 | 61.3% | 12→49ms |
| 1,000（3 seed） | 10〜14/18 | 17〜18/18 | 44.0〜50.9% | 40〜43→86〜92ms |
| 10,000（3 seed） | 7〜8/18 | 17〜18/18 | 52.5〜55.2% | 97〜100→159〜165ms |

問題ごとのpaired確認 (`../runs/phase2-completion-analysis-v1/paired.json`; historical artifact not included in this preview)では、20問×8集合×2反復の320ペア（採点対象288）でA成功/B失敗は0、逆も0。選定B/Cのhashは320/320一致し、scope/state/forbidden違反0。これは本文抽出が全文Aに対して指定引用を追加で落としていないという結果であり、モデルが同じ回答品質を出す保証ではない。以前のBには、現在ルール要求でdraft等の断片を返す状態違反があり、単に引用の文字列が揃ったケースも安全な採用とは扱わない。

最終payload監査 (`../runs/phase2-completion-audit-final-v2/audit.json`; historical artifact not included in this preview)は2,880保存payloadを検査し、token/hash・出典metadata・原文位置・候補/保存先の一致・固定コードからの再生成すべてで不一致0。開発2,880件 (`../runs/phase2-completion-audit-dev-v2/audit.json`; historical artifact not included in this preview)と大規模開発2,160件 (`../runs/phase2-completion-audit-large-v2/audit.json`; historical artifact not included in this preview)も同様。監査v1は文字数とtokenの取り違えなどの実装不備で無効化し、根拠として使っていない。

ローカル更新と検索の統合はcompletion-snapshots-v3 (`../runs/phase2-completion-snapshots-v3/20261030T100105.900183Z-c969ccbb/results.json`; historical artifact not included in this preview)で実行した。16 actorの書込み16件＋snapshot読取り16件、処理区間の最大重なり16、版・private分離・自身の資料取得・検索結果の本文digest一致は16/16。SQL失敗後の非可視性、応答消失後の再試行で版が増えないことも確認した。backup後の承認済み2版はrestoreで失われることを記録した。これはSQLite上のローカル測定であり、16モデルの実行やD1、分散可用性の検証ではない。

### 実験条件と出典

Python 3.13.12 / macOS arm64 / SQLite 3.51.2 / tiktoken 0.14.0 / o200k_base。参照tokenは返却JSON全体。時間は同一プロセス内のwarm索引で、各trial前に文字列token数キャッシュをクリアし、辞書は読み込み済み。OSキャッシュは消去していない。索引の再オープン・構築は別測定。独立した実環境の平均性能やネットワーク時間ではない。

固定データは[release-v6](../fixtures/phase2-release-v6/README.md)の86文書・246節、開発20問／最終20問。テーマを分離した自作診断であり、独立ベンチマークではない。v1〜v5は出典・問題文・カテゴリ・private条件等の不備で不採用。v3での開発実行は数字を選定に使う前に無効化した。実装はv3固定後・v6固定前に書かれている。v6作成担当は改善実装を見ておらず、有効な測定の前にhash固定したが、「v6が実装前に固定された」とは言えない。経緯は[評価計画](release-evaluation-plan.md)に記録した。

生成負荷はexact 35 / near 25 / condition 15 / old 10 / contradiction 10 / unrelated 5の重みで混合し、opaque IDを付けて順序をシャッフルする。生成物の実際の完全重複率は1,000文書で46.0〜48.9%、10,000文書で65.08〜65.46%。近似文書が同じ有限の変更パターンになることもあるため、重み35%と重複率は一致しない。対応表・正解・問題IDは採点器だけが使い、検索要求はtext/actor/scope/mode/as_ofだけに限定する。

### 開発データでの寄与分離

生結果と設定 (`../runs/phase2-release-dev-v3/summary.json`; historical artifact not included in this preview)。48件は16個の採点可能な開発問題を3つのcorpusで試した数で、48個の独立問題ではない。B、1trialぶんのtoken合計。全行で権限・禁止引用検査は0件。

| 変更（前段との差） | 予算 | 出典付き引用が全て取得できた件数 | 参照token合計 |
|---|---:|---:|---:|
| 従来control、3候補 | 4,000 | 33/48 | 91,948 |
| 完全一致の複製をまとめるだけ | 4,000 | 34/48 | 93,357 |
| 上記 + diversity 0.5 | 4,000 | 33/48 | 94,684 |
| 完全一致集約 + diversity 1.0 | 4,000 | 32/48 | 94,958 |
| 完全一致集約 + 6候補 | 1,000 | 31/48 | 55,244 |
| 同上（予算だけ変更） | 2,000 | 37/48 | 112,456 |
| 同上（選択設定） | 4,000 | **41/48** | **173,646** |
| 完全一致集約 + 12候補 | 4,000 | 40/48 | 225,852 |
| 完全一致集約 + BM25、3候補 | 4,000 | 27/48 | 96,692 |

diversityとBM25は採用しなかった。改善の多くは候補数・予算の増加による。完全一致集約だけの効果やDBの効果として数えない。設定と6ソースファイルのhashをselection.json (`../runs/phase2-release-dev-v3/selection.json`; historical artifact not included in this preview)で2026-10-30T02:32:26Zに固定してから最終評価した。最終結果を見た後の調整はしていない。

### 最終比較

各seedは同じ20問、うち17問採点対象。合計8,640行、各3反復。token合計は20問×1trial。3seedの範囲は信頼区間ではない。すべて4,000token設定で、Aは比較用の全文なので予算制限しない。

| 文書数 | 構成／方式 | 必須引用全揃い | token合計 | median ms | p95 ms |
|---:|---|---:|---:|---:|---:|
| 86 | control / B | 16/17 | 31,953 | 1.70 | 4.15 |
| 86 | selected / A | 17/17 | 52,119 | 0.25 | 0.35 |
| 86 | selected / B | 17/17 | 62,137 | 4.87 | 5.74 |
| 86 | selected / C | 17/17 | 62,137 | 4.88 | 5.58 |
| 100 | control / B | 16/17 | 32,043 | 1.73 | 2.14 |
| 100 | selected / A | 17/17 | 54,046 | 0.27 | 0.33 |
| 100 | selected / B | 17/17 | 61,675 | 4.90 | 6.29 |
| 100 | selected / C | 17/17 | 61,675 | 4.94 | 6.35 |
| 1,000 | control / B | 14〜15/17 | 31,340〜31,695 | 5.14〜5.38 | 6.65〜8.53 |
| 1,000 | selected / A | 15〜16/17 | 54,726〜55,091 | 1.80〜1.99 | 2.37〜3.50 |
| 1,000 | selected / B | 15〜16/17 | 60,113〜60,238 | 6.49〜6.76 | 7.95〜11.44 |
| 1,000 | selected / C | 15〜16/17 | 60,113〜60,238 | 6.60〜6.95 | 8.01〜15.60 |
| 10,000 | control / B | 12〜13/17 | 31,674〜31,983 | 85.55〜89.38 | 119.83〜148.99 |
| 10,000 | selected / A | 14/17 | 55,408〜55,543 | 22.98〜23.19 | 28.21〜30.37 |
| 10,000 | selected / B | 14/17 | 60,187〜60,591 | 27.18〜28.33 | 34.66〜36.68 |
| 10,000 | selected / C | 14/17 | 60,187〜60,591 | 27.77〜30.27 | 35.63〜40.97 |

最終summary (`../runs/phase2-release-final-v1/summary.json`; historical artifact not included in this preview) / CSV (`../runs/phase2-release-final-v1/results.csv`; historical artifact not included in this preview) / payload (`../runs/phase2-release-final-v1/payloads.jsonl`; historical artifact not included in this preview) / 環境・hash・生成条件 (`../runs/phase2-release-final-v1/metadata.json`; historical artifact not included in this preview)。分類別CSV (`../runs/phase2-release-analysis-v1/categories.csv`; historical artifact not included in this preview)と選択設定の失敗一覧 (`../runs/phase2-release-analysis-v1/selected-failures.json`; historical artifact not included in this preview)も保存した。分類は固定fixtureのラベルであり、後述のmulti_sourceラベルの不備を含む。A/B/Cの候補一致、B/Cのbyte単位payload一致を2,880組で確認した。B/Cは同じ入力から同じメモリ索引を作るため、これはDBの検索品質の優位性ではない。検索時の保存先readは0回、追加探索は全件1roundである。

選択設定のAとBは同じ候補を使うが、Aはbody全体を返すので旧状態・未採用案も含み得る。Bは節の状態・期限で絞り、原文位置等を返す。したがってAの「引用あり」は、回答時の状態取り違えがないことを意味しない。同時に、Bの小ささも保証されない。86文書の選択設定ではA=52,119、B=62,137tokenで約19.2%増だった。参照tokenが減らないことを隠して改善とは呼ばない。

1,000/2,000tokenも実測済み。10,000文書の選択Bはそれぞれ8〜10/17、11〜12/17に低下した。既知データへの回帰は元30問中26/26、旧Phase2最終20問中19/19の引用を保持したが、4,000tokenでの合計参照量はcontrolより増えた。

### 更新と16並列

maintenance生結果 (`../runs/phase2-release-maintenance-v1/results.json`; historical artifact not included in this preview)。16本の同時スレッドが同じshared queryを読み、応答hashとB/C一致を確認した。これは16体の実モデルでも16個の独立プロセスでもない。読取中の並行更新はこの試験に含まない。更新は1件を保存→readback→全索引を再構築→新しいmarkerを検索する順に各条件1回。保存と索引の更新は自動的に一体化されない。

| 文書数 | 保存先 | import ms | index ms | 1件commit ms | 再index ms | 16読取batch ms | reader p95 ms |
|---:|---|---:|---:|---:|---:|---:|---:|
| 100 | file | 20.63 | 27.37 | 0.45 | 23.36 | 13.96 | 7.02 |
| 100 | sqlite | 4.00 | 21.54 | 0.59 | 22.14 | 12.07 | 8.08 |
| 1,000 | file | 189.69 | 227.97 | 0.55 | 229.36 | 33.68 | 20.79 |
| 1,000 | sqlite | 21.71 | 213.25 | 0.46 | 217.76 | 36.89 | 21.34 |
| 10,000 | file | 1897.87 | 2664.62 | 0.83 | 2472.24 | 280.10 | 174.48 |
| 10,000 | sqlite | 221.08 | 1603.61 | 0.50 | 1574.59 | 273.15 | 167.55 |

索引再オープンを各3回測定したがOS cold cacheではない。1万文書ではファイル2,557.5〜2,900.9ms、SQLite1,538.4〜1,605.3ms。SQLiteはこの実装で大量ファイルの読み込みより速かった。ただし測定は1台・一つのseed・小さい本文の合成資料で、DB一般の費用優位を示さない。データ量が増えれば全索引再構築の負担が支配的になる。

版比較更新・同request_id再送・応答喪失・衝突・バックアップ復元は別の既存5反復試験 (`../runs/phase2-faults-v3/results.json`; historical artifact not included in this preview)で実施済み。16同時更新では初回1件だけ確定、残り15件は競合として再試行し、最終16変更を保存。復元はtiny local DBで約2.195〜2.719ms、バックアップ後の確定書込み2件は失われた。復元後に無損失と誤認しない。取得アダプター、KnowledgeStore、taskflow stubは自動同期していない。

### 保存payloadの事後監査

補足監査v4 (`../runs/phase2-release-audit-v4/summary.json`; historical artifact not included in this preview)は、retrieverを再実行せず保存された2,880 payloadを再検算した。hash・token数・予算・出典URL/title/revision・原文spans・metadataの不一致は0。B/Cの1,920 payloadで状態／有効期間／scope違反は0、repeat0のB/Cは960/960組でbyte一致した。Aでは旧状態のliteralが48payloadに含まれ、B/Cでは0だった。Aは本文全体を返す仕様なので、この48件をモデルの誤答とは数えない。

全構成・全予算を合算すると条件の欠落は80件、文字列はあるが許容出典に由来しないものは2件。4,000tokenの比較表については、これらを加味した事後の厳しい採点でも件数は変わらなかった。条件を含む集計 (`../runs/phase2-release-audit-v4/groups.json`; historical artifact not included in this preview)と、監査時点のscript・入力hashを保存した。採点器自身の誤りを修正したv1〜v3の途中監査は公開候補から除外し、当初の評価結果は書き換えていない。監査はfixtureの窓口条件欠落を補完するものではない。

### 0.4.0rc1の配布検査

新しい配布候補は `dist/release-0.4.0rc1/`。wheelにはCLI・completion/release設定・snapshot連携・明示実行のモデル検証器を含む。sdistには有効なcompletion入力と保存結果、review ZIPには以前の測定も含む。API送信や外部公開をbuildで行うことはない。導入確認・展開後テスト・再生監査・SHA256は配布物外のreceiptに記録する。

`--profile completion`は明示選択で、既定のrelease設定は互換性のため維持した。package説明を実際のAPI機能に合わせて訂正したため、旧選定の全source hashと現在の `__init__.py` は異なる。検索アルゴリズムは変更していない。厳密な再生には各runの保存sourceを用い、監査スクリプトがそれを検証する。

## 失敗例

継続検証では、似た文書が候補を埋めて別の必須資料が候補から落ちる失敗と、候補にはあるが同じ資料の断片が予算を使い切る失敗を分離した。候補数を増やすだけでは返却量が増え、2,000tokenでは不足が残った。過去の日付と検索日時の不一致、節が本文の一部ではない入力、重複範囲を含む資料に対する負荷生成の不整合も発見し、失敗した実行を比較から除外した。これらを検索性能の悪化として数えない。

最終評価の未達4 source casesは同じhandoff問題だった。1,000文書の2 seedと10,000文書の2 seedで、必要な文の文字列は得られたが、採点上必要な正本ではなく別条件の資料を引用していた。全文Aも同じ失敗なので、候補取得段階の残課題である。失敗レコード (`../runs/phase2-completion-analysis-v1/comparison.json`; historical artifact not included in this preview)を保存した。文字列一致だけなら成功と誤判定するため、採用根拠には出典一致も必要とした。

1. **似た資料が候補を占有する。** 10,000文書seed9101の`v4f28`は「Kora引継ぎとRook競合の根拠」。6候補でも片方の根拠を取得できない。完全一致をまとめても、条件が少し違う資料の混雑は残る。
2. **引用が同じでも出典の意味が違う。** 同条件の`v4f21`は履歴引用の文字列を取得したが、許容された原典／完全複製からは取得していない。`v4f16`も同様。10,000文書のliteral一致は16/17だがsource-awareは14/17。文字列だけの採点なら2問分を誤って成功にする。
3. **圧縮しない検索結果。** 短い資料の断片化でメタデータが繰り返され、全文より多くのtokenを返す。候補を増やす設定は既知30問でも改善前より参照量を増やした。4,000tokenを1,000に下げると必要根拠まで失われる。
4. **評価問題にも不備が残る。** `v4f16`は問題文で到着と窓口条件を聞くが、事前正解は到着の1引用しか定義していない。カテゴリもmulti_sourceだがこの問題単体は複数資料取得を検証できない。ほかの明示的な複数出典問題は残るが、17/17を質問全体の正答率とは呼べない。固定fixtureは書き換えず、この欠陥を公開する。
5. **初期集計の限界。** frozen `release_eval.score()` は `obsolete_quotes` を直接集計せず、`missing_conditions` は出典を限定しない文字列検査だった。この指標だけで旧決定取り違え0件や条件根拠が正しいとは断定できない。保存payloadからの独立した補足監査で区別する。採点器の事後修正を、事前に決めた採点として扱わない。

失敗したfixture draftや無効runを採用結果に混ぜず、公開ZIPには採用したv6と有効runを入れる。元の作業フォルダでは不採用版も消さず保存した。最終問題は既に閲覧したため、今後の改善には回帰データとしてしか使えない。

## 再現方法

継続検証の開発結果は次のコマンドで新しい出力先へ再実行できる。最終問題は開発選定とコードhashを固定してから評価する。

```sh
TIKTOKEN_CACHE_DIR="$PWD/tokenizer-cache" .venv/bin/python -m context_lab.completion_eval \
  --mode dev --output runs/phase2-completion-dev-replay-new \
  --datasets 80:18100,1000:18101,1000:18102,1000:18103 \
  --variants state_six,state_twelve,balanced_six,balanced_twelve
.venv/bin/python scripts/run_completion_snapshots.py \
  --output-root runs/phase2-completion-snapshots-replay-new
```

`budget.py`と`model_eval.py`に、10ドル共通上限の永続予約、失敗時の予約保持、最大16並列、Responses APIの使用量・回答・所要時間保存を実装した。HTTPを差し替えたテストと実際の検索payloadを使う接続前テストは通ったが、実APIへの送信はまだ0件。接続テストの合格をモデル測定と混同しない。

最終の再生監査は以下で実行できる。配布物や設定を書き換えず、測定時に保存したソースとハッシュを照合する。

```sh
TIKTOKEN_CACHE_DIR="$PWD/tokenizer-cache" .venv/bin/python scripts/audit_completion_payloads.py \
  --run runs/phase2-completion-final-v1 \
  --output runs/phase2-completion-audit-replay-new
```

実モデル用入力320試行はローカルに準備済み（接続前の作業用入力は配布対象外、`scripts/prepare_completion_model_tasks.py`で生成できる）。最終20問×2文書集合×以前/選定の全文/断片×2反復で、並び順を固定してシャッフルした。正解・採点基準・問題IDはモデルに渡さず、task_keyは保存結果との対応付け専用。B/Cは同一payloadなので、同じモデル入力をCとして重複実行してDBの優位を主張することはしない。

実モデルの採点準備として `model_quality.py` と[採点手順](model-quality-protocol.md)を追加した。引用が実際の入力・原文・許容出典に含まれるかを検査し、回答の全条件・状態・引用の意味・情報不足時の保留は別の明示的な採点を要求する。未採点は成功にせず、自動検査で失敗しても意味採点の完了とは呼ばない。API未送信の入力不正・予算上限エラーもtask index/key付きで保存する。Python 3.13で149 tests、3.11で関連24 testsが通った（`runs/phase2-model-quality-validation-v1/`）。HTTPはmockで、実モデル測定ではない。

主比較の20問はactorが8種類なので、16体同時処理の根拠にはならない。別途、既知の最終問題からファイル順で最初のshared 16問を選び、16種類の架空actorへ変更した4条件・64入力を `runs/phase2-completion-concurrency-inputs-v1/` へ保存した。10,000文書上で変更前後のpayloadは64/64完全一致。新しい独立問題ではなく、実モデル並列実行は未測定。上記採点器・記録修正・並列入力準備は保存済み0.4.0rc1配布後の作業であり、既存distには含まない。

Python 3.11以上。Python 3.13.12で全テスト、3.11.12で新機能の標準ライブラリ部分を実行確認した。wheelはデモ／API、sdistは新規実験、review ZIPは保存結果との照合も行える。ZIPを展開したルートを作業場所にする。コマンドの出力先が既にある場合は新しい名前に変える。

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[tokens]'
export TIKTOKEN_CACHE_DIR="$PWD/tokenizer-cache"
.venv/bin/python -c 'import tiktoken; tiktoken.get_encoding("o200k_base")'
.venv/bin/python scripts/preflight.py
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python scripts/verify_phase2_artifacts.py

# 全7構成を開発データで比較し、選択を保存
.venv/bin/python -m context_lab.release_eval --mode dev \
  --output runs/phase2-release-dev-replay --repeats 2

# 配布した固定設定で最終問題を回帰実行
.venv/bin/python -m context_lab.release_eval --mode final \
  --selection runs/phase2-release-dev-v3/selection.json \
  --output runs/phase2-release-final-replay --repeats 3 \
  --datasets 86:9100,100:9101,1000:9101,1000:9102,1000:9103,10000:9101,10000:9102,10000:9103

.venv/bin/python scripts/run_release_maintenance.py \
  --selection runs/phase2-release-dev-v3/selection.json \
  --output runs/phase2-release-maintenance-replay
.venv/bin/python -m context_lab.faults --output runs/phase2-faults-replay --repeats 5
.venv/bin/python scripts/audit_release_payloads.py \
  --run runs/phase2-release-final-v1 --corpus fixtures/phase2-release-v6/corpus.json \
  --queries fixtures/phase2-release-v6/final.json --output runs/phase2-release-audit-replay
```

旧0.3.0rc1時点ではローカルの73テストと保存payload監査を実行して合格した。Python 3.11〜3.13のCIは設定のみであり、実行済みとは扱わない。配布物の導入確認は[release手順](releasing.md)と配布物外のreceiptに記録する。

source hashが変わると固定設定の再利用を拒否する。新しい実装はdevを再実行し、新しい未使用問題を固定して評価すること。source snapshotは各run内に保存してある。元の`fixtures/synthetic/`と`runs/synthetic-v1/`は元manifestとの一致を検査する。新しいrunは作成専用で、既存結果を上書きしない。

## 未検証事項

継続系列の最終問題は測定・再生監査済みで、実モデルの回答・費用・16並列は未測定。2026-11-02に既存キーの保存場所を確認したが、この評価環境の通常・権限昇格実行ともDNS段階で接続に失敗し、実モデル評価は通信待ちで停止中。別環境のセットアップ接続成功は、本比較実験の測定には数えない。接続前の実装・採点・入力準備を完了しても、実測やOSS完成の代わりにはしない。クレジット残高・請求額は未確認。秘密値は公開成果物へ保存しない。Python 3.13の全テストとCLI demo/queryは通り、3.11.12でも新機能の標準ライブラリ部分37 testsが通ったが、3.11のtokens依存、Python 3.12、Linuxの実行は未完了。

- 実モデルの回答品質、usage／実課金、prompt caching、出力token、人的訂正時間、16体の業務完了時間。参照tokenはこれらの代理指標に過ぎない。
- D1、ネットワーク障害、分散更新、HTTP認証、マルチテナント隔離、本番taskflow、クラウドのバックアップ／復旧。ローカルSQLiteをD1の実証と呼ばない。
- corpus／質問を外部の独立チームが用意した評価、実運用分布、より大きい本文と更新頻度、別OS、Python 3.11でtokens extraを含む全テスト、Python 3.12の実行。GitHub Actionsの設定は作成したがremote CIは未実行。
- 学習済みembedding／rerankerとの比較、増分索引、更新と検索snapshotの原子切替。現在は全件をメモリに読み、更新後に再構築する。
- サイドチャネルを含むprivate情報の非干渉、敵対的資料、プロセスやディスク故障時の安全性。検索のcaller identityを信頼できるホストが設定する必要がある。
- 入力ZIP全体の再配布権の最終確認と外部公開。MIT本文を準備したことは、権利確認完了やGitHub公開済みを意味しない。

## 次の判断

継続作業は完了扱いにしない。大規模開発比較と固定した最終問題の測定・再生監査は実行済み。次は実モデルで回答品質・総token・待ち時間・更新費を比較する。0.4.0rc1はその検証へ進むためのローカル配布候補として梱包する。GitHub公開と本番変更は引き続き行わない。

1. **今できる判断:** この評価キットと実験ライブラリをローカル公開候補として採用する。DB移行／D1採用／本番の16エージェントへの一括導入は採用しない。既存の業務保存先はこのタスクでは変更しない。
2. **次の検証対象:** 準備済みの以前/選定・全文/断片の4条件で実モデルの出力を比較し、全条件・引用元・状態・情報不足時の保留を採点する。現在の最終問題を見た後で検索を再調整する場合は、新しい未使用問題を先に固定する。
3. **採用ゲート:** 同一の事前定義品質を満たして初めて、参照token＋実モデル課金＋更新／再構築＋再試行＋訂正時間を16体の代表的タスクで比較する。DBは必要な整合性・運用費・復旧要件から選ぶ。予算と隔離された測定先が確定すれば実モデル／D1を次段階で測る。
4. **公開の最終操作:** 入力の再配布権とライセンス表記を確認し、release ownerが外部公開を指示した後に行う。この候補には公開操作は含まない。
