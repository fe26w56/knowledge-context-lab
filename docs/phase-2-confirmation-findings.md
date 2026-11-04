# Phase 2 findings

2026-11-02更新。架空資料だけを使用。外部公開・本番移行なし。旧報告は[初回](phase-2-initial-findings.md)、[実モデル前](phase-2-pre-model-findings.md)、[確認評価前](phase-2-before-confirmation-findings.md)として保存した。

## 結論

**総合判断は「追加検証が必要」。DB導入と、断片化による一律の圧縮方式は採用しない。運用上はファイル保管を維持する。** 同じ品質を常に低費用・短時間で得られる方式は、今回の比較では確認できなかった。

今回の短い資料では、12候補から断片を返すBは52/80成功、同じ候補全文を返すAは74/80成功だった。Aの名目API費用は約0.03262 USD、Bは約0.04174 USDで、全文のほうが約21.9%低かった。断片ごとの出典・状態・位置情報が入力を増やし、必要な本文を予算から押し出していた。**「短く切れば安くなる」は成立しない。** ただしA失敗/B成功も3ペアあり、同品質の保証や母集団の非劣性を主張しない。

6候補全文はさらに安く、小規模では同じ38/40成功だったが、10,000文書では26/40に下がった。候補選定の改善と候補数増加には価値がある一方、費用との交換条件が残る。この最終結果に合わせた閾値・検索調整は行わない。必要品質が未定のまま、規模だけで自動的に方式を切り替える規則も採用しない。

OSSとして提供するのは、方式を分離して比較できるPythonライブラリ、CLI、固定診断データ、実API応答・使用量、採点訂正、障害試験、再生監査を備えたローカル評価キット（0.5.0rc1）である。`--profile control --full` と `--profile completion --full` で測定した全文方式を実行できる。`--full` は参照予算を設けず、候補本文中の履歴や案も含む。予算付き方式は `--full` を指定せずに比較する。既定release設定は互換性のため維持し、品質最適の推奨とはしない。

## 比較表

A=同一候補の全文、B=ファイル索引からの予算付き断片、C=Bと同じ処理をSQLite保存で実行。B/Cで出力が一致するため、同じ文脈のAPI呼出しをC向けに重複させていない。フィルター・JSON・候補数の効果をDBの効果には数えない。

[confirmation-v5](../fixtures/phase2-confirmation-v5/README.md)は76文書・284節、dev20/final20問。構造監査 (`../runs/phase2-confirmation-structural-audit-v5/audit.json`; historical artifact not included in this preview)と意味監査 (`../runs/phase2-confirmation-fixture-audit-v5/semantic-review.json`; historical artifact not included in this preview)後に測定した。作者は以前の実装・結果を見ている。固定は追加改善前・有効測定前だが、独立した外部ベンチマークではない。意味の不整合があった旧completion-v7の320応答は保存し、最終の採用根拠から除外した。

最終実APIはgpt-6-luna、最大出力4096token、8並列、20問×2規模×4条件×2反復=320試行。各行40は20問の2反復であり、40個の独立問題ではない。引用真正性・供給範囲・必須出典・状態・条件・情報不足・私的情報を検査し、意味判定はエージェント支援レビューとroot監査で行った。独立した人手採点ではない。

| 文書数 | 構成 | 成功 / 試行 | 入力token | 名目API費用 USD | 応答中央値 / p95 秒 |
|---:|---|---:|---:|---:|---:|
| 100 | 6候補 control / A | 38/40 | 79,132 | 0.012813 | 4.82 / 6.04 |
| 10,000 | 6候補 control / A | 26/40 | 83,818 | 0.014068 | 5.13 / 7.01 |
| 100 | 6候補 control / B | 38/40 | 178,920 | 0.019315 | 4.83 / 6.87 |
| 10,000 | 6候補 control / B | 28/40 | 178,408 | 0.020554 | 5.54 / 7.95 |
| 100 | 12候補 selected / A | 38/40 | 134,874 | 0.015137 | 4.16 / 5.83 |
| 10,000 | 12候補 selected / A | 36/40 | 152,296 | 0.017478 | 4.78 / 6.89 |
| 100 | 12候補 selected / B | 26/40 | 188,672 | 0.019767 | 4.85 / 7.73 |
| 10,000 | 12候補 selected / B | 26/40 | 188,296 | 0.021975 | 5.69 / 11.25 |

比較JSON/CSV (`../runs/phase2-confirmation-analysis-v1/comparison.json`; historical artifact not included in this preview)・全採点 (`../runs/phase2-confirmation-model-final-quality-v1/result.json`; historical artifact not included in this preview)・実API生結果 (`../runs/phase2-confirmation-model-final-v1/run.json`; historical artifact not included in this preview)。費用はprovider usageと名目単価からの推定で、実請求やcredit消費額ではない。キャッシュ量・出力長が異なるため、入力圧縮だけの費用効果とも言えない。時間はランダム順の混合実行で測ったクライアント応答時間。初期の一部はローカル再生監査と重なっており、arm別の独立した総時間や16エージェント業務時間ではない。

最終の根拠保持（モデル回答とは別、情報不足2問を除く18問）:

| 文書数 | 6候補 A/B | 12候補 A | 12候補 B | 12候補 A→B 返却token合計 | 取得p95 A→B |
|---:|---:|---:|---:|---:|---:|
| 100 | 18/18 | 18/18 | 12/18 | 59,537→79,027 | 8.4→38.0ms |
| 1,000 | 16/18 | 16/18 | 8/18 | 64,709→79,288 | 37.9→71.5ms |
| 10,000 | 13/18 | 18/18 | 10/18 | 68,209→79,017 | 93.5→125.8ms |

生結果 (`../runs/phase2-confirmation-final-v1/summary.json`; historical artifact not included in this preview)。予算はB/Cが1,000/2,000/4,000、表は4,000。Aは上限なし。最終720ペアでB/Cの候補・payloadが一致。保存した1,080 payloadの再生監査 (`../runs/phase2-confirmation-final-audit-v1/audit.json`; historical artifact not included in this preview)は不一致0。warm in-process索引の時間で、各queryでtoken数キャッシュを消去。OSキャッシュは未消去。索引構築・取り込みは別のbuilds.jsonに保存している。

追加の一変更として、安全な文書全文のほうが小さい場合だけ切り替える `AdaptiveRetrieval` を実装した。開発データでは4,000予算の100文書が12→18/18になったが、1,000/10,000文書は9/18のままで、取得p95も約66→104ms、122→220msへ増えた。**不採用の実験機能**として既定OFF。開発測定 (`../runs/phase2-adaptive-dev-v1/summary.json`; historical artifact not included in this preview)と1,620 payload監査 (`../runs/phase2-adaptive-dev-audit-v1/audit.json`; historical artifact not included in this preview)を保存。最終問題には適合させていない。構成固定と不採用理由 (`../runs/phase2-confirmation-selection-v1/selection.json`; historical artifact not included in this preview)参照。

16 actorのAPI試験 (`../runs/phase2-model-concurrency-analysis-20261102-v1/summary.json`; historical artifact not included in this preview)では旧固定入力を使った8 batch・128呼出しで、16種類のactorの処理区間が実際に重なった。これは派生した並列回帰試験であり、最終20問での16体業務品質や独立した16体の自律運用ではない。ローカルSQLite障害試験 (`../runs/phase2-completion-snapshots-v3/20261030T100105.900183Z-c969ccbb/results.json`; historical artifact not included in this preview)は版競合、同一request_idの再送、異内容拒否、応答消失、snapshot/検索接続、private境界、復元を検証済み。D1へ一般化しない。

全体では849回のAPI呼出しが正常完了し、自動再試行0。名目推定0.40558 USD、保守的計上2.51760 USD（過去setup2回のusage不明に対する0.02 USD保留を含む）。会計照合 (`../runs/phase2-live-accounting-20261102-v2/summary.json`; historical artifact not included in this preview)で全attemptと共通10 USD ledgerを一致確認した。

## 失敗例

- **引き継ぎ資料と受領記録の混同:** Flintはoutstanding-work checklistが必要なのに、断片だけの回答がsigned acceptance entryを必要資料として挙げた。同じ文書からの真正な引用だけでは正解にならない。
- **別資料の義務の持込み:** Acacia appendixの非公開・正確なhousehold countsという要件を落とし、Yarrowの除外理由の義務を回答した。引用元の実在と、質問への適用可能性は別。
- **複数根拠の一部欠落:** Zephyrのsnapshot digestや担当者があっても、snapshot後のaccepted writesのreplay要件が欠ければ失敗。類似語を含む出典を取得しただけでは不十分。
- **metadataを原文引用にした回答:** `verified_at: ...` という本文にない文字列を引用した例は真正性検査で失敗。事実としてmetadataにあることと、本文の逐語引用であることを分ける。
- **監査者の誤判定:** 最初の意味レビューにも欠落をpassとした例があった。開発6件、最終5件の判定訂正を元レビューと併存させた。統合監査 (`../runs/phase2-confirmation-model-final-semantic-v1/integration-audit.json`; historical artifact not included in this preview)はrootが実際に見た範囲を明示する。
- **復元時の損失:** backup作成後の承認済み2版はrestoreで失われた。DBがあるだけで無損失にはならない。

全失敗回答と判定 (`../runs/phase2-confirmation-analysis-v1/failures.json`; historical artifact not included in this preview)を保存している。最終失敗を使った検索実装の再調整はしていない。

## 再現方法

Python 3.11以上。以下は展開したソースのルートで実行する。毎回新しい出力名を使う。

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[tokens]'
export TIKTOKEN_CACHE_DIR="$PWD/tokenizer-cache"
.venv/bin/python -c 'import tiktoken; tiktoken.get_encoding("o200k_base")'
.venv/bin/python -m unittest discover -s tests
.venv/bin/python scripts/audit_completion_payloads.py   --fixture fixtures/phase2-confirmation-v5   --run runs/phase2-confirmation-final-v1   --output runs/phase2-my-confirmation-replay
.venv/bin/python -m context_lab.model_quality summarize   --prepared runs/phase2-confirmation-model-final-review-v1/result.json   --reviews runs/phase2-confirmation-model-final-semantic-v1/reviews-integrated.json   --output runs/phase2-my-model-summary
```

再生監査と保存済み回答の再集計にはAPIキーも追加課金も不要。実APIの再呼出しは明示的な別操作で、同じ回答・費用・時間の再現を保証しない。[モデル評価手順](model-quality-protocol.md)を参照。検索器と回答モデルにはrequestのtext/actor/scope/mode/as_ofと検索文脈だけを渡し、qid・gold・rubricは採点用に分離した。

```bash
.venv/bin/context-lab-query demo --output work/demo-new
.venv/bin/context-lab-query query --backend file --index work/demo-new/index   --request work/demo-new/request.json --profile control --full --unit chars
.venv/bin/context-lab-query query --backend file --index work/demo-new/index   --request work/demo-new/request.json --profile completion --budget 4000
```

新CLIの全文選択は既存の測定済み`retrieve(full=True)`への入口であり、検索アルゴリズムを最終結果で変更したものではない。古い測定はそれぞれのsource snapshotで再生する。配布の検証結果は[release provenance](release-provenance.md)にまとめる。

## 未検証事項

D1・分散障害・本番taskflow・本番での16体自律業務、実請求書・credit残高/充当先、実資料での正答率、人の訂正時間、独立した外部問題、Linux/Windows/リモートCIは未測定。Python 3.11/3.13のローカル検証と区別する。私的資料を扱う本番サービスのtenant分離も、このプロセス内のactorフィルターで証明したものではない。

40問は自己作成した診断で、20 final問の反復から一般的な最適性は推定しない。取得時間とLLM応答時間は異なる実験であり、単純加算して16体全体の改善倍率とはしない。エージェント支援採点には訂正を要した例があり、人手独立採点と同等とは扱わない。

## 次の判断

現在はDB移行せず、既存ファイル運用を維持する。導入候補を選ぶ際は、短い文書なら候補全文を必ず比較対象に含める。厳しい入力予算が必要なら欠落率を実測し、満たさない場合に圧縮を採用しない。必要な品質水準を満たすことを先に確かめ、同品質内で使用量・応答時間・更新負担を比較する。

次に採用判断を更新する条件は、利用者が許可した別の代表資料・独立作成の問題で同品質を確認し、16体の実際の作業時間と訂正負担まで測ること。今回は禁止されている実資料の取込み・本番移行・外部公開を行っていない。ローカル配布候補は、この否定的結果と再現手段を共有するための成果物であり、最適方式が証明されたという宣言ではない。
