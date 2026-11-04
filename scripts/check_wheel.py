"""Install the wheel in a fresh venv and exercise both public CLI backends offline."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import venv


def check(root, wheel):
    with tempfile.TemporaryDirectory(prefix="context-lab-wheel-") as temp:
        temp = Path(temp)
        env = temp / "venv"
        venv.EnvBuilder(with_pip=True).create(env)
        python = env / "bin/python"
        isolated_env = dict(os.environ)
        for key in ("PYTHONPATH", "PYTHONHOME"):
            isolated_env.pop(key, None)
        isolated_env.update(PYTHONNOUSERSITE="1", PIP_CONFIG_FILE=os.devnull)

        def run(command, **kwargs):
            kwargs.setdefault("cwd", temp)
            return subprocess.run(command, check=True, capture_output=True,
                                  env=isolated_env, **kwargs)

        run([str(python), "-m", "pip", "install", "--no-index", "--no-deps", "--no-cache-dir", str(wheel.resolve())])
        imported = run([str(python), "-c", "import context_lab, context_lab.cli, context_lab.retrieval_release, context_lab.retrieval_completion, context_lab.snapshot, context_lab.budget, context_lab.model_eval, context_lab.workspace, context_lab.workspace_cli, context_lab.workspace_mcp; print(context_lab.__file__)",], text=True)
        installed_path = Path(imported.stdout.strip()).resolve()
        if env.resolve() not in installed_path.parents:
            raise AssertionError(f"import escaped fresh venv: {installed_path}")
        cli = env / "bin/context-lab-query"
        outputs = []
        for backend in ("file", "sqlite"):
            index = temp / backend
            run([str(cli), "build", "--backend", backend, "--index", str(index), "--corpus", str(root / "fixtures/phase2/corpus.json")], cwd=temp)
            result = run([str(cli), "query", "--backend", backend, "--index", str(index), "--selection", str(root / "configs/phase2-selected.json"), "--request", str(root / "configs/example-request.json"), "--unit", "chars", "--budget", "5000", "--diagnostics"], text=True, cwd=temp)
            value = json.loads(result.stdout)
            assert any("10分" in item["text"] for item in value["items"])
            assert len(result.stdout.strip()) <= 5000
            assert json.loads(result.stderr)["unit"] == "unicode_chars"
            outputs.append(value)
        assert outputs[0] == outputs[1]
        # Exercise the packaged default profile, demo command and both storage adapters.
        demo_dir = temp / "demo"
        run([str(cli), "demo", "--output", str(demo_dir)], cwd=temp)
        default_outputs = []
        for backend in ("file", "sqlite"):
            index = temp / f"default-{backend}"
            run([str(cli), "build", "--backend", backend, "--index", str(index), "--corpus", str(demo_dir / "corpus.json")], cwd=temp)
            result = run([str(cli), "query", "--backend", backend, "--index", str(index), "--request", str(demo_dir / "request.json"), "--unit", "chars", "--budget", "2000", "--diagnostics"], text=True, cwd=temp)
            value = json.loads(result.stdout)
            assert len(value["items"]) == 1
            assert len(result.stdout.strip()) <= 2000
            assert "10分" in result.stdout and "60分" not in result.stdout
            assert json.loads(result.stderr)["unit"] == "unicode_chars"
            default_outputs.append(value)
        assert default_outputs[0] == default_outputs[1]
        completion_outputs = []
        for backend in ("file", "sqlite"):
            result = run([str(cli), "query", "--backend", backend, "--index", str(temp / f"default-{backend}"),
                          "--request", str(demo_dir / "request.json"), "--profile", "completion",
                          "--unit", "chars", "--budget", "2000", "--diagnostics"], text=True)
            value = json.loads(result.stdout)
            assert value["items"] and "10分" in result.stdout and "60分" not in result.stdout
            assert len(result.stdout.strip()) <= 2000
            completion_outputs.append(value)
        assert completion_outputs[0] == completion_outputs[1]
        help_checks = []
        for name in ("context-lab", "context-lab-query", "context-lab-phase2", "context-lab-faults", "context-lab-release-eval", "context-lab-workflow", "context-lab-workspace", "context-lab-workspace-mcp"):
            run([str(env / "bin" / name), "--help"], cwd=temp)
            help_checks.append(name)
        # Exercise the workspace lifecycle from the installed wheel using only
        # the public fictional migration fixture.  This deliberately includes a
        # source correction so stale topic evidence is observable as review work.
        fixture = json.loads((root / "fixtures/phase2-migration-v2/pages.json").read_text(encoding="utf-8"))
        pages = [page for page in fixture["pages"] if page["scope"] == "shared" and page["id"].startswith("dev-")]
        workspace_db = temp / "workspace-demo.sqlite"
        demo_code = """
import json, sys
from context_lab.workspace import Workspace
db, pages_json, result_json = sys.argv[1:]
pages = json.load(open(pages_json, encoding='utf-8'))
ws = Workspace(db)
ws.import_pages(pages, actor='ops-bot', request_id='wheel-demo-import')
source = ws.get_source('dev-cedar-main', actor='ops-bot')
quote = '公開判定は、全テストが成功していること、脆弱性スキャンが0件であること、担当者レビューが1名以上完了していることの三つです。'
start = source['page']['body'].index(quote)
ws.publish_topic('cedar', {
    'title': 'Cedarリリース', 'summary': '公開条件を3つ保持する。',
    'conditions': ['全テスト成功', '脆弱性スキャン0件', '担当者レビュー1名以上'],
    'state': 'proposed', 'as_of': '2026-09-12', 'task_refs': ['external-task:Cedar-41']
}, [{'source_id': 'dev-cedar-main', 'source_version': 1, 'start': start,
     'end': start + len(quote), 'quote': quote}], actor='ops-bot',
   expected_version=0, request_id='wheel-demo-publish')
corrected = dict(next(page for page in pages if page['id'] == 'dev-cedar-main'))
corrected['body'] = corrected['body'].replace('担当者レビューが1名以上完了', '担当者レビューが2名以上完了')
ws.import_pages([corrected], actor='ops-bot', request_id='wheel-demo-correct', expected_versions={'dev-cedar-main': 1})
topic = ws.get_topic('cedar', actor='ops-bot')
assert topic['status'] == 'needs_review', topic
bundle = ws.export_bundle(actor='ops-bot')
restored = Workspace.restore_bundle(bundle, db + '.restored')
assert restored.export_bundle(actor='ops-bot') == bundle
json.dump({'topic_status': topic['status'], 'bundle_parity': True}, open(result_json, 'w'), ensure_ascii=False)
"""
        # Materialize the fixture only inside the temporary wheel check area.
        # The installed package is still imported with PYTHONPATH removed.
        (temp / "pages.json").write_text(json.dumps(pages, ensure_ascii=False), encoding="utf-8")
        run([str(python), "-c", demo_code, str(workspace_db), str(temp / "pages.json"), str(temp / "workspace-demo.json")], cwd=temp)
        workspace_demo = json.loads((temp / "workspace-demo.json").read_text(encoding="utf-8"))
        mcp_messages = """{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-11-25"}}
{"jsonrpc":"2.0","method":"notifications/initialized"}
{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"context","arguments":{"request":"合計で全件を確認","coverage":"all"}}}
"""
        mcp = subprocess.run([str(python), "-m", "context_lab.workspace_mcp", "--db", str(workspace_db), "--actor", "ops-bot"], cwd=temp, input=mcp_messages, text=True, capture_output=True, env=isolated_env, check=True)
        replies = [json.loads(line) for line in mcp.stdout.splitlines() if line.strip()]
        assert replies[0]["result"]["protocolVersion"] == "2025-11-25"
        assert replies[1]["result"]["structuredContent"]["policy"]["selected"] == "all"
        workspace_mcp_context = replies[1]["result"]["structuredContent"]["returned_source_count"] == len(pages)
        assert workspace_mcp_context, "fresh MCP returned incomplete context"
    return dict(ok=True, wheel_name=wheel.name, wheel_sha256=hashlib.sha256(wheel.read_bytes()).hexdigest(), fresh_venv=True,
                backends=["file", "sqlite"], payloads_equal=True, default_profile=True, completion_profile=True, demo=True,
                expected_cache_policy_found=True, unit="unicode_chars",
                network_used=False, import_from_fresh_venv=True, workspace_interfaces=True,
                workspace_demo=True, workspace_demo_topic_status=workspace_demo["topic_status"],
                workspace_demo_export_restore_parity=workspace_demo["bundle_parity"],
                workspace_mcp_context=workspace_mcp_context, console_entrypoints_checked=help_checks)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--wheel", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    result = check(Path(__file__).resolve().parents[1], args.wheel)
    with args.output.open("x") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(json.dumps(result))
