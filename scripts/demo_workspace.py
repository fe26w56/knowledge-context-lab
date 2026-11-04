"""Run a complete fictional local-workspace demonstration."""
from __future__ import annotations
import argparse, json, shutil, tempfile
from pathlib import Path
from context_lab.workspace import Workspace

ROOT = Path(__file__).parents[1]
FIXTURE = ROOT / "fixtures/phase2-migration-v2/pages.json"

def run(workdir: Path) -> dict:
    if workdir.exists() and any(workdir.iterdir()):
        raise RuntimeError(f"workdir must be new or empty: {workdir}")
    workdir.mkdir(parents=True, exist_ok=True)
    pages = json.loads(FIXTURE.read_text(encoding="utf-8"))["pages"]
    pages = [p for p in pages if p["scope"] == "shared" and p["id"].startswith("dev-")]
    ws = Workspace(workdir / "workspace.sqlite")
    imported = ws.import_pages(pages, actor="ops-bot", request_id="demo-import")
    search = ws.search("Cedar 公開条件", actor="ops-bot", mode="current")
    source = ws.get_source("dev-cedar-main", actor="ops-bot")
    quote = "公開判定は、全テストが成功していること、脆弱性スキャンが0件であること、担当者レビューが1名以上完了していることの三つです。"
    start = source["page"]["body"].index(quote)
    evidence = {"source_id":"dev-cedar-main","source_version":source["version"],"start":start,"end":start+len(quote),"quote":quote}
    payload = {"title":"Cedarリリース","summary":"公開条件を3つ保持する。","conditions":["全テスト成功","脆弱性スキャン0件","担当者レビュー1名以上"],"state":"proposed","as_of":"2026-09-12","task_refs":["external-task:Cedar-41"]}
    published = ws.publish_topic("cedar", payload, [evidence], actor="ops-bot", expected_version=0, request_id="demo-publish")
    corrected = json.loads(json.dumps(source["page"], ensure_ascii=False))
    corrected["body"] = corrected["body"].replace("担当者レビューが1名以上完了", "担当者レビューが2名以上完了")
    correction = ws.import_pages([corrected], actor="ops-bot", request_id="demo-correction", expected_versions={"dev-cedar-main":source["version"]})
    stale = ws.get_topic("cedar", actor="ops-bot")
    historical = ws.get_topic("cedar", actor="ops-bot", version=1)
    bundle = ws.export_bundle(actor="ops-bot")
    (workdir / "bundle.json").write_text(json.dumps(bundle, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    restored = Workspace.restore_bundle(bundle, workdir / "restored.sqlite")
    parity = bundle == restored.export_bundle(actor="ops-bot")
    if not imported["committed"] or search["status"] != "found" or stale["status"] != "needs_review" or historical["payload"]["summary"] != payload["summary"] or not parity:
        raise RuntimeError("demo assertion failed")
    return {"run":"phase2-migration-demo-v2","fixture":"fixtures/phase2-migration-v2/pages.json","imported":len(imported["committed"]),"search_status":search["status"],"published_version":published["version"],"correction_version":correction["committed"][0]["version"],"topic_status_after_correction":stale["status"],"historical_status":historical["status"],"export_restore_parity":parity,"workdir":str(workdir)}

def main() -> int:
    p=argparse.ArgumentParser(); p.add_argument("--workdir",type=Path); a=p.parse_args()
    temp=None
    if a.workdir is None: temp=tempfile.mkdtemp(prefix="context-workspace-demo-"); workdir=Path(temp)
    else: workdir=a.workdir.resolve()
    try: print(json.dumps(run(workdir),ensure_ascii=False,sort_keys=True)); return 0
    finally:
        if temp: shutil.rmtree(temp,ignore_errors=True)
if __name__ == "__main__": raise SystemExit(main())
