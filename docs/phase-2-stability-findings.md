# 確率的な揺れを減らす仮説と検証

2026-11-03。研究・実装・固定後の取得評価・実モデル反復を分離した記録。

## 結論

**順序の固定は取得の再現性に有効だった。条件・例外を含む親節の追加は開発では改善したが、最終問題での品質改善は確認できなかった。** 大量の根拠を一律に追加する方式は採用しない。今回の結論も総合的には「追加検証が必要」であり、DB導入の根拠ではない。

文献調査では、関連情報の位置による性能差、複数回答の多数決、設定固定の限界を調べた。[Lost in the Middle](https://arxiv.org/abs/2307.03172)は位置依存を、[Self-Consistency](https://arxiv.org/abs/2203.11171)は推論問題での多数決を扱う。どちらも本件のNotion取得や親節展開を直接保証しない。設定固定や[Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs)も事実の正しさの保証ではない。親節で条件を保持する案は、このプロジェクトで検証する仮説として立てた。[調査メモ](phase-2-stability-research-notes.md)／[事前計画](phase-2-stability-protocol.md)

同じ入力でも文章表現は変わったが、100資料の実モデル比較では、通常の10問の必要事実は両方式とも各5回正しかった。不明1問と権限外1問への回答も断定を避けた。一方、原文を厳密に引用する契約は従来方式の1回答で失敗した。**表現の一致、意味の正確性、引用の完全一致を別々に採点する必要がある。** 少数の反復から将来の誤答率ゼロとは言えない。

1万資料でも通常・履歴10問を各3回、追加60回答で確認した。必須事実と安全な不明回答は両方式30/30だったが、親節方式の1回答に原文が指定しない実施時期の付け足しがあった。回答全体の支持まで求めると従来30/30、親節29/30。親節の実inputは従来の3.27倍で、安定性の改善は示せなかった。全件要求はこの追加生成から除外している。

## 比較表

### 仮説ごとの寄与

| 仮説・変更 | 実測結果 | 判断 |
| --- | --- | --- |
| H1: 同じ資料をid順に揃える | 最終108組の順序不変が90→108。根拠保持は差なし | 全件経路の順序再現性に有効。通常検索は元から順序固定済み |
| H2: 選択箇所と同じ親見出し内の条件・例外を原文で渡す | 開発の全条件保持7/8→8/8。同じ8,000枠の段落選択だけでは7/8。最終は全方式raw 10/11 | 開発効果は最終へ一般化せず。一律採用しない |
| H3: 同一payloadでモデルを5回反復する | 意味正答・安全な不明回答は両方式60/60。引用契約込み59/60対60/60 | 品質分散低下の十分な証拠はない |
| H4: 多数決で品質を安定させる | 反復は測定したが、回答選択器は未実装・未評価 | 正解を知る採点者の選択を多数決の性能と呼ばない |
| 意味検索・確認済み決定の再利用・temperature/seed変更 | 今回の比較では未測定 | 後続の候補 |

最終は12意図、各3言い換え、3入力順、100/1,000/10,000資料、5方式＝1,620行。答えのある11問のうち1問は権限外goldという評価欠陥があった。raw 10/11を維持し、後から100%へ読み替えない。未知回答1問は取得の成功数に加えていない。自作診断であり独立benchmarkではない。最終開封後に検索方式は調整していない。

### 資料増加と入力token

下表は通常・履歴の10意図、各3言い換え×3順序のreference input中央値。provider framingと出力は含まない。全件取得を別にした表が正で、category名から分類した旧audit-v2は採用しない。

| 方式 | 100資料 | 1,000資料 | 10,000資料 |
| --- | ---: | ---: | ---: |
| 従来の段落選択・2,000枠 | 770 | 2,035 | 2,033 |
| 順序固定・2,000枠 | 770 | 2,035 | 2,033 |
| 段落選択・8,000枠 | 770 | 3,599.5 | 8,023.5 |
| 親節展開・8,000枠 | 1,168.5 | 5,567.5 | 7,979.5 |
| project全文 | 993 | 8,734 | 83,266 |
| **全件要求2意図：全方式共通** | **1,114.5** | **8,718.5** | **84,243.5** |

通常検索の1万資料p95は従来2,063、親節8,066、全文93,887。全件要求のp95は84,461で、2,000/8,000枠を超えたことを明示する。完全性を保つため全件を読めば入力は増える。これはローカルかネットワークかとは別の問題。原文をDBへ移すだけでは、この増加は消えない。

!資料増加と入力token (`../runs/phase2-stability-analysis-v1/tokens.png`; historical artifact not included in this preview)

raw取得行 (`../runs/phase2-stability-final-v1/rows.jsonl`; historical artifact not included in this preview)／mode別の再集計 (`../runs/phase2-stability-analysis-v1/summary.json`; historical artifact not included in this preview)／開発で固定した選定 (`../runs/phase2-stability-selection-v1/selection.json`; historical artifact not included in this preview)

### 実モデル：100資料、12問×5反復×2方式

同じ質問・同じprompt/schema・同じモデル設定で、方式を交互に実行した。各意図・方式内のrequest hashは5回一致。gpt-6-lunaのaliasを使用し、reasoning effortは変更していない。返却fingerprintはなかった。

| 指標 | 従来の段落選択 | 親節展開 |
| --- | ---: | ---: |
| 通常10問の必要事実 | 50/50 | 50/50 |
| 未知1問の安全な不明回答 | 5/5 | 5/5 |
| 権限外1問の安全な不明回答 | 5/5 | 5/5 |
| 全引用が原文と完全一致した回答 | 59/60 | 60/60 |
| 一致引用数 | 117/118 | 130/130 |
| 5回とも回答文字列が一致した意図 | 2/12 | 2/12 |
| 実input tokens合計 | 60,165 | 78,725 |
| 実output tokens合計（reasoning含む） | 17,222 | 17,943 |
| 保守単価による費用計上USD | 0.047298900 | 0.058101725 |

入力合計+30.85%、保守計上費用+22.84%。この費用は既存の高めの予約単価によるもので、請求書の実測額ではない。公式input count 24回と実usageは120/120で一致した。生成120回はすべて完了。反復120回を独立120問とは数えない。

実行結果 (`../runs/phase2-stability-model-v1/summary.json`; historical artifact not included in this preview)／機械監査 (`../runs/phase2-stability-model-analysis-v1/summary.json`; historical artifact not included in this preview)／別agent意味レビュー (`../runs/phase2-stability-semantic-agent-v1.json`; historical artifact not included in this preview)／root確認 (`../runs/phase2-stability-root-review-v1.json`; historical artifact not included in this preview)

### 実モデル：1万資料への探索的延長

100資料の結果を見た後、固定済みのretriever・質問・promptを変更せず、`mode != all`の10意図すべてを各3回、交互順で比較した。結果による問題の選別はしていない。事前計画の最終試験とは別の探索的延長であり、新しい独立検証とは呼ばない。

| 指標（各30回答） | 従来の段落選択 | 親節展開 |
| --- | ---: | ---: |
| 通常8問の必要事実 | 24/24 | 24/24 |
| 未知・権限外への安全な不明回答 | 6/6 | 6/6 |
| 回答全体に支持されない追加断定なし | 30/30 | 29/30 |
| 全引用が原文に一致 | 30/30 | 30/30 |
| 実input tokens合計 | 53,025 | 173,373 |
| 実input tokens中央値 | 2,464 | 8,769.5 |
| 実output tokens合計 | 7,791 | 8,490 |
| 保守単価による費用計上USD | 0.035591325 | 0.102359400 |

同じ10問だけに揃えた100→1万資料の実input中央値は、従来906→2,464、親節1,221→8,769.5。通常検索は上限近くで抑制されるが、資料100倍でも同じtoken数になるわけではない。providerのschema・role・非短縮JSON等を含む実inputと、上のreference tokensは別の計数なので値が異なる。今回の20個のinput countも60/60でusageと一致した。

生成は主比較120回＋延長60回、ほか接続確認1回。計数は主比較24＋延長20＋接続確認2回。今回の追加保守計上は接続確認込み**0.243414600 USD**、全期間累積**9.653204350 / 10 USD**。不明予約2件・0.600879200 USDを維持しており、請求額・APIクレジット残高の実測ではない。

延長run (`../runs/phase2-stability-scale-model-v1/summary.json`; historical artifact not included in this preview)／機械集計 (`../runs/phase2-stability-scale-model-analysis-v1/summary.json`; historical artifact not included in this preview)／別agentレビュー (`../runs/phase2-stability-scale-semantic-agent-v1.json`; historical artifact not included in this preview)／全断定まで評価したroot統合 (`../runs/phase2-stability-scale-root-review-v1.json`; historical artifact not included in this preview)

## 失敗例

- **引用のつなぎ合わせ**：従来方式、round 4、受付結果の不明回答。二つの正しい箇所を、途中の見出し・内容を省いた一つの連続引用として返した。回答内容は正しいが、完全一致引用という契約には違反した。引用文字列を毎回モデルに再生成させる弱点が現れた。
- **不要な時期の追加**：1万資料、round 2、親節方式。「復元ログを保管する」という根拠から「移行後は復元ログを保管」と回答した。移行の必須条件自体は正しいが、「移行後」は支持されない。goldの必須語やclaimsだけでなく、answer本文全体の監査が必要だった。
- **親節の重なり**：最終測定後の監査で、親節とその内側の節を両方返す冗長性が16個の親節payloadで見つかった。原文は保持するが入力を余分に使う。重なり監査 (`../runs/phase2-stability-parent-overlap-audit-v1.json`; historical artifact not included in this preview)。費用差はこの実装の結果であり、親節取得方式全般の不可避な費用とはしない。測定済み実装と結果は変更していない。
- **評価用goldの欠陥**：Quillの非所有者が読めないprivate原文を、answerableの必須根拠にしていた。監査で見逃し、凍結後に判明。元のfixture・raw得点を変更せずerrata (`../runs/phase2-stability-fixture-errata-v1.json`; historical artifact not included in this preview)を残した。情報漏えい0と、回答可能な通常問題の正答を混同しない。
- **カテゴリ名の過大解釈**：cross_documentとした2問は単一資料内の二つの証跡名を聞いていた。真の複数資料結合の検証にはなっていない。
- **開発だけの改善**：開発の条件分割1問では親節展開が有効だったが、最終では既存方式でも必要根拠を保持できた。開発8/8を最終の改善と呼ばない。
- **全件経路の成長**：全件要求は1万資料で約8.4万token。通常検索の2,000枠がそのまま使えるとの主張は棄却する。

## 再現方法

Python 3.11以上、既存`.venv`、`pip install -e '.[tokens]'`。保存先は必ず新しい名前にする。既存fixture/runは上書きしない。

```bash
TIKTOKEN_CACHE_DIR="$PWD/tokenizer-cache" .venv/bin/python scripts/evaluate_stability.py \
  --fixture fixtures/phase2-stability-v3 --split final \
  --selection runs/phase2-stability-selection-v1/selection.json \
  --output runs/phase2-stability-final-reproduction-new

.venv/bin/python scripts/analyze_stability.py \
  --run runs/phase2-stability-final-reproduction-new \
  --fixture fixtures/phase2-stability-v3 \
  --output runs/phase2-stability-analysis-reproduction-new

.venv/bin/python scripts/analyze_stability_model.py \
  --run runs/phase2-stability-model-v1 --fixture fixtures/phase2-stability-v3 \
  --output runs/phase2-stability-model-analysis-reproduction-new

.venv/bin/python scripts/analyze_stability_model.py \
  --run runs/phase2-stability-scale-model-v1 --fixture fixtures/phase2-stability-v3 \
  --output runs/phase2-stability-scale-analysis-reproduction-new

TIKTOKEN_CACHE_DIR="$PWD/tokenizer-cache" ~/.codex/bin/quiet-test -- \
  .venv/bin/python -m unittest discover -s tests
```

上は取得評価と保存済みAPI結果の再集計で、有料生成はしない。実生成は`scripts/run_stability_model.py`で、既存共有ledger・外部の既存key file・新しいoutputを明示する。全対応roundの保守予約が残額に収まらない場合は開始しない。既存上限や不明予約を解除しない。APIキーはmemoryで読み、結果へ保存しない。公開・本番移行は未実施。

探索的1万資料生成は`scripts/run_stability_scale.py`に分離した。元runのhash固定実装は維持し、追加cap 0.34 USDと共有台帳の残りの小さい方で60回分を事前確認してから実行した。すべての生成で自動再送は0。

Python 3.11/3.13で各298 tests PASS。保護されたPhase 1と初期Phase 2のhashも一致。検証receipt (`../runs/phase2-stability-validation-v1/receipt.json`; historical artifact not included in this preview)。既存rc2配布archiveは今回再生成していない。新実装は選択式の実験moduleで、workspace既定の取得方式は変更していない。

## 未検証事項

- 実Notionの継続更新、16体の認証・並列生成・日常業務全体への効果。
- 多数決による実際の回答選択、temperature/seedの効果、モデルsnapshot間の差。
- 真の複数文書照合、意味が近い競合する条件、外部benchmarkでの反復安定性。
- データ量を固定した回答品質の比較を、実運用の全資料・全質問へ一般化すること。
- 全件要求を1万資料でモデル生成した品質、実請求、運用保守・人の確認時間。

## 次の判断

順序固定は診断optionに残す。親節展開は一律の既定方式にしない。必要な条件が不足したと判断できたときの追加取得候補として扱うが、検索だけで完全性を証明する機能はまだない。

親節候補の次版では、重なる原文範囲を一つにまとめる処理をまず切り離して測る。情報を落とさずtokenが減ることと、モデル出力が改善することは別に確認する。今回の最終問題は既に露出済みなので、その再実行を新しい最終評価にはしない。

次に有望な仮説は、**確認した決定・条件・出典・版を一緒に再利用し、同じ判断を毎回生成し直す回数を減らすこと**。訂正時の失効基盤は既存workspaceにあるが、この方式の回答品質・token・費用の改善は別途測る必要がある。全件集計は、保存側で計算した件数・対象範囲・根拠を渡す方式と比較する。検索のtoken上限、集計、決定の再利用を別々の寄与として測る。

引用については、取得した原文offsetから文字列を生成するか、完全一致検査で不正な引用を拒否する方針を優先する。拒否を正答数に加えず、再取得・人の確認の追加費用も含める。多数決は、同じ誤根拠の繰り返しや生成費用を増やす可能性があるため、この境界を整えた後に比較する。
