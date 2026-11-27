"""工具各模块的行为测试，使用项目自带的合成资料。"""
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from minutedesk.arrange import align, is_key  # noqa: E402
from minutedesk.compose import Composer
from minutedesk.editions import audit_edition, diff_runs
from minutedesk.extract import extract_all, split_sentences
from minutedesk.gazetteer import Gazetteer
from minutedesk.identity import IdentityResolver, in_period, is_former
from minutedesk.licensing import LicenseBook
from minutedesk.loader import MaterialError, load_workspace
from minutedesk.pipeline import run_pipeline, write_outputs
from minutedesk.reident import assess_edition, assess_text, candidate_persons

ROOT = Path(__file__).resolve().parents[1]
MATERIALS = ROOT / "materials"


class PipelineSetup(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ws = load_workspace(MATERIALS)
        cls.gaz = Gazetteer(cls.ws["directory"])
        cls.resolver = IdentityResolver(cls.ws["directory"], cls.gaz)
        cls.lic = LicenseBook(
            cls.ws["notes"], cls.ws["permissions"],
            cls.gaz.cfg.get("abbreviations"))
        cls.statements = extract_all(cls.ws["notes"], cls.gaz, cls.resolver)
        cls.arrangements = align(cls.statements)
        cls.composer = Composer(cls.ws, cls.arrangements, cls.gaz, cls.lic)

    def arrangement(self, routes, activity=None, month=None):
        for arrangement in self.arrangements:
            if set(arrangement.routes) == set(routes) and (
                    activity is None or arrangement.activity == activity) and (
                    month is None or arrangement.month == month):
                return arrangement
        self.fail(f"未找到 routes={routes} activity={activity} 的安排")


class LoaderTest(PipelineSetup):
    def test_directory_identifies_body_vs_person(self):
        self.assertEqual(self.ws["directory"]["d1"].kind, "body")
        self.assertEqual(self.ws["directory"]["p1"].kind, "person")

    def test_bad_selector_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            shutil.copytree(MATERIALS, Path(tmp) / "m")
            target = Path(tmp) / "m" / "permissions.jsonl"
            rows = [json.loads(line) for line in target.read_text(
                encoding="utf-8").splitlines()]
            rows[0]["selector"] = "资料里没有的选段"
            target.write_text("\n".join(json.dumps(r, ensure_ascii=False)
                                        for r in rows), encoding="utf-8")
            with self.assertRaises(MaterialError):
                load_workspace(Path(tmp) / "m")

    def test_dangling_reference_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            shutil.copytree(MATERIALS, Path(tmp) / "m")
            target = Path(tmp) / "m" / "notes.jsonl"
            rows = [json.loads(line) for line in target.read_text(
                encoding="utf-8").splitlines()]
            rows[0]["submitted"] = "nope"
            target.write_text("\n".join(json.dumps(r, ensure_ascii=False)
                                        for r in rows), encoding="utf-8")
            with self.assertRaises(MaterialError):
                load_workspace(Path(tmp) / "m")


class IdentityTest(PipelineSetup):
    def test_alias_resolves_to_same_person(self):
        note = self.ws["notes"]["s2"]
        sentence = split_sentences(note, self.gaz.cfg["abbreviations"])[0]
        mentions = self.resolver.resolve_mentions(note, self.gaz.scan(sentence.text))
        alias = next(m for m in mentions if m.surface == "P. Xu")
        self.assertEqual(alias.resolved, "p1")
        self.assertEqual(alias.status, "exact")

    def test_former_role_uses_tense_word_and_period(self):
        note = self.ws["notes"]["s5"]
        sentence = split_sentences(note, self.gaz.cfg["abbreviations"])[0]
        mentions = self.resolver.resolve_mentions(note, self.gaz.scan(sentence.text))
        role = next(m for m in mentions if m.kind == "person" and m.surface == "coordinator")
        self.assertEqual(role.resolved, "p2")  # 历任者，不是现任 p1/p3
        speaker, status = self.resolver.resolve_speaker(note, sentence.text, mentions)
        self.assertEqual((speaker, status), ("p2", "former"))

    def test_same_role_different_holders_disambiguated_by_period(self):
        self.assertTrue(in_period(self.ws["directory"]["p1"], "2026-11"))
        self.assertTrue(is_former(self.ws["directory"]["p2"], "2026-11"))
        self.assertFalse(in_period(self.ws["directory"]["p2"], "2026-11"))

    def test_ambiguous_role_without_org_or_tense(self):
        note = self.ws["notes"]["s1"]
        sentence = split_sentences(note, self.gaz.cfg["abbreviations"])[0]
        mentions = self.resolver.resolve_mentions(note, self.gaz.scan(sentence.text))
        role = next(m for m in mentions if m.surface == "联运协调员")
        self.assertEqual(role.status, "ambiguous")
        self.assertEqual(set(role.candidates), {"p1", "p3"})

    def test_reported_person_kept_in_chain_not_mistaken_for_speaker(self):
        s2 = next(s for s in self.statements if s.note_id == "s2" and s.sentence_index == 0)
        self.assertEqual(s2.speaker, "p3")       # 材料提交方是说话人
        self.assertIn("p1", s2.reported)         # P. Xu 是被转述者

    def test_body_confirmation_does_not_land_on_person(self):
        s4 = next(s for s in self.statements if s.note_id == "s4" and s.sentence_index == 0)
        self.assertEqual(s4.speaker, "d1")
        self.assertEqual(s4.speaker_status, "body")


class ExtractionTest(PipelineSetup):
    def test_abbreviation_does_not_split_sentence(self):
        note = self.ws["notes"]["s2"]
        sentences = split_sentences(note, self.gaz.cfg["abbreviations"])
        self.assertEqual(len(sentences), 2)
        self.assertTrue(sentences[0].text.startswith("P. Xu suggested"))

    def test_speech_act_kinds(self):
        by_id = {(s.note_id, s.sentence_index): s for s in self.statements}
        self.assertEqual(by_id[("s1", 1)].primary_kind, "proposal")
        self.assertEqual(by_id[("s4", 0)].primary_kind, "confirmed")
        self.assertEqual(by_id[("s6", 0)].primary_kind, "correction")
        self.assertEqual(by_id[("s4", 1)].primary_kind, "caveat")
        self.assertEqual(by_id[("s6", 0)].correction_target, "s4")

    def test_qualifiers_preserved(self):
        s3 = next(s for s in self.statements if s.note_id == "s3" and s.sentence_index == 1)
        self.assertIn("scope_only", s3.qualifiers)
        self.assertIn("target_not_firm", s3.qualifiers)
        s6 = next(s for s in self.statements if s.note_id == "s6" and s.sentence_index == 0)
        self.assertIn("target_not_firm", s6.qualifiers)

    def test_relative_month_resolved_but_flagged(self):
        s7 = next(s for s in self.statements if s.note_id == "s7")
        self.assertEqual(s7.month, "2026-12")
        self.assertFalse(s7.month_resolved)

    def test_warehouse_route_guard(self):
        # 银湾仓 不应被识别成银湾线
        s7 = next(s for s in self.statements if s.note_id == "s7" and s.sentence_index == 0)
        self.assertNotIn("银湾线", s7.routes)


class AlignmentTest(PipelineSetup):
    def test_cross_lingual_alignment_of_confirmed_arrangement(self):
        arrangement = self.arrangement({"石岭线", "银湾线"}, "data_exchange", "2026-03")
        self.assertEqual(arrangement.languages, {"zh", "en"})
        self.assertTrue(arrangement.is_confirmed)
        note_ids = {s.note_id for s in arrangement.statements}
        self.assertIn("s4", note_ids)
        self.assertIn("s8", note_ids)

    def test_correction_chain_merges_into_target(self):
        arrangement = self.arrangement({"石岭线", "银湾线"}, "data_exchange", "2026-03")
        note_ids = {s.note_id for s in arrangement.statements}
        self.assertIn("s6", note_ids)  # Correction to s4 归并

    def test_different_arrangements_not_merged_on_similar_number(self):
        february = self.arrangement({"北环货线"}, "coverage_window", "2026-02")
        march = self.arrangement({"石岭线", "银湾线"}, "data_exchange", "2026-03")
        self.assertNotEqual(february.id, march.id)
        # 但编辑应能看到它们为何被分开
        linked = {w["other"] for w in february.weak_links}
        self.assertIn(march.id, linked)

    def test_handover_kept_separate_from_data_exchange(self):
        handover = self.arrangement(set(), "handover", "2026-12")
        exchange = self.arrangement({"石岭线", "银湾线"}, "data_exchange", "2026-03")
        self.assertNotEqual(handover.id, exchange.id)
        self.assertTrue(all(not s.is_confirmed for s in handover.statements))

    def test_non_key_sentence_does_not_merge_unrelated_arrangements(self):
        # s1 的“银湾线也是我负责的”不得把银湾线并进北环安排
        february = self.arrangement({"北环货线"}, "coverage_window", "2026-02")
        self.assertEqual(february.routes, frozenset({"北环货线"}))


class LicensingTest(PipelineSetup):
    def test_full_text_vs_selector_coverage(self):
        s1_proposal = next(s for s in self.statements
                          if s.note_id == "s1" and s.sentence_index == 1)
        s3_exchange = next(s for s in self.statements
                           if s.note_id == "s3" and s.sentence_index == 1)
        self.assertTrue(self.lic.is_licensed(s1_proposal, "session"))
        self.assertFalse(self.lic.is_licensed(s1_proposal, "public"))
        self.assertTrue(self.lic.is_licensed(s3_exchange, "public"))
        grants = self.lic.statement_grants(s3_exchange, "public")
        self.assertEqual([g.permission_id for g in grants], ["p03"])

    def test_selector_does_not_cover_other_sentence(self):
        s3_north = next(s for s in self.statements
                        if s.note_id == "s3" and s.sentence_index == 0)
        self.assertFalse(self.lic.is_licensed(s3_north, "public"))
        self.assertFalse(self.lic.is_licensed(s3_north, "session"))

    def test_new_permission_scoped_to_listed_material(self):
        # s6 只有会内授权，不会因为 s4 公开而自动公开
        s6 = next(s for s in self.statements if s.note_id == "s6" and s.sentence_index == 0)
        self.assertTrue(self.lic.is_licensed(s6, "session"))
        self.assertFalse(self.lic.is_licensed(s6, "public"))

    def test_selector_license_for_one_org_note_does_not_spread(self):
        # p03 只许可 p4 提交的 s3 中的一段；同机构语境的其他材料不受影响
        s1 = next(s for s in self.statements
                  if s.note_id == "s1" and s.sentence_index == 1)
        s3 = next(s for s in self.statements
                  if s.note_id == "s3" and s.sentence_index == 1)
        self.assertTrue(self.lic.is_licensed(s3, "public"))
        self.assertFalse(self.lic.is_licensed(s1, "public"))
        # 且 s3 的授权只覆盖选段所在句，不覆盖同材料另一句
        s3_other = next(s for s in self.statements
                        if s.note_id == "s3" and s.sentence_index == 0)
        self.assertFalse(self.lic.is_licensed(s3_other, "public"))


class ReidentificationTest(PipelineSetup):
    def test_named_surface_is_high_risk(self):
        result = assess_text("许沛建议二月增开北环货线窗口。", "zh", self.gaz,
                             self.ws["directory"], "2026-11", "2026-11-21")
        self.assertEqual(result["level"], "high")
        self.assertEqual(result["risks"][0]["matched"], ["p1"])

    def test_role_org_route_combination_identifies_holder_without_name(self):
        text = "辰谷现任联运协调员负责银湾线，该协调员也参与北环货线。"
        result = assess_text(text, "zh", self.gaz, self.ws["directory"],
                             "2026-11", "2026-11-21")
        self.assertEqual(result["level"], "high")
        self.assertEqual(result["risks"][-1]["matched"], ["p1"])

    def test_former_holder_distinguished(self):
        text = "The former coordinator of the North Loop described a test."
        result = assess_text(text, "en", self.gaz, self.ws["directory"],
                             "2026-11", "2026-11-22")
        self.assertEqual(result["risks"][-1]["matched"], ["p2"])

    def test_body_wording_without_role_has_no_person_risk(self):
        text = ("The working group confirmed a March exchange of aggregate "
                "metrics only, for Silver Bay and Shiling.")
        result = assess_text(text, "en", self.gaz, self.ws["directory"],
                             "2026-03", "2026-11-22")
        self.assertEqual(result["level"], "low")

    def test_cross_sentence_combination_flagged(self):
        blocks = [
            {"text": "辰谷现任联运协调员建议二月增加陪同窗口。", "language": "zh",
             "month": "2026-11", "date": "2026-11-22",
             "authorized_persons": set()},
            {"text": "该协调员也负责银湾线。", "language": "zh",
             "month": "2026-11", "date": "2026-11-22",
             "authorized_persons": set()},
        ]
        findings = assess_edition(blocks, self.gaz, self.ws["directory"])
        self.assertTrue(any(f["scope"] == "cross_sentence" for f in findings))
        self.assertIn("p1", findings[-1]["matched_persons"])

    def test_authorized_person_excluded_from_risk(self):
        blocks = [
            {"text": "许沛建议二月增加北环货线陪同窗口。", "language": "zh",
             "month": "2026-11", "date": "2026-11-22",
             "authorized_persons": {"p1"}},
        ]
        findings = assess_edition(blocks, self.gaz, self.ws["directory"])
        self.assertEqual(findings, [])

    def test_route_alone_does_not_guess_person(self):
        self.assertEqual(candidate_persons(self.ws["directory"], "2026-11",
                                           None, None, {"北环货线"}, None), [])


class CompositionTest(PipelineSetup):
    def test_public_edition_keeps_confirmed_fact_with_latest_qualifier(self):
        result = self.composer.build("public", "zh")
        self.assertEqual(len(result.blocks), 1)
        block = result.blocks[0]
        self.assertEqual(block.status, "confirmed")
        self.assertIn("三月", block.text)
        self.assertIn("待各方确认", block.text)  # 来自 s6 勘误的最新限定
        self.assertEqual(set(block.permissions), {"p04", "p07"})

    def test_public_edition_has_no_personal_attribution(self):
        for language in ("zh", "en"):
            result = self.composer.build("public", language)
            rendered = result.render()
            for name in ("许沛", "许飞", "云珂", "张栗", "P. Xu", "F. Xu",
                         "K. Yun", "Li Zhang", "Pei Xu"):
                self.assertNotIn(name, rendered)

    def test_proposal_vs_confirmation_still_distinguishable(self):
        result = self.composer.build("public", "zh")
        # 确认事实保留；未授权的个人提议不进正文，只能在核对区找到
        review_texts = " ".join(b.text for b in result.review_only)
        self.assertIn("建议二月每周增开一轮", review_texts)
        self.assertNotIn("建议二月每周增开一轮", result.render())

    def test_unlicensed_high_risk_statement_goes_review_only(self):
        result = self.composer.build("public", "en")
        sources = {s for b in result.review_only for s in b.source_statements}
        self.assertIn("s2#0", sources)
        decision = next(d for d in result.decisions if d["item"].endswith("s2#0"))
        self.assertEqual(decision["decision"], "review_only")

    def test_session_edition_keeps_speakers_and_original_wording(self):
        result = self.composer.build("session", "zh")
        rendered = result.render()
        self.assertIn("许飞 (former)", rendered)
        self.assertIn("货运协调组", rendered)
        self.assertIn("test suggestion", rendered)  # 原话保留（英文材料）

    def test_every_decision_has_evidence(self):
        for audience in ("public", "session"):
            result = self.composer.build(audience, "zh")
            for decision in result.decisions:
                self.assertTrue(decision["evidence"], decision)

    def test_internal_records_remain_reviewable_without_license(self):
        result = self.composer.build("session", "en")
        review_sources = {s for b in result.review_only
                          for s in b.source_statements}
        # s3#0（北环另行议定）无任何受众授权，但仍在审阅区可见
        self.assertIn("s3#0", review_sources)
        # 未授权材料不会进入核对稿正文
        body_sources = {s for b in result.blocks for s in b.source_statements}
        self.assertNotIn("s3#0", body_sources)


class EditionAuditTest(PipelineSetup):
    def test_sent_edition_v1_passes_but_flags_qualifier_if_drifted(self):
        audit = audit_edition(self.ws["editions"]["v1"], self.ws, self.gaz, self.lic)
        self.assertTrue(audit["passed"])

    def test_draft_v2_fails_on_license_and_reidentification(self):
        audit = audit_edition(self.ws["editions"]["v2"], self.ws, self.gaz, self.lic)
        self.assertFalse(audit["passed"])
        codes = {f["code"] for f in audit["findings"]}
        self.assertIn("no_license", codes)
        self.assertIn("reidentification", codes)
        self.assertIn("qualifier_drift", codes)

    def test_draft_v3_session_passes(self):
        audit = audit_edition(self.ws["editions"]["v3"], self.ws, self.gaz, self.lic)
        self.assertTrue(audit["passed"])

    def test_audit_finds_cross_sentence_combo_in_v2(self):
        audit = audit_edition(self.ws["editions"]["v2"], self.ws, self.gaz, self.lic)
        scopes = {f.get("scope") for f in audit["findings"]
                  if f["code"] == "reidentification"}
        self.assertIn("cross_sentence", scopes)


class RerunAndHistoryTest(unittest.TestCase):
    def test_fingerprint_changes_when_material_changes_and_diff_reports_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            m1 = Path(tmp) / "m1"
            shutil.copytree(MATERIALS, m1)
            first = run_pipeline(m1)
            out1 = Path(tmp) / "out"
            write_outputs(first, out1)
            run_path = out1 / "runs" / first["fingerprint"][:12] / "result.json"

            # 新增一条公开授权：s1 的提议可以对外
            perm = m1 / "permissions.jsonl"
            rows = [json.loads(line) for line in perm.read_text(
                encoding="utf-8").splitlines()]
            rows.append({
                "id": "p08", "time": "2026-11-25T10:00", "material": "s1",
                "audiences": ["public", "session"], "selector": "",
                "note": "追加公开许可"})
            perm.write_text("\n".join(json.dumps(r, ensure_ascii=False)
                                      for r in rows), encoding="utf-8")

            second = run_pipeline(m1)
            self.assertNotEqual(first["fingerprint"], second["fingerprint"])
            diff = diff_runs({"editions": first["editions"]},
                             {"editions": second["editions"]})
            items = {d["item"] for d in diff["changed"]}
            self.assertTrue(
                any(item[0] == "public" and "s1#1" in item[2] for item in items))
            # 且能看出取舍变化方向与决定它的许可
            changed = next(d for d in diff["changed"]
                           if d["item"][0] == "public"
                           and "s1#1" in d["item"][2])
            self.assertEqual(changed["before"]["decision"], "review_only")
            self.assertEqual(changed["after"]["decision"], "include")

    def test_sent_snapshot_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            pipeline = run_pipeline(MATERIALS)
            out = Path(tmp) / "out"
            write_outputs(pipeline, out)
            snapshot = out / "sent" / "v1.json"
            self.assertTrue(snapshot.exists())
            payload = json.loads(snapshot.read_text(encoding="utf-8"))
            self.assertEqual(payload["edition_id"], "v1")
            self.assertIn("audit", payload)


if __name__ == "__main__":
    unittest.main()
