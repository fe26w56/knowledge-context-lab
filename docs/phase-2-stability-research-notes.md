# Phase 2: 再現性・品質安定化の調査メモ

2026-11-03。実装前の仮説整理。ここでいう「安定」は、同じ入力を再実行して同じ結果になる再現性と、正しい根拠を保持する品質を分ける。文献の結果をこのプロジェクトの実Notionや16体へ直接一般化しない。

## 既存結果との接続

今回のtoken-growth最終評価では、2,000 tokenのsection選択で100→10,000文書の入力中央値が737→1,994.5へ増え、18問中13問が完全根拠だった。別の最終評価では、12候補全文が100→10,000文書で38/40→36/40となった。したがって、固定top-k・固定予算は再現しやすくても、資料増加時の根拠保持を保証しない。

## 文献からの仮説

| 仮説 | 一次資料が支持する範囲 | このプロジェクトでの反証可能な試験 |
|---|---|---|
| R1: 取得順を固定し、重要根拠を先頭/末尾に配置すると、同じ根拠でも回答揺らぎが減る | Liu et al. は、長いcontextでは関連情報の位置にU字型の性能差が出ると報告している。[Lost in the Middle](https://arxiv.org/abs/2307.03172) | 同一retrieval payloadをランダム順・BM25順・重要度を先頭/末尾へ配置して、同じ質問を複数回実行。引用完全性と回答一致率を比較する。順序固定だけで正しさが増すとは仮定しない。 |
| R2: 原文sectionだけでなく、親見出し・版・条件・例外・参照先を一つの証拠単位として返すと、分割による取りこぼしが減る | Lewis et al. は外部retrieverとgeneratorを組み合わせるRAGを示したが、どの単位を返すかはアプリケーション依存。[RAG](https://arxiv.org/abs/2005.11401) | 同じ候補を「sectionのみ」「section+親見出し」「decision/condition/exception record+原文offset」で比較。必須引用だけでなく、条件・例外・版の保持を採点する。 |
| R3: 同一条件の複数出力の多数決は、難しい推論の正答率を上げ得るが、根拠検索の誤りを直すとは限らず、費用を増やす | Wang et al. のself-consistencyは複数推論経路をサンプリングし、多数決で性能向上を報告する。[Self-Consistency](https://arxiv.org/abs/2203.11171) | まず同じ根拠payloadを2〜3回生成し、単一回答・多数決・根拠不一致時の再取得を比較。正答、引用一致、token/費用、追加時間を同時に測る。多数決で同じ誤引用が一致するケースを別集計する。 |
| R4: temperature=0やseed固定だけでは、実行環境の揺らぎを完全には消せない | ChatGPT code generationの実証研究はtemperature 0で非決定性が減るが消えないと報告。[Empirical Study](https://discovery.ucl.ac.uk/id/eprint/10198256/) | 同一model/version・prompt・取得payloadで、temperature/seed/並列度を固定し、反復出力の完全一致率と意味一致率を記録。設定固定を「正しさ」や「完全再現」と呼ばない。 |
| R5: 長文を一括投入するより、根拠を明示的に分離して統合する方が、入力位置依存と不要tokenを制御しやすい | RAG論文はretrieverで非parametric memoryを選びgeneratorへ渡す構成を示す。[RAG](https://arxiv.org/abs/2005.11401)。ただしこの資料から本件の最適分割方式は導けない | full context、候補section、構造化record→原文closureの3方式で、同一根拠を位置だけ変えて比較。入力tokenだけでなく、全引用の原文一致・条件適用・見落としを測る。 |

## 優先順位

上表のR1–R5は調査候補。実行計画のH1は順序正規化、H2は親節展開、H3は同一入力反復の品質、H4は安定した誤答の観察に対応する。以下は調査時点の優先案であり、実施範囲は[事前計画](phase-2-stability-protocol.md)を正とする。

実行時のH1はまず**入力順・同点順位の正規化だけ**を試す。「重要箇所を先頭に置く」効果まで検証したことにはしない。重要箇所の選定にgoldを使わない。H2の親節展開は本プロジェクトの推論に基づく仮説であり、引用したRAG論文がこの方式の優越を直接証明しているわけではない。

OpenAIの[再現性の説明](https://developers.openai.com/api/docs/guides/advanced-usage)も、同じ設定やseedによる制御は完全決定性の保証ではないとしている。この説明はChat Completionsについてのもので、Responsesや全モデルで同じseed指定が使えるとは仮定しない。[Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs)はschema整合を扱うが、内容の誤りは残り得る。既存モデルのgpt-6-lunaを使い、reasoning設定を変更せず、同一requestの反復を先に観測する。temperature/seed変更の効果は今回の比較に混ぜない。

API実測の予算予約には[公式input token count endpoint](https://developers.openai.com/api/docs/guides/token-counting)でschemaとroleを含む同じ入力を事前計数する。ローカルreference tokensだけをprovider usageとみなさない。[料金表](https://developers.openai.com/api/docs/pricing)は2026-11-03に再確認し、既存の高めの予約単価を維持する。

最初はH1とH2を、モデル呼出しなしのpayload評価と少数の同一入力反復で実装する。取得順を固定し、各選択sectionに親見出し・status・updated_at・条件/例外の参照を付け、原文offsetへ戻れるようにする。これなら検索の誤りと生成の揺らぎを分離できる。

次に同一入力反復で基準を作る。temperature 0やseed固定の効果は今回は未測定とする。R3のself-consistencyは後続の候補に残す。複数生成は費用を増やし、同じ誤った根拠を合意する可能性があるため、根拠closureが不足した場合だけ再取得する条件付き方式がよい。

## 実装前の受入条件

- 検索順を固定した場合の同一payload再現率を100%で確認する。
- 100→1,000→10,000文書で、完全根拠率、条件/例外/版の保持、入力token中央値/p95、取得時間を分けて記録する。
- 構造化recordの内容が古い場合、必ず原文と版へ戻して失効を検出できる。
- self-consistencyを使う場合、単一実行との品質差、追加token・費用・時間を同じ質問で報告する。
- いずれも実Notion、16体の本番agent、業務削減時間の証明とは分けて記載する。

