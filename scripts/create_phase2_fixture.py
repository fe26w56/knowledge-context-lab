"""Create and freeze the Phase 2 synthetic fixture before retrieval changes."""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "fixtures" / "phase2"


def q(qid, split, category, text, expected, *, answerable=True, forbidden=None, condition=None, obsolete=None, mode="search", actor="bot_01", as_of="2026-04-20", rubric="すべての必須根拠と条件を保持し、採用状態と時点を混同しないことを確認する。"):
    return {
        "id": qid, "split": split, "category": category,
        "request": {"text": text, "actor": actor, "as_of": as_of, "mode": mode},
        "expected_quotes": expected, "forbidden_quotes": forbidden or [],
        "condition_quotes": condition or [], "obsolete_quotes": obsolete or [],
        "answerable": answerable, "rubric": rubric,
    }


def build_corpus():
    corpus = json.loads((ROOT / "fixtures/synthetic/corpus.json").read_text())
    corpus["corpus_id"] = "synthetic-research-phase2"
    corpus["fixture_kind"] = "phase2_frozen_diagnostic"
    corpus["description"] = "完全架空のPhase 2診断資料。改善実装前に固定した自作データで、独立ベンチマークではない。"
    long_rows = "\n".join(f"| 条件{i:02d} | {i*5}分 | 例外{i:02d}を確認 |" for i in range(1, 81))
    table_text = "長い条件表は見出し・単位・例外を保持して扱う。\n\n| 条件 | 閾値 | 例外 |\n|---|---:|---|\n" + long_rows
    corpus["documents"].extend([
        {"id": "p19", "title": "Nacre長期条件表（架空）", "source_url": "https://example.invalid/phase2/p19", "recorded_at": "2026-04-19", "verified_at": "2026-04-19", "scope": "shared", "owner": "bot_02", "body": "# Nacre長期条件表\n公開範囲: shared。\n\n## 長い条件表\n記録種別: report。採用状態: na。有効開始: 2026-04-01。有効終了: 未設定。確認日: 2026-04-19。\n" + table_text, "sections": [{"id": "p19_s1", "heading": "長い条件表", "text": table_text, "kind": "report", "adoption_status": "na", "valid_from": "2026-04-01", "valid_to": None, "verified_at": "2026-04-19"}]},
        {"id": "p20", "title": "Nacre旧版と現行版の比較（架空）", "source_url": "https://example.invalid/phase2/p20", "recorded_at": "2026-04-19", "verified_at": "2026-04-19", "scope": "shared", "owner": "bot_03", "body": "# Nacre旧版と現行版の比較\n公開範囲: shared。\n\n## 現行採用版\n記録種別: decision。採用状態: adopted。有効開始: 2026-04-12。有効終了: 未設定。確認日: 2026-04-19。\nNacreの同時更新はexpected_versionが一致した場合だけ適用し、競合時は新しい版を読んで確認する。\n\n## 旧版の案\n記録種別: decision。採用状態: superseded。有効開始: 2026-04-01。有効終了: 2026-04-12。確認日: 2026-04-19。\n旧版では競合時に最後の書き込みを優先する案だったが、2026年4月12日に廃止された。", "sections": [{"id": "p20_s1", "heading": "現行採用版", "text": "Nacreの同時更新はexpected_versionが一致した場合だけ適用し、競合時は新しい版を読んで確認する。", "kind": "decision", "adoption_status": "adopted", "valid_from": "2026-04-12", "valid_to": None, "verified_at": "2026-04-19"}, {"id": "p20_s2", "heading": "旧版の案", "text": "旧版では競合時に最後の書き込みを優先する案だったが、2026年4月12日に廃止された。", "kind": "decision", "adoption_status": "superseded", "valid_from": "2026-04-01", "valid_to": "2026-04-12", "verified_at": "2026-04-19"}]},
        {"id": "p21", "title": "Nacre短い引継ぎメモ（架空）", "source_url": "https://example.invalid/phase2/p21", "recorded_at": "2026-04-20", "verified_at": "2026-04-20", "scope": "shared", "owner": "bot_05", "body": "# Nacre短い引継ぎメモ\n公開範囲: shared。\n\n## 次の担当\n記録種別: decision。採用状態: adopted。有効開始: 2026-04-20。有効終了: 未設定。確認日: 2026-04-20。\n次の担当botはbot_05で、未解決の確認を完了前に保留する。", "sections": [{"id": "p21_s1", "heading": "次の担当", "text": "次の担当botはbot_05で、未解決の確認を完了前に保留する。", "kind": "decision", "adoption_status": "adopted", "valid_from": "2026-04-20", "valid_to": None, "verified_at": "2026-04-20"}]},
    ])
    return corpus


def build_queries():
    # Questions are authored directly from grounded quotes, then kept separate from the corpus.
    qs = [
        q("p2d01","dev","current_decision","キャッシュの期限設定を今採用する値は？",["Lumenの通常検索キャッシュは10分で期限切れにする。"],mode="current"),
        q("p2d02","dev","history","4月5日のキャッシュ方針を復元して。",["旧方針ではLumenの通常検索キャッシュを60分保持していた。"],mode="history",as_of="2026-04-05"),
        q("p2d03","dev","proposal","4月19日の延長案は採用決定か？",["Lumenのキャッシュを30分へ延ばす案は提案中である。4月19日に追記されたが、採用の記録はない。"]),
        q("p2d04","dev","paraphrase","所有者が一致しないprivate資料を候補に混ぜてから隠せばよい？",["privateの記録はownerが一致するbotだけが参照できる。検索後に表示を隠す方式にせず、候補を選ぶ前に公開範囲を確認する。"],condition=["検索後に表示を隠す方式にせず、候補を選ぶ前に公開範囲を確認する。"]),
        q("p2d05","dev","multi_source","Relay引継ぎと完了判定に必要なものは？",["引き継ぎには、目的、完了した範囲、未解決事項、次の操作、根拠のIDと版を含める。","Relayの作業完了には、保存が確定した根拠のIDと版が必要である。"],condition=["保存が確定した根拠のIDと版"]),
        q("p2d06","dev","retry","応答だけ消えたRelay保存はどう確認する？",["Relayの保存応答が届かなかった場合は、同じrequest_idで保存結果を照会する。"]),
        q("p2d07","dev","idempotency","同じrequest_idで異なる内容を再送した場合は？",["同じrequest_idで異なる内容を送った場合は、要求の不一致として拒否する。"]),
        q("p2d08","dev","measured_vs_target","Sora復旧の目標と実測・整合性を分けて答えて。",["Soraの復旧時間の目標は15分以内である。目標値は実績値として報告しない。","4月18日のSora復旧演習では、開始から参照再開まで18分かかった。15分以内という目標は未達だった。復元後のチェックサムは保存時と一致した。"],condition=["目標値は実績値として報告しない。"]),
        q("p2d09","dev","condition_exception","停止中に古いコピーで一般メモを返せる条件と、決定を使う処理の扱いは？",["Soraが停止している間、一般的な調査メモは取得後24時間以内のコピーを返せる。コピーを返すときは取得時刻と、現在の版を確認できていないことを表示する。","保存先が停止して確認できない場合は、その処理を保留する。"],condition=["取得後24時間以内","処理を保留"]),
        q("p2d10","dev","multiple_conditions","4人旅行で予算・同宿・時間を全部満たす候補は？",["宿泊費の上限は1人1泊8,000円で、全員が同じ宿に泊まることを必須条件とする。","波止場の宿は1人1泊7,800円で、4人が泊まれる部屋を1室確保できる。港から徒歩8分で、チェックインの締切は19時である。"],condition=["全員が同じ宿","チェックインの締切は19時"]),
        q("p2d11","dev","unknown","Lumen本番のp95応答時間の実測値は？",[],answerable=False),
        q("p2d12","dev","scope_private","bot_04専用の実験識別語をbot_01に返してよい？",[],answerable=False,forbidden=["PRIVATE_ONLY_ORANGE_731"],actor="bot_01"),
        q("p2d13","dev","condition_exception","強風予報だけで連絡船を欠航と断定できる？",["風速15メートル毎秒以上が予想される場合は、運航会社の当日発表を確認する。予報だけで欠航と断定したり、運航すると決めたりしてはならない。"],condition=["当日発表を確認"]),
        q("p2d14","dev","paraphrase","文章の修正だけで確認日を更新する運用か？",["文章の表現だけを直したときは、情報確認日を新しくしてはならない。"]),
        q("p2d15","dev","handoff_constraint","担当botが終えたと言っただけで完了にできる？",["完了の根拠が不足する場合は、状態を確認待ちとして表示する。担当botが処理を終えたと述べただけでは完了状態へ進めない。"]),
        q("p2d16","dev","long_table","Nacreの長い条件表から条件02の閾値と例外を返して。",["| 条件02 | 10分 | 例外02を確認 |"],condition=["例外02を確認"]),
        q("p2d17","dev","old_version","Nacreの現在の競合処理は何か？旧版の最後優先を現行と答えないで。",["Nacreの同時更新はexpected_versionが一致した場合だけ適用し、競合時は新しい版を読んで確認する。"],obsolete=["旧版では競合時に最後の書き込みを優先する案だったが、2026年4月12日に廃止された。"],mode="current"),
        q("p2d18","dev","short_new","Nacreの次担当と未解決時の扱いは？",["次の担当botはbot_05で、未解決の確認を完了前に保留する。"]),
        q("p2d19","dev","multi_source","船の到着、港から宿、宿の締切をまとめて確認して。",["18時10分に到着する。","港から徒歩8分で、チェックインの締切は19時である。"]),
        q("p2d20","dev","scope_private","bot_11本人が個別候補識別語を確認できる？",["bot_11の個別候補識別語はPRIVATE_ONLY_CEDAR_284である。"],actor="bot_11"),
        q("p2f01","final","current_decision","現在の端末採用はAlderかJuniperか？",["4月15日にAlder Miniを採用した。"],mode="current"),
        q("p2f02","final","proposal","軽さを優先するJuniper変更案は採用済み？",["4月19日にJuniper Airへ変更する案が追記されたが、採用はされていない。"]),
        q("p2f03","final","condition_exception","Alder採用の価格と必須バッテリー条件を揃えて答えて。",["変換器を含めた総額は75,000円で、バッテリー6時間以上という必須条件を満たすことが採用理由である。"],condition=["6時間以上"]),
        q("p2f04","final","multi_source","D1とD2のフィルター交換間隔を取り違えずに比較して。",["装置D1のフィルターは稼働200時間ごとに交換する。","装置D2のフィルターは稼働350時間ごとに交換する。"],condition=["D1","D2"]),
        q("p2f05","final","paraphrase","採用済みと購入済みは同じ状態？",["機種の採用は決まっているが、発注はまだ行っていない。採用済みと購入済みを同じ状態として扱わない。"]),
        q("p2f06","final","history","過去の判断理由を調べるとき、現在版だけで置換してよい？",["過去の判断理由を調べる要求では、その判断時点で有効だった版を参照する。現在の結論だけに置き換えると、当時の理由を説明できなくなる。"],mode="history",as_of="2026-04-05"),
        q("p2f07","final","condition_exception","空欄の振替料金を無料と判断してよい？",["欠航時の代替船と、他社便への振り替え料金は未確認である。比較表に空欄がある項目を無料と解釈しない。"],condition=["無料と解釈しない"]),
        q("p2f08","final","unknown","灯台食堂は胡桃を使わないと確定できる？",["灯台食堂が胡桃を扱わないという回答はまだ得られていない。同行者の条件を伝えて確認するまで、食事場所を確定しない。"],condition=["食事場所を確定しない"]),
        q("p2f09","final","multi_source","連絡船の風条件と食事の胡桃条件を同時に確認するには？",["予報だけで欠航と断定したり、運航すると決めたりしてはならない。","料理名だけで判断せず、店に材料と調理時の取り扱いを確認する。"],condition=["当日発表","材料と調理時"]),
        q("p2f10","final","handoff_constraint","引継ぎ後も元会話を読める前提でよい？",["後続botが元の会話を読めるとは仮定しない。"]),
        q("p2f11","final","retry","同内容のrequest_id再送は二重保存になる？",["同じrequest_idと同じ内容の再送は、最初の処理結果を返す。"]),
        q("p2f12","final","concurrency","expected_version競合時に他bot更新を自動消去してよい？",["競合したbotは新しい版を読んで内容を確認し、他botの更新を自動で消さない。"]),
        q("p2f13","final","measured_vs_target","16体同時実行の待ち時間は測定済み？",["16体のbotを同時に動かす試験は未実施である。単独で1回成功したことから、16体での待ち時間や成功率を推定しない。"]),
        q("p2f14","final","scope_private","bot_01がbot_04のprivate識別語を検索して得られる？",[],answerable=False,forbidden=["PRIVATE_ONLY_ORANGE_731"]),
        q("p2f15","final","long_table","長い表を1000 tokenに収めるため途中で条件列を削ってよい？",["長い条件表は見出し・単位・例外を保持して扱う。"],condition=["見出し・単位・例外"]),
        q("p2f16","final","short_new","Nacreメモの未解決確認は完了前にどう扱う？",["未解決の確認を完了前に保留する。"]),
        q("p2f17","final","unknown","Soraの別地域切替と複数bot継続書込は演習済み？",["別地域への切り替えと、複数botの継続書き込みは対象外だった。"]),
        q("p2f18","final","condition_exception","旅行予約は空室を保証する確定予約？",["予約はまだ行っていない。候補の空室情報は4月18日に確認したもので、その後の空室を保証しない。"],condition=["予約はまだ行っていない"]),
        q("p2f19","final","paraphrase","KBは製品名ではなく何の略称？",["この架空運用でKBは、調査結果と根拠を保管する知識庫を指す。"]),
        q("p2f20","final","unknown","実測していないp95値を推定して報告できる？",["Lumenの本番環境におけるp95応答時間はまだ測定していない。計測器を接続したことだけでは、応答時間を測定済みとは扱わない。"],condition=["測定済みとは扱わない"]),
    ]
    return {"schema_version": 1, "corpus_id": "synthetic-research-phase2", "fixture_kind": "phase2_frozen_diagnostic", "queries": qs}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    corpus = build_corpus(); queries = build_queries()
    (OUT / "corpus.json").write_text(json.dumps(corpus, ensure_ascii=False, indent=2) + "\n")
    for split in ("dev", "final"):
        data = {**queries, "queries": [x for x in queries["queries"] if x["split"] == split]}
        (OUT / f"{split}.json").write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    hashes = {name: hashlib.sha256((OUT / name).read_bytes()).hexdigest() for name in ("corpus.json", "dev.json", "final.json")}
    freeze = {"created_at": datetime.now(timezone.utc).isoformat(), "frozen_before_improvement": True, "corpus_documents": len(corpus["documents"]), "corpus_sections": sum(len(d["sections"]) for d in corpus["documents"]), "question_counts": {s: sum(q["split"] == s for q in queries["queries"]) for s in ("dev", "final")}, "sha256": hashes, "independent_benchmark": False}
    (OUT / "FREEZE.json").write_text(json.dumps(freeze, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
