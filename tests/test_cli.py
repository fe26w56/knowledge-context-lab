from contextlib import redirect_stdout
from dataclasses import asdict
import io
import json
from pathlib import Path
import tempfile
import unittest

from context_lab.cli import main
from context_lab.retrieval_v2 import Config


class CliTests(unittest.TestCase):
    def test_full_candidate_comparison_is_explicit_and_excludes_budget(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/"demo"
            with redirect_stdout(io.StringIO()):
                main(["demo","--output",str(root)])
            args=["query","--backend","file","--index",str(root/"index"),
                  "--request",str(root/"request.json"),"--unit","chars","--profile","control"]
            out=io.StringIO()
            with redirect_stdout(out):
                main(args+["--full"])
            body=json.loads(out.getvalue())["items"][0]["text"]
            self.assertIn("10分",body)
            self.assertIn("60分",body)  # Full A retains labelled history in a candidate body.
            with self.assertRaises(SystemExit):
                main(args+["--full","--budget","2000"])

    def test_installed_style_demo_with_default_profile_needs_no_selection_file(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/"demo"
            with redirect_stdout(io.StringIO()):
                main(["demo","--output",str(root)])
            out=io.StringIO()
            with redirect_stdout(out):
                main(["query","--backend","file","--index",str(root/"index"),"--request",str(root/"request.json"),"--unit","chars","--budget","2000"])
            payload=json.loads(out.getvalue())
            self.assertEqual(1,len(payload["items"]))
            self.assertIn("10分",payload["items"][0]["text"])
            self.assertNotIn("60分",out.getvalue())
            with self.assertRaises(FileExistsError):
                main(["demo","--output",str(root)])

    def test_build_query_persistence_and_scope(self):
        corpus=Path(__file__).parents[1]/"fixtures/phase2/corpus.json"
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            selection=root/"selection.json"
            selection.write_text(json.dumps({"config":asdict(Config(stage=2,split_long=True)),"budget":5000}))
            request=root/"request.json"
            request.write_text(json.dumps({"text":"キャッシュ期限","actor":"bot_01","mode":"current","as_of":"2026-04-20"}))
            payloads=[]
            for backend in ("file","sqlite"):
                index=root/backend
                with redirect_stdout(io.StringIO()):
                    main(["build","--backend",backend,"--index",str(index),"--corpus",str(corpus)])
                out=io.StringIO()
                with redirect_stdout(out):
                    main(["query","--backend",backend,"--index",str(index),"--request",str(request),"--selection",str(selection),"--unit","chars"])
                payload=json.loads(out.getvalue())
                self.assertTrue(payload["items"])
                self.assertTrue(any("10分" in x["text"] for x in payload["items"]))
                self.assertNotIn("PRIVATE_ONLY_",out.getvalue())
                payloads.append(payload)
            self.assertEqual(payloads[0],payloads[1])
