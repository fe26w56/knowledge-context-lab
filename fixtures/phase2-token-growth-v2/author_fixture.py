"""Author a varied token-growth diagnostic without boilerplate padding."""
from __future__ import annotations
import hashlib, importlib.util, json, random
from pathlib import Path

ROOT = Path(__file__).parent
SEED = 20261103
PROJECTS = ["atlas", "birch", "cobalt", "delta", "ember", "fjord", "grove", "harbor"]
VARIED = [
    ("リスク", "失敗すると担当の確認が遅れ、古い判断が現行手順へ混入する。影響範囲と検知方法を別々に記録する。"),
    ("展開", "小さな対象で確認してから段階的に広げる。切り戻し条件と観測する指標を先に決める。"),
    ("レビュー記録", "レビューでは主張、根拠、適用条件、未確認事項を分ける。承認されていない案は提案として残す。"),
    ("制約", "担当者の不在、参照期限、権限範囲を考慮する。条件が足りない場合は推測で補完せず、追加確認へ回す。"),
    ("代替案", "簡素な運用と自動化案を比較した。自動化案は更新費が増えるため、再利用回数が増えた場合だけ再評価する。"),
    ("測定", "成功件数だけでなく、根拠の取りこぼし、旧版の混入、入力トークン、再確認に要した時間を記録する。"),
    ("引き継ぎ項目", "次の担当へ対象、現在の状態、次の期限、最後に確認した版、残った疑問を渡す。完了と未確認を混同しない。"),
    ("境界", "この判断は指定プロジェクトの共有資料に限る。別プロジェクトや私的資料の内容は同じ質問へ持ち込まない。"),
]
EXTRA = [("入力", "依頼の範囲、基準日、参照できなかった範囲を記録する。"), ("判断", "決定と保留を分け、理由を短く残す。"), ("確認", "数値と単位は原文のまま保持する。"), ("失敗時", "再試行条件と途中結果の扱いを記録する。"), ("依存", "外部資料の参照日と取得状態を残す。"), ("変更履歴", "変更前後の要点を上書きせず残す。"), ("利用例", "典型例と例外例を分ける。"), ("終了条件", "確認済み、追加確認、廃止を区別する。"), ("責任", "判断の責任者と確認者を別々に記録する。"), ("期限", "期限の根拠と延長時の承認を記録する。"), ("通知", "関係者へ伝えた内容と時点を記録する。"), ("回復", "復旧後に再発防止の確認項目を残す。")]
SUPPLEMENT = [("用語", "専門語の意味と、この資料での使い方を明記する。"), ("対象外", "対象外の要求を別記し、暗黙の前提へ戻さない。"), ("入力品質", "不足や矛盾を見つけた場合はその状態を保持する。"), ("照合", "複数の根拠を照合し、片方だけで結論を確定しない。"), ("連絡", "連絡手段が使えない場合の代替経路を記録する。"), ("保留", "保留理由と再開条件を明示する。"), ("承認", "承認者の役割と承認対象の版を記録する。"), ("期限後", "期限を過ぎた記録は現行状態と分けて扱う。"), ("棚卸し", "定期的な見直しの頻度と観測値を保存する。"), ("終了", "終了理由と再開の可能性を記録する。")]
SUPPLEMENT.append(("監視", "定期的な監視値の変化と、変化を検知した時刻を保存する。"))
SUPPLEMENT.append(("合意", "関係者が合意した範囲と、合意していない点を記録する。"))

def _v1():
    p = ROOT.parent / "phase2-token-growth-v1" / "author_fixture.py"
    spec = importlib.util.spec_from_file_location("v1_fixture", p)
    mod = importlib.util.module_from_spec(spec); assert spec.loader
    spec.loader.exec_module(mod)
    return mod

def _digest(path: Path) -> str: return hashlib.sha256(path.read_bytes()).hexdigest()

def _varied_body(project: str, idx: int, tail: str = "", long: bool = False) -> str:
    rng = random.Random(SEED + idx * 97)
    sections = VARIED[:]
    rng.shuffle(sections)
    out = [f"# {project.title()} knowledge note {idx:03d}", f"対象: {project}。これは架空の作業資料で、更新後の状態と根拠の版を分けて管理する。"]
    for heading, paragraph in sections:
        out += [f"## {heading}", f"{project}について{paragraph}"]
    for heading, paragraph in EXTRA:
        out += [f"## {heading}", f"{project}について{paragraph}"]
    for heading, paragraph in SUPPLEMENT:
        out += [f"## {heading}", f"{project}について{paragraph}"]
    out += ["## 観測対象", f"対象期間は2026年10月。資料 {idx:03d} の変更者、参照期限、利用範囲を確認し、関連する記録へリンクする。"]
    if tail: out += ["## 決定または根拠", tail]
    if long:
        extra = [("運用観察", "問い合わせの傾向と判断の分岐を月次で確認する。"), ("例外整理", "通常手順から外れる場合の承認者と復旧条件を残す。"), ("将来検討", "資料の増加で検索結果が不安定になったら索引と版管理を見直す。"), ("比較記録", "代替案の採用理由、見送った理由、再検討の条件を記録する。")]
        for n in range(1, 130):
            h, b = extra[(n - 1) % len(extra)]; out += [f"## {h} {n:02d}", f"{project}の{b}観測番号は{n:02d}で、前の観測とは別の確認単位として扱う。"]
    return "\n".join(out)

FINAL_TOPICS = [
    ("iris", "I1", "Iris policy", "Irisの現行方針は金曜にレビューし、公開前に担当が版を確認する。", "Iris evidence", "根拠は承認ログと月次監査表に保存する。"),
    ("juno", "J1", "Juno gate", "Junoは全件再現試験とp95 700ms未満を承認条件にする。", "Juno handoff", "失敗IDと再実行担当を引き継ぐ。"),
    ("kepler", "K1", "Kepler retention", "Keplerの現行資料は90日、監査履歴は500日保存する。", "Kepler evidence", "削除前に保留一覧と保存表を確認する。"),
    ("lumen", "L1", "Lumen routing", "Lumenの緊急問い合わせは当番へ、通常は翌営業日キューへ送る。", "Lumen handoff", "未処理IDと次の確認条件を引き継ぐ。"),
    ("mesa", "M1", "Mesa proposal", "Mesa案は未採用の提案で、2名レビューと再現ログが必要だ。", "Mesa evidence", "現時点は1名レビューのため採用条件未達である。"),
    ("nova", "N1", "Nova history", "Novaの2026-08-11障害では旧設定900msを使用した。", "Nova current", "現在値は600msで、旧設定は履歴だけに使う。"),
    ("opal", "O1", "Opal inventory", "Opalの登録機材は三脚、センサー、ケーブルの3種である。", "Opal evidence", "返却記録と在庫表を月末に突き合わせる。"),
    ("quartz", "Q1", "Quartz access", "Quartz共有資料はagent-aとagent-cが閲覧できる。", "Quartz handoff", "権限変更は本人確認と承認記録が必要だ。"),
    ("river", "R1", "River policy", "Riverの現行レビューは火曜で、緊急障害なら当日確認を許可する。", "River evidence", "根拠は監査ログとチェックリストに分けて保存する。"),
]

def base_corpus() -> list[dict]:
    v1 = _v1(); old = v1.base_corpus(); docs=[]
    for i, src in enumerate(old):
        body = src["body"]
        marker = "## 決定\n" if "## 決定\n" in body else "## 根拠\n"
        tail = body.split(marker, 1)[1] if marker in body else ""
        docs.append({**src, "body": _varied_body(src["project"], i + 1, tail, long=(i in {2, 8}))})
    start = len(docs)
    for j, (project, code, title, body1, title2, body2) in enumerate(FINAL_TOPICS):
        docs.append({"id":f"src-final-{code.lower()}-decision","title":title,"project":project,"status":"current","scope":"shared","owner":"","updated_at":"2026-10-30","body":_varied_body(project,start+j*2,body1)})
        docs.append({"id":f"src-final-{code.lower()}-evidence","title":title2,"project":project,"status":"current","scope":"shared","owner":"","updated_at":"2026-10-30","body":_varied_body(project,start+j*2+1,body2)})
    return docs

def questions():
    dev, _ = _v1().questions()
    final=[]
    for project, code, title, body1, title2, body2 in FINAL_TOPICS:
        final.append({"qid":f"final-{code.lower()}-1","text":f"{project}の現行方針と条件は？","project":project,"mode":"current","category":"conditions","required_source_ids":[f"src-final-{code.lower()}-decision"],"required_quotes":[body1]})
        final.append({"qid":f"final-{code.lower()}-2","text":f"{project}の根拠または引き継ぎを答えて","project":project,"mode":"current","category":"evidence","required_source_ids":[f"src-final-{code.lower()}-evidence"],"required_quotes":[body2]})
    return dev, final

def generate(size: int, scenario: str = "mixed", seed: int = SEED, length_multiplier: int = 1) -> list[dict]:
    if size < 1 or scenario not in {"mixed", "unrelated", "long"} or length_multiplier < 1: raise ValueError("invalid size, scenario, or length_multiplier")
    docs = base_corpus(); rng = random.Random(seed + size + {"mixed":17,"unrelated":31,"long":53}[scenario])
    if scenario == "unrelated":
        docs = docs[:len(base_corpus())]
    while len(docs) < size:
            i = len(docs)
            project=("unrelated-" + str(rng.randrange(20))) if scenario == "unrelated" else PROJECTS[rng.randrange(len(PROJECTS))]
            docs.append({"id":f"src-scale-{i:05d}","title":f"{project.title()} scale note {i:05d}","project":project,"status":"current","scope":"shared","owner":"","updated_at":"2026-10-30","body":_varied_body(project,i)})
    if scenario == "mixed":
        # Every scale size contains the same family pressure, with evaluator-only counts derived later.
        for i, target in enumerate(range(len(base_corpus()), size)):
            if target % 101 == 0 and target > len(base_corpus()): docs[i+len(base_corpus())]["body"] = docs[3]["body"]
            elif target % 137 == 0 and target > len(base_corpus()): docs[i+len(base_corpus())]["status"]="historical"; docs[i+len(base_corpus())]["body"] = docs[3]["body"].replace("2026", "2025")
            elif target % 173 == 0 and target > len(base_corpus()): docs[i+len(base_corpus())]["body"] = docs[3]["body"].replace("毎週", "隔週")
        if size >= 100:
            docs[40]["body"] = docs[3]["body"]
            docs[41]["body"] = docs[3]["body"]
            docs[42]["status"] = "historical"; docs[42]["body"] = docs[3]["body"].replace("2026", "2025")
            docs[43]["body"] = docs[3]["body"].replace("毎週", "隔週")
    if scenario == "long" and length_multiplier > 1:
        for i in range(min(12, len(docs))):
            for _ in range(length_multiplier - 1): docs[i]["body"] += "\n\n" + _varied_body(docs[i]["project"], i + 100 + _)[-700:]
    return docs

def generation_metadata(size: int, scenario: str = "mixed", seed: int = SEED, length_multiplier: int = 1) -> dict:
    docs = generate(size, scenario, seed, length_multiplier); bodies=[d["body"] for d in docs]
    return {"size":size,"scenario":scenario,"seed":seed,"length_multiplier":length_multiplier,"counts":{"sources":len(docs),"historical":sum(d["status"]=="historical" for d in docs),"private":sum(d["scope"]=="private" for d in docs),"exact_duplicate_body_groups":sum(bodies.count(b)>1 for b in set(bodies))},"body_chars":sum(len(b) for b in bodies)}

def main():
    ROOT.mkdir(parents=True, exist_ok=True); docs=generate(100,"mixed",SEED); dev, final=questions()
    (ROOT/"corpus.json").write_text(json.dumps(docs,ensure_ascii=False,indent=2)+"\n")
    (ROOT/"dev.json").write_text(json.dumps(dev,ensure_ascii=False,indent=2)+"\n")
    (ROOT/"final.json").write_text(json.dumps(final,ensure_ascii=False,indent=2)+"\n")
    hashes={n:_digest(ROOT/n) for n in ("author_fixture.py","corpus.json","dev.json","final.json")}
    lengths=[len(d["body"]) for d in docs]; bodies=[d["body"] for d in docs]
    meta={"schema":"phase2-token-growth-freeze-v2","seed":SEED,"authored_diagnostic":True,"independent_benchmark":False,"corpus_count":100,"dev_count":len(dev),"final_count":len(final),"dev_projects":sorted({q["project"] for q in dev}),"final_projects":sorted({q["project"] for q in final}),"min_body_chars":min(lengths),"long_body_count_ge_6000":sum(x>=6000 for x in lengths),"exact_duplicate_body_groups":sum(bodies.count(b)>1 for b in set(bodies)),"status_historical_count":sum(d["status"]=="historical" for d in docs),"mixed_generation_metadata":{"100":generation_metadata(100,"mixed"),"1000":generation_metadata(1000,"mixed"),"10000":generation_metadata(10000,"mixed")},"unrelated_generation_metadata":{"100":generation_metadata(100,"unrelated"),"1000":generation_metadata(1000,"unrelated")},"files":hashes}
    (ROOT/"FREEZE.json").write_text(json.dumps(meta,ensure_ascii=False,indent=2)+"\n")

if __name__ == "__main__": main()
