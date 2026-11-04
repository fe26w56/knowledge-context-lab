# Phase 2: 安定性を保つ取得・回答の事前計画

2026-11-03。文献調査を先に実施し、以下を新規改善実装と最終開封の前に定める。
[調査メモ](phase-2-stability-research-notes.md)。自作診断であり独立benchmarkではない。

## 仮説と境界

- H1（順序）: 内容が同じ資料集合なら、入力順や同点順位でcontextが変わらないように正規順序を固定する。再現性と正しさは別指標。
- H2（原文のまとまり）: 見出し階層に基づき、選んだ段落の親節・兄弟節を原文のまま返すと、隣接する条件/例外の欠落が減る。大きいbudgetだけの効果と比較する。
- H3（生成）: 同じinputを反復したとき、H2のまとまった根拠が回答の全条件正答率・最悪反復品質を改善するか。出力文字列一致だけを成功にしない。
- H4（多数決）: H3の保存済み反復を使い、同じ誤答が繰り返される例と、正答が安定する例を分ける。新しい有料多数決処理は導入しない。

キーワード+意味検索、構造化決定の再利用、temperature/seed操作は別の仮説。
今回のモデルの対応や測定がない項目を検証済みとは書かない。
OpenAIは設定固定でも完全決定性を保証していない。
https://developers.openai.com/api/docs/guides/advanced-usage
Structured Outputsは形式を揃えるが内容の正しさは保証しない。
https://developers.openai.com/api/docs/guides/structured-outputs

## 固定入力

新規fixtureに開発8意図・最終12意図、各3言い換えを作る。project/factsを分離し、
source/generator/dev/finalをhash固定する。未知、履歴、全件、非公開、未承認、
条件・例外、別資料参照を含める。独立の意味監査で質問とgoldの整合を確認する。
各意図の3言い換えは同じ必要事実を要求する。問題ID/goldは検索やモデルへ渡さない。

実際の固定対象は `fixtures/phase2-stability-v3/`。v1は質問とgoldの不整合、v2は
増加分が別projectのみという弱点を最終測定前に棄却し、保存した。v3の質問は監査修正後v2と
同じbytesで、generatorだけ同一projectの別業務・条件・複製・旧版を含む増加に修正した。
開発8問にはunknown/cross-documentがない。最終12問には両者がある。選定用のカテゴリ網羅性に
限界がある。同一teamの別agentによる意味監査であり、独立benchmarkではない。
最終の3問に対するgold不足の指摘は固定前にrootへ共有されたため、完全blindとも呼ばない。

## 取得評価

同じ情報を持つ100/1,000/10,000文書、入力順seed 3種類、各3言い換え。
同じ内容の順序だけを変える比較と、資料増加の比較を分離する。
旧diverse_sections 2,000、正規順序2,000、正規順序8,000、親節展開8,000、
project全文を比較。8,000はcontext token上限、instruction等を含む総入力も別計数。
親節が大きすぎる場合は切断せず、省略/overflowを明記。全件要求は全文経路。

指標: 同一質問・同一集合のpayload完全一致、各意図の全言い換え/順序/規模での
全必要根拠保持率、missing条件/例外、private/stale exposure、input median/p95。
各条件での平均だけでなく、全条件で成功した意図の数を報告する。
開発で全根拠保持を優先し、同率ならtokenの少ない方式を固定してからfinalを開く。
最終の失敗を見て調整しない。成長による失敗を順序のランダム性と混同しない。

## 実モデル反復

既存のAPI接続・共通10 USD ledgerを使い、既存不明予約2件を維持する。
開始時保守計上9.409789750 USD、残り0.590210250 USD。
既存モデルgpt-6-luna、reasoning effortはoverrideせず、tool呼出しなし、store=false。
APIのモデル名・返却model/fingerprint（提供時）・request hash・usageを保存する。
固定できる日付snapshotが公式にない場合はalias使用と明記する。

同一最終12意図の第一表現、100文書、入力順seed0で旧方式と開発選択方式を比較。
各3反復を基本とし、全12意図・両方式を1巡する対応ブロック単位で、上限5反復まで。
実行前に公式input token count endpointで同じpayloadのschema/role込みtokensを確認。
保守料金input0.55/output0.825 USD per million、input count+max(1024,10%)余裕と
output上限2,048で各呼出しをdispatch前予約。既存上限変更・不明予約解除はしない。
本試験の追加保守計上は最大0.45 USD。途中失敗は保存し自動再送しない。
count失敗時は生成しない。実usageが事前boundを超えた場合も停止する。
最低の対応ブロックを完了できない場合は実施数と欠測を明記する。
入力count endpointは生成ではなく別件数として記録。請求書/残高の確認ではない。

回答は同一schemaでanswerと引用を出し、全文sourceに照合する。期待文字列の機械採点は
意味正答と同一視せず、全出力を別agentとrootが原文で監査する。
反復の正答率、全反復正答の意図数、意味の不一致、引用不正、input/output/reasoning tokens、
推定費用を報告。言い換えやseedや反復を独立した意図の数として数えない。
同じ誤答の一致は安定した誤りとして失敗に数える。少数反復から将来の失敗確率ゼロとは言わない。

## 保存・採用

出力は新規runs/phase2-stability-*へ保存。既存実装・保護fixture/run・公開境界は維持。
qualityを落としてtokenや分散だけ減った方式は採用しない。
全体の議論はdocs/phase-2-findings.mdの6節順に追補する。
