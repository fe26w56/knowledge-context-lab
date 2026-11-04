# knowledge-context-lab：Phase 2と16 actor追加検証の結果

2026-11-03。ローカルOSS候補0.6.0rc1。公開・本番移行は未実施。[前回報告の保存版](phase-2-confirmation-findings.md)は内容を保って残した。

## 結論

**総合判断は「追加検証が必要」。ファイル保管を維持し、DB導入・生成した共有記録・キャッシュ方式の一律採用を見送る。** 同品質で総費用50%減・時間30%減という探索目標は達成しなかった。

16人分の異なるactor要求が、調査・条件判断・引き継ぎ・原資料の改訂/撤回を経る架空案件を実装した。開発8案件で変更を一つずつ比較し、構成を固定して最終8案件を実行した。最終384回答では6候補全文124/128、12候補全文124/128、12候補＋明示キャッシュ125/128が厳格採点を通った。これはAPI成功率ではなく、値・引用・必要出典・実際の先行出力を含む採点である。

キャッシュ方式は12候補全文に比べ推定費用9.41%減・時間3.81%減だった。しかし同じtaskの対応比較では3件改善・2件悪化し、提案中の上限を現在許可された上限として返す新たなfield誤りもあった。**合計点の1件差は同品質の証明にならない。** 6候補より費用は27.48%高い。標準設定は変更せず、実験用の選択肢として残す。

最終の失敗11件はすべて必要な出典が実際に供給されていた。残存誤りをDBや検索漏れの問題とは扱えない。共有記録も、作成・再作成・追加回答の負担を含めると開発で不利だった。失効・権限・実handoff・費用予約・実入力監査を再利用できる検証キットとして実装したことが今回の成果である。

予定した2反復のうち、2巡目は19成功＋使用量不明の通信失敗1件で事前の停止条件に従い中断した。正式な対応比較は完了した1巡目だけ。失敗を成功試行へ置き換えておらず、反復安定性の確認は未完了である。

## 比較表

### 最終8案件・各16 actor・同時API worker 3

費用は各方式128回答の合計。provider usageと保存単価による推定で、請求書・credit消費の実測ではない。時間は案件開始から4つの依存waveの完了まで。16 actorは16同時API呼び出しを意味しない。

| 方式 | 厳格成功task | 全task成功案件 | 推定費用USD | 8案件時間合計 | 案件median / p95秒 | cached input |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 6候補全文＋handoff明確化 | 124/128 | 5/8 | 0.064692 | 243.53秒 | 29.92 / 34.69 | 0 |
| 12候補全文＋同じ明確化 | 124/128 | 4/8 | 0.091036 | 237.87秒 | 29.60 / 33.64 | 0 |
| 12候補＋明示cache境界 | 125/128 | 5/8 | 0.082470 | 228.80秒 | 28.87 / 29.65 | 69,108 |

案件単位の4,000回の探索的bootstrapで、12候補に対するcache方式の費用削減区間は3.33–15.56%、時間削減区間は0.39–7.88%。制御された8案件の再標本化であり、実務母集団の信頼区間・非劣性証明ではない。p95はnearest-rankで、この件数では最大値。provider状態やblock分割による読み方の変化もあり、全差をcacheだけの因果効果とは断定しない。集計・対応task差 (`../runs/phase2-workflow-final-analysis-v2/summary.json`; historical artifact not included in this preview)

| 条件（各2案件・32task） | 6候補 成功 / USD | 12候補 成功 / USD | cache 成功 / USD |
| --- | ---: | ---: | ---: |
| 短文・低再利用 | 32 / 0.012171 | 31 / 0.016307 | 31 / 0.016039 |
| 短文・高再利用 | 30 / 0.012267 | 31 / 0.016103 | 31 / 0.013493 |
| 長文・低再利用 | 31 / 0.020221 | 30 / 0.029558 | 31 / 0.029294 |
| 長文・高再利用 | 31 / 0.020032 | 32 / 0.029067 | 32 / 0.023643 |

低再利用のcache hitは0。長文・高再利用では12候補比で費用18.66%減、時間1.19%増。再利用による入力費削減と、仕事全体の高速化を分けて判断する。

### 開発で切り分けた寄与

異なる開発run間には応答・provider状態の揺れがある。正式な最終比較と混ぜない。

| 変更 | 観測結果 | 判断 |
| --- | --- | --- |
| ローカル取得のまとめ・再利用 | 384組でcontext完全一致。高再利用で約18–35ms短縮、低再利用hit 0 | モデル回答は減らず、全体の数十秒を大幅には短縮しない |
| 生成した根拠抜粋の共有記録 | 106/128、204 API、0.085710 USD、333.81秒。6候補基準は115/128、128 API、0.063010 USD、196.61秒 | 構築費を回収できず不採用 |
| 共有記録＋原文回答1回 | 111/128、242 API、0.101742 USD、478.57秒 | 38追加回答込みで費用・時間が悪化 |
| direct predecessorのstatusをコピーと明示 | 12候補の開発厳格成功110→124/128。古いincoming_statusとの混同に対応 | 読み方の改善。DBの効果ではない |
| JSONでsourcesを先頭へ | prefix12の128回答でcached input 0 | 順序だけでは再利用を確認できず |
| sources後の明示cache境界 | 開発124/128、cached input 172,878 | 最終候補へ。ただし最終では個別品質悪化が残った |
| 回答schemaも共通化 | 119/128へ低下、cacheは235,195へ増加 | 安価・高速でも品質低下により不採用 |

共有記録は同じ12候補から作り、引用を原文照合する。可視snapshot全体・時点・設定で失効し、追加・削除・改訂・権限変更も反映する。構築費を前処理として除外していない。開発費用再計算 (`../runs/phase2-workflow-dev-pricing-v2/summary.json`; historical artifact not included in this preview)・開発分析 (`../runs/phase2-workflow-dev-analysis-v2/summary.json`; historical artifact not included in this preview)・取得再利用 (`../runs/phase2-workflow-reuse-v2/results.json`; historical artifact not included in this preview)

前回Phase 2では、別の確認評価で12候補全文74/80、同候補断片52/80、6候補64/80だった。今回と分母・条件が異なり合算しない。file/SQLite同一pipeline比較・ローカル更新障害試験は[保存版](phase-2-confirmation-findings.md)に残す。provider cacheの効果をDBの効果に数えない。

## 失敗例

1. **正しい引用でも状態を誤る。** final-02-t05のcache12は、提案文の69 cratesを「現在許可されたlimit」へ出力した。statusはproposedと正しいが、契約上limitはnullである。
2. **提案の発効日まで不明にする。** final-03の6候補方式は本文の2026-06-01をnull化した。許可済みの上限がないことと、提案本文の日付がないことを混同した。
3. **受け取った根拠を落とす。** final-06-t11の12候補方式は、撤回後も有効なhandoff規則があるのにitem/owner/retentionを全てnull化。private codeの読み落としもcache12と6候補に各1件。必要出典は全11失敗で供給済み。
4. **引用を整形する。** final-05-t02の6候補方式は結論falseが正しいが、引用の先頭大文字化などで逐語一致を壊した。値正答と引用の真正性を分けて数えた。
5. **通信障害。** 2巡目でURLError、response ID/usageなし。原因の細分類は未測定。最大予約0.5808792 USDを保留し、自動再試行0回で停止。完成した1 case-armと途中4試行を保存し、完全な2巡目とは扱わない。障害監査 (`../runs/phase2-workflow-interruption-audit-v1/audit.json`; historical artifact not included in this preview)
6. **評価者も誤る。** 初回AIレビューの機械判定転記・task種別を誤った汎用理由を拒否し、case別の具体的再レビューへ差し替えた。AIレビュー384件に加え、主担当が全11失敗＋8案件×4種別の32成功を対抗確認。独立した人手評価ではない。採用レビュー・確認範囲 (`../runs/phase2-workflow-final-semantic-v1/integration-audit.json`; historical artifact not included in this preview)

## 再現方法

Python3.11.12と3.13.12で各226 tests、失敗・error・skip 0。元fixture/results・tokenizerのpreflightも通過した。検査記録 (`../runs/phase2-workflow-validation-v4/py313.json`; historical artifact not included in this preview)

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[tokens]'
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python scripts/audit_workflow_run.py \
  --fixture fixtures/phase2-workflow-v6 \
  --run runs/phase2-workflow-final-r1-v1 \
  --output runs/phase2-my-workflow-replay
.venv/bin/python scripts/analyze_workflow.py \
  --run runs/phase2-workflow-final-r1-v1 \
  --output runs/phase2-my-workflow-analysis
```

この再生はAPIを呼ばない。384件の実入力・応答・出典・権限・時点・引用・usageと保存時ソースによる採点を照合した。再生監査 (`../runs/phase2-workflow-final-integrity-r1-v1/summary.json`; historical artifact not included in this preview)。API入力は公開taskと取得資料・実handoffのみ。gold・問題ID・期待引用は検索器・モデルへ渡さない。

実APIの手順・共通10 USD ledger・停止条件は[workflow利用手順](workflow-usage.md)。同じ許可枠のledgerを作り直して上限をリセットしない。実行済み最終問題は今後回帰用である。

selection (`../runs/phase2-workflow-selection-v1/selection.json`; historical artifact not included in this preview)と各runのsource snapshotに実装/fixture hash・seed・worker数を保存。v5設計は新workflow実装前に固定、v6はsmokeで判明した必要十分条件の文言を実装後・有効比較前に修復した版。v6が実装前だったとは主張しない。[fixture](../fixtures/phase2-workflow-v6/README.md)

価格は保存したsnapshot (`../runs/phase2-workflow-pricing-v3/pricing.json`; historical artifact not included in this preview)と当時の[公式料金](https://developers.openai.com/api/docs/pricing)・[cache仕様](https://developers.openai.com/api/docs/guides/prompt-caching)による。旧runの区間を上書きせず、保存requestのdefault 30mとwrite tokenから別版で再計算した。請求額ではない。

全フェーズ共通ledgerの保守的計上は**7.3990805 USD / 許可10 USD**。Phase 3の成功1,921回・通信失敗1回と、以前の成功849回・setup保留を照合した。Phase 3のusage既知分の名目推定は1.032070515 USD。新しい不明試行の最大予約と過去setupの0.02 USDを残す。会計監査は不一致0だが使用量不明1件があるため`incomplete`。完済・実請求確認済みではない。会計 (`../runs/phase2-workflow-accounting-final-v1/summary.json`; historical artifact not included in this preview)

## 未検証事項

- 2巡目全体、冷/温cacheの厳密な反復比較、通信失敗の原因と実課金。provider cacheは完全には制御していない。
- 実資料、独立した外部問題・人手評価、長期の16体実業務、人の訂正時間、別モデルの比較。自作8案件は同系統テンプレートを共有し、長文も最大約470語の制御された文書である。
- 請求書、credit残高・充当先、D1、ネットワーク越しのDB、production認証・tenant分離。actorは信頼済み呼出側が設定する。
- 変更部分だけの失効、構築費を回収できるほど長い調査・多数回の再利用、vector検索・reranker。未測定の方式を悪いと断定しない。
- GitHub公開、remote CI、本番移行。MIT候補の配布権最終確認は公開責任者の判断事項。

## 次の判断

**ファイル保管＋原文・版・条件を保持する取得を継続する。** 共有記録・DB・一律cacheを標準へ入れない。実験実装はopt-inで公開候補へ含め、失敗も再生できる形にする。

大きな改善を次に狙うなら、今回の11失敗に対応した「状態を構造化して制約検査する」「読み落とし・引用不備を検出したときだけ追加確認する」「別モデルの費用と訂正減を比べる」を、新しい未使用問題と総費用で比較する。これは次の候補で、今回達成した改善ではない。

共有記録・DBへの投資は、代表案件の重複調査量・文書長・更新頻度を測り、構築費込みの回収条件が見えた後に判断する。今回の予算で結論を良く見せるための最終問題への調整や追加試行は行っていない。
