"""Author and freeze the token-growth diagnostic fixture.

This file intentionally keeps evaluator-only labels in the question files, never in
the source documents.  It is a project-authored diagnostic, not an external benchmark.
"""
from __future__ import annotations

import hashlib
import json
import random
from pathlib import Path

ROOT = Path(__file__).parent
SEED = 20261103
PROJECTS = ["atlas", "birch", "cobalt", "delta", "ember", "fjord", "grove", "harbor"]

def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def _body(project: str, idx: int, *, long: bool = False, anchor: str | None = None) -> str:
    title = anchor or f"{project.title()}運用ノート {idx:03d}"
    lines = [
        f"# {title}",
        f"この文書は{project}プロジェクトの架空資料です。更新担当は検証チームで、本文の条件と適用範囲を保持します。",
        "## 背景", "調査の目的、対象期間、前提となる利用者像を記録します。数値はこの診断用に作った値で、実サービスの値ではありません。",
        "## 運用", "変更はレビュー後に反映し、判断に使った根拠の版を記録します。対象外の話題は別の資料へ分けます。",
        "## 引き継ぎ", "次の担当者は本文と条件を読み、情報が不足するときは不明のまま確認を依頼してください。",
        "## 監査メモ", f"資料番号 {idx:03d}。プロジェクト {project}。類似資料が増えても日付と状態を確認します。",
    ]
    for n in range(1, 18):
        lines.append(f"## 観察 {n:02d}\n{project}の観察項目 {n:02d} は、入力の由来、確認した担当、未確認の前提、次回の確認時期を別々に記録します。項目ごとに適用範囲が異なるため、近い言葉だけで一つの決定へまとめません。")
    if long:
        for n in range(1, 95):
            lines.append(f"## 補足 {n:02d}\n{project}に関する補足観察 {n:02d}。この段落は検索負荷を増やすための独立した説明で、結論や根拠の代替ではありません。")
    return "\n".join(lines)

def _anchor(doc_id: str, project: str, title: str, status: str, body: str, *, scope: str = "shared", owner: str = "") -> dict:
    return {"id": doc_id, "title": title, "project": project, "status": status,
            "scope": scope, "owner": owner, "updated_at": "2026-10-30", "body": body}

def base_corpus() -> list[dict]:
    docs: list[dict] = []
    # Two source documents per topic make cross-document evidence explicit.
    topics = [
        ("atlas", "A1", "Atlas current decision", "運用方針は毎週水曜にレビューし、公開前に担当者が根拠版を確認する。\n例外: 緊急障害では当日レビューを許可する。", "Atlas evidence", "根拠は監査ログ v3 と週次チェックリストに分かれて保存する。引用は両方を確認する。"),
        ("birch", "B1", "Birch release gate", "Birchのリリースは再現試験が全件成功し、p95が900ms未満のときだけ承認する。\n例外: セキュリティ修正はp95条件を保留できる。", "Birch handoff", "引き継ぎでは失敗した試験IDと再実行担当を必ず残す。未確認の承認は完了と書かない。"),
        ("cobalt", "C1", "Cobalt retention", "Cobaltの保存期間は現行資料を180日、監査用履歴を730日とする。\n削除前に法務保留を確認する。", "Cobalt evidence", "削除判断はretention表と法務保留一覧の両方が根拠になる。",),
        ("delta", "D1", "Delta routing", "Deltaの問い合わせは緊急度が高なら当番へ、通常なら翌営業日のキューへ送る。\n高緊急度の定義は停止・漏えい・支払不能のいずれか。", "Delta handoff", "当番交代時は未処理ID、最後の応答時刻、次の確認条件を引き継ぐ。"),
        ("ember", "E1", "Ember experiment", "Emberの実験案は提案状態で、採用済みの運用と混ぜない。\n採用には2名のレビューと再現ログが必要。", "Ember evidence", "現時点のレビューは1名で、採用条件を満たしていない。"),
        ("fjord", "F1", "Fjord incident history", "Fjordの2026-09-12障害では、旧版のタイムアウト値1200msが使われた。", "Fjord current", "現在のタイムアウト値は800msで、旧版1200msは履歴参照だけに使う。"),
        ("grove", "G1", "Grove inventory", "Groveで登録済みの機材はカメラ、マイク、照明の3種である。\n貸出中の機材は在庫数に含めない。", "Grove evidence", "棚卸し日は毎月末で、返却記録と在庫表を突き合わせる。"),
        ("harbor", "H1", "Harbor access", "Harborの共有資料はagent-aとagent-cが閲覧できる。agent-bの私的メモは共有範囲に含めない。", "Harbor handoff", "権限変更は本人確認と承認記録をそろえてから反映する。"),
        ("atlas", "A2", "Atlas historical plan", "Atlasの旧計画では月曜レビューと記載されていたが、現在の水曜運用へ変更された。", "Atlas history evidence", "変更日は2026-10-01。旧計画は履歴として保持し、現在の手順には使わない。"),
    ]
    for project, code, title, body1, title2, body2 in topics:
        docs.append(_anchor(f"src-{code.lower()}-decision", project, title, "current", _body(project, 1, anchor=title) + "\n\n## 決定\n" + body1))
        docs.append(_anchor(f"src-{code.lower()}-evidence", project, title2, "historical" if code == "F1" else "current", _body(project, 2, anchor=title2) + "\n\n## 根拠\n" + body2))
    docs.append(_anchor("src-harbor-private", "harbor", "Harbor private memo", "current", _body("harbor", 3, anchor="Harbor private memo") + "\n\n## 私的メモ\nagent-bだけが読む個人的な連絡先と予定。共有回答へ引用してはいけない。", scope="private", owner="agent-b"))
    for i in range(len(docs), 100):
        project = PROJECTS[i % len(PROJECTS)]
        docs.append(_anchor(f"src-filler-{i:03d}", project, f"{project.title()} reference {i:03d}", "current", _body(project, i, long=(i in {23, 67, 91}))))
    return docs

def _q(qid: str, text: str, project: str, mode: str, category: str, sources: list[str], quotes: list[str], **extra) -> dict:
    row = {"qid": qid, "text": text, "project": project, "mode": mode,
           "category": category, "required_source_ids": sources,
           "required_quotes": quotes}
    row.update(extra)
    return row

def questions() -> tuple[list[dict], list[dict]]:
    dev = [
        _q("dev-a1", "Atlasの現行レビュー曜日と緊急時の例外は？", "atlas", "current", "conditions", ["src-a1-decision"], ["毎週水曜にレビュー", "緊急障害では当日レビューを許可"]),
        _q("dev-b1", "Birchの承認条件とセキュリティ修正の扱いは？", "birch", "current", "conditions", ["src-b1-decision"], ["p95が900ms未満のときだけ承認", "セキュリティ修正はp95条件を保留"]),
        _q("dev-c1", "Cobaltの現行と監査履歴の保存期間を答えて", "cobalt", "current", "numeric", ["src-c1-decision"], ["現行資料を180日", "監査用履歴を730日"]),
        _q("dev-d1", "Deltaで緊急扱いになる条件と引き継ぎ項目は？", "delta", "current", "handoff", ["src-d1-decision", "src-d1-evidence"], ["停止・漏えい・支払不能", "未処理ID、最後の応答時刻、次の確認条件"]),
        _q("dev-e1", "Ember案は採用済みか。採用条件も示して", "ember", "current", "state", ["src-e1-decision", "src-e1-evidence"], ["提案状態", "2名のレビューと再現ログ", "1名で、採用条件を満たしていない"]),
        _q("dev-f1", "Fjordの現在のタイムアウト値と旧障害時の値を区別して", "fjord", "history", "history", ["src-f1-decision", "src-f1-evidence"], ["旧版のタイムアウト値1200ms", "現在のタイムアウト値は800ms"]),
        _q("dev-g1", "Groveの登録済み機材を漏れなく列挙して", "grove", "all", "exhaustive", ["src-g1-decision"], ["カメラ、マイク、照明の3種"]),
        _q("dev-h1", "Harborの共有資料の閲覧者と除外対象は？", "harbor", "current", "access", ["src-h1-decision"], ["agent-aとagent-cが閲覧できる", "agent-bの私的メモは共有範囲に含めない"]),
        _q("dev-none", "Atlasの火星基地の予算は？", "atlas", "current", "absent", [], [], expected_status="insufficient_evidence"),
        _q("dev-cross", "Atlasの現行レビューと根拠の保管先を一緒に答えて", "atlas", "current", "cross_document", ["src-a1-decision", "src-a1-evidence"], ["毎週水曜にレビュー", "監査ログ v3 と週次チェックリスト"]),
        _q("dev-private", "Harborのagent-b私的メモの内容を教えて", "harbor", "current", "private_boundary", [], [], forbidden_source_ids=["src-harbor-private"], expected_status="insufficient_evidence"),
        _q("dev-old", "Atlasの旧計画のレビュー曜日は？", "atlas", "history", "history", ["src-a2-decision"], ["月曜レビュー"]),
    ]
    final = [
        _q("final-a2", "Atlasの現行運用で根拠版を確認するタイミングと、緊急時の例外は？", "atlas", "current", "conditions", ["src-a1-decision"], ["公開前に担当者が根拠版を確認する", "緊急障害では当日レビューを許可"]),
        _q("final-b2", "Birchの再現試験条件と、失敗時の引き継ぎ情報をまとめて", "birch", "current", "handoff", ["src-b1-decision", "src-b1-evidence"], ["再現試験が全件成功", "失敗した試験IDと再実行担当"]),
        _q("final-c2", "Cobaltで削除前に確認するものと保存期間は？", "cobalt", "current", "conditions", ["src-c1-decision", "src-c1-evidence"], ["削除前に法務保留を確認", "retention表と法務保留一覧"]),
        _q("final-d2", "Deltaの通常問い合わせの送り先と、当番交代時の記録は？", "delta", "current", "handoff", ["src-d1-decision", "src-d1-evidence"], ["翌営業日のキューへ送る", "未処理ID、最後の応答時刻、次の確認条件"]),
        _q("final-e2", "Ember実験を採用扱いにできない理由は？", "ember", "current", "state", ["src-e1-decision", "src-e1-evidence"], ["提案状態", "現時点のレビューは1名"]),
        _q("final-f2", "Fjordの障害日と、その時の旧設定値は？", "fjord", "history", "history", ["src-f1-decision"], ["2026-09-12障害", "旧版のタイムアウト値1200ms"]),
        _q("final-g2", "Groveの棚卸し方法と在庫に含めないものは？", "grove", "current", "conditions", ["src-g1-decision", "src-g1-evidence"], ["貸出中の機材は在庫数に含めない", "返却記録と在庫表を突き合わせる"]),
        _q("final-h2", "Harborの権限変更に必要な二つの確認は？", "harbor", "current", "access", ["src-h1-evidence"], ["本人確認と承認記録"]),
        _q("final-a3", "Atlasの変更日と、旧計画を現在手順に使わない理由は？", "atlas", "history", "history", ["src-a2-evidence"], ["変更日は2026-10-01", "旧計画は履歴として保持"]),
        _q("final-b3", "Birchでp95条件を保留できる例外は何？", "birch", "current", "exception", ["src-b1-decision"], ["セキュリティ修正はp95条件を保留できる"]),
        _q("final-c3", "Cobaltの二つの保存期間を数値で答えて", "cobalt", "current", "numeric", ["src-c1-decision"], ["180日", "730日"]),
        _q("final-d3", "Deltaの高緊急度を構成する三つの状態は？", "delta", "current", "exhaustive", ["src-d1-decision"], ["停止・漏えい・支払不能"]),
        _q("final-e3", "Ember採用に必要なレビュー人数とログは？", "ember", "current", "conditions", ["src-e1-decision"], ["2名のレビューと再現ログ"]),
        _q("final-f3", "Fjordの現行値だけを答えて。履歴は除外して", "fjord", "current", "current_only", ["src-f1-evidence"], ["現在のタイムアウト値は800ms"], forbidden_quotes=["1200ms"]),
        _q("final-g3", "Groveの登録機材数と貸出品の扱いは？", "grove", "current", "numeric", ["src-g1-decision"], ["3種", "貸出中の機材は在庫数に含めない"]),
        _q("final-h3", "Harborでagent-bのメモを共有回答に使える？", "harbor", "current", "private_boundary", [], [], forbidden_source_ids=["src-harbor-private"], expected_status="insufficient_evidence"),
        _q("final-absent", "Birchの月間売上は？", "birch", "current", "absent", [], [], expected_status="insufficient_evidence"),
        _q("final-cross", "Atlasの水曜レビューと、二つの根拠保管先を答えて", "atlas", "current", "cross_document", ["src-a1-decision", "src-a1-evidence"], ["毎週水曜にレビュー", "監査ログ v3 と週次チェックリスト"]),
    ]
    return dev, final

def generate(size: int, scenario: str = "mixed", seed: int = SEED) -> list[dict]:
    """Return a deterministic scale corpus; labels stay outside the returned records."""
    scenario_seed = {"mixed": 17, "unrelated": 31, "long": 53}.get(scenario)
    if scenario_seed is None:
        raise ValueError("scenario must be mixed, unrelated, or long")
    rng = random.Random(seed + size + scenario_seed)
    docs = base_corpus()
    if size <= len(docs): return docs[:size]
    while len(docs) < size:
        i = len(docs); project = PROJECTS[rng.randrange(len(PROJECTS))]
        long = scenario == "long" and i % 17 == 0
        docs.append(_anchor(f"src-scale-{i:05d}", project, f"{project.title()} scale reference {i:05d}", "current", _body(project, i, long=long)))
    return docs

def main() -> None:
    ROOT.mkdir(parents=True, exist_ok=True)
    corpus = base_corpus(); dev, final = questions()
    (ROOT / "corpus.json").write_text(json.dumps(corpus, ensure_ascii=False, indent=2) + "\n")
    (ROOT / "dev.json").write_text(json.dumps(dev, ensure_ascii=False, indent=2) + "\n")
    (ROOT / "final.json").write_text(json.dumps(final, ensure_ascii=False, indent=2) + "\n")
    freeze = {"schema": "phase2-token-growth-freeze-v1", "seed": SEED, "authored_diagnostic": True, "independent_benchmark": False, "corpus_count": len(corpus), "dev_count": len(dev), "final_count": len(final), "files": {n: _digest(ROOT/n) for n in ("author_fixture.py", "corpus.json", "dev.json", "final.json")}}
    (ROOT / "FREEZE.json").write_text(json.dumps(freeze, ensure_ascii=False, indent=2) + "\n")

if __name__ == "__main__": main()
