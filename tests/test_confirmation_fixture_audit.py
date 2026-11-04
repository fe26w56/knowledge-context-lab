import hashlib, json, shutil, tempfile, unittest
from pathlib import Path
from scripts.audit_confirmation_fixture import audit_fixture

ROOT = Path(__file__).parents[1]
FIXTURE = ROOT / "fixtures/phase2-confirmation-v5"

class ConfirmationFixtureAuditTests(unittest.TestCase):
    def copy_fixture(self):
        temp = Path(tempfile.mkdtemp()); fixture = temp / "fixture"; shutil.copytree(FIXTURE, fixture)
        return temp, fixture

    def rewrite(self, fixture, name, mutate):
        path = fixture / name; data = json.loads(path.read_text()); mutate(data); path.write_text(json.dumps(data))
        freeze = json.loads((fixture / "FREEZE.json").read_text())
        freeze["sha256"][name] = hashlib.sha256(path.read_bytes()).hexdigest()
        (fixture / "FREEZE.json").write_text(json.dumps(freeze))

    def assert_failure(self, fixture, needle, out):
        with self.assertRaisesRegex(ValueError, "structural audit failed"):
            audit_fixture(fixture, out)
        result = json.loads((out / "audit.json").read_text())
        self.assertTrue(any(needle in f["message"] for f in result["failures"]), result["failures"])

    def test_frozen_fixture_passes_and_semantics_remain_unvalidated(self):
        temp, fixture = self.copy_fixture()
        try:
            result = audit_fixture(fixture, temp / "out")
            self.assertTrue(result["structural_valid"]); self.assertFalse(result["semantic_validated"])
            self.assertEqual(result["counts"]["questions"], 40)
        finally: shutil.rmtree(temp)

    def test_hash_mismatch_is_reported_separately(self):
        temp, fixture = self.copy_fixture()
        try:
            (fixture / "corpus.json").write_text((fixture / "corpus.json").read_text() + " ")
            self.assert_failure(fixture, "FREEZE hash mismatch", temp / "out")
        finally: shutil.rmtree(temp)

    def test_hidden_body_paragraph_is_rejected_after_hash_update(self):
        temp, fixture = self.copy_fixture()
        try:
            def mutate(d): d["documents"][0]["body"] += "\n\nUnindexed hidden paragraph."
            self.rewrite(fixture, "corpus.json", mutate)
            self.assert_failure(fixture, "not covered by section interval", temp / "out")
        finally: shutil.rmtree(temp)

    def test_quote_must_be_in_indexed_section_after_hash_update(self):
        temp, fixture = self.copy_fixture()
        try:
            def mutate(d): d["queries"][0]["rubric"]["atomic_claims"][0]["evidence_quote"] = "Aster release current operating decision"
            self.rewrite(fixture, "dev.json", mutate)
            self.assert_failure(fixture, "quote absent from indexed section", temp / "out")
        finally: shutil.rmtree(temp)

    def test_source_scope_mismatch_is_rejected_after_hash_update(self):
        temp, fixture = self.copy_fixture()
        try:
            def mutate(d): d["queries"][0]["request"]["scope"] = "private"
            self.rewrite(fixture, "dev.json", mutate)
            self.assert_failure(fixture, "source scope differs", temp / "out")
        finally: shutil.rmtree(temp)

    def test_history_date_outside_interval_is_rejected_even_if_superseded(self):
        temp, fixture = self.copy_fixture()
        try:
            def mutate(d):
                q = next(x for x in d["queries"] if x["category"] == "history")
                q["request"]["as_of"] = "2028-01-01"
            self.rewrite(fixture, "dev.json", mutate)
            self.assert_failure(fixture, "date interval invalid", temp / "out")
        finally: shutil.rmtree(temp)

    def test_category_mode_and_private_owner_are_checked(self):
        temp, fixture = self.copy_fixture()
        try:
            def mutate(d):
                q = next(x for x in d["queries"] if x["category"] == "history"); q["request"]["mode"] = "current"
            self.rewrite(fixture, "dev.json", mutate)
            self.assert_failure(fixture, "requires mode=history", temp / "out")
        finally: shutil.rmtree(temp)

    def test_section_text_must_occur_in_body(self):
        temp, fixture = self.copy_fixture()
        try:
            def mutate(d): d["documents"][0]["sections"][0]["text"] = "not in body"
            self.rewrite(fixture, "corpus.json", mutate)
            self.assert_failure(fixture, "does not occur in document body", temp / "out")
        finally: shutil.rmtree(temp)

    def test_private_owner_mismatch_with_matching_scope(self):
        temp, fixture = self.copy_fixture()
        try:
            def private_source(d): d['documents'][0]['scope'] = 'private'
            def private_request(d): d['queries'][0]['request']['scope'] = 'private'
            self.rewrite(fixture, 'corpus.json', private_source)
            self.rewrite(fixture, 'dev.json', private_request)
            self.assert_failure(fixture, 'private source owner differs', temp/'out')
        finally: shutil.rmtree(temp)

    def test_actor_boundary_mismatch(self):
        temp, fixture = self.copy_fixture()
        try:
            def mutate(d):
                q = next(q for q in d['queries'] if q['category'] == 'private_boundary')
                q['rubric']['access_boundary'] = {'attempting_actor': 'somebody-else'}
            self.rewrite(fixture, 'dev.json', mutate)
            self.assert_failure(fixture, 'attempting_actor differs', temp/'out')
        finally: shutil.rmtree(temp)

    def test_runtime_schema_enum_is_checked(self):
        temp, fixture = self.copy_fixture()
        try:
            def mutate(d): d['documents'][0]['sections'][0]['adoption_status'] = 'unsupported-state'
            self.rewrite(fixture, 'corpus.json', mutate)
            self.assert_failure(fixture, 'runtime schema: Invalid adoption status', temp/'out')
        finally: shutil.rmtree(temp)

    def test_second_source_cannot_hide_behind_valid_first_source(self):
        temp, fixture = self.copy_fixture()
        try:
            def mutate(d): d['queries'][0]['rubric']['atomic_claims'][0]['accepted_source_ids'].append('missing-source')
            self.rewrite(fixture, 'dev.json', mutate)
            self.assert_failure(fixture, 'accepted source does not exist', temp/'out')
        finally: shutil.rmtree(temp)

    def test_current_claim_cannot_use_a_draft_section(self):
        temp, fixture = self.copy_fixture()
        try:
            def mutate(d): d['documents'][0]['sections'][0]['adoption_status'] = 'draft'
            self.rewrite(fixture, 'corpus.json', mutate)
            self.assert_failure(fixture, 'state ineligible', temp/'out')
        finally: shutil.rmtree(temp)

    def test_answerable_is_a_boolean_and_missing_fields_are_a_list(self):
        temp, fixture = self.copy_fixture()
        try:
            def mutate(d):
                d['queries'][0]['answerable'] = 'true'
                d['queries'][0]['rubric']['missing_information'] = 'none'
            self.rewrite(fixture, 'dev.json', mutate)
            self.assert_failure(fixture, 'must be booleans', temp/'out')
            result = json.loads((temp/'out/audit.json').read_text())
            self.assertTrue(any('must be lists' in f['message'] for f in result['failures']))
        finally: shutil.rmtree(temp)

if __name__ == "__main__":
    unittest.main()
