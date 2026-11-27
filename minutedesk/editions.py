"""已保存稿件的审计、发送史与重跑对比。

审计只依据 permissions 的授权范围与合成公开名录；
重跑时逐条比对决策，报告被新授权/新勘误改变的取舍，并保留发送版快照。
"""
from __future__ import annotations

import json
from pathlib import Path

from .models import Edition
from .reident import assess_edition


def audit_edition(edition: Edition, workspace, gaz, license_book) -> dict:
    """对一条已保存稿件做依据核对与重识别检查。"""
    notes = workspace["notes"]
    directory = workspace["directory"]
    findings: list[dict] = []

    # 1. basis 中的材料是否实际支持该受众引用（含选段覆盖）
    for note_id in edition.basis:
        note = notes[note_id]
        grants = [g for g in license_book.grants
                  if g.material == note_id and g.audience == edition.audience]
        if not grants:
            findings.append({
                "code": "no_license", "severity": "high",
                "message": f"依据材料 {note_id} 未授权给 {edition.audience} 受众",
                "note_id": note_id})
            continue
        if edition.audience == "public" and any(g.selector for g in grants):
            # 选段授权：稿件文字不得超出选段事实范围
            selectors = [g.selector for g in grants if g.selector]
            for selector in selectors:
                # 稿件是另一种语言时无法逐字比对，检查选段中的关键限定是否丢失
                if note.language != edition.language:
                    for must_keep in _selector_guard_terms(selector, note.language):
                        if must_keep not in edition.text and not _guard_satisfied(
                                must_keep, edition.text):
                            findings.append({
                                "code": "selector_scope", "severity": "medium",
                                "message": f"{note_id} 的选段授权限定“{must_keep}”"
                                           f"在 {edition.id} 中未体现",
                                "note_id": note_id})

    # 2. 重识别：整版文字合并评估，授权个人排除在风险外
    authorized = set()
    for grant in license_book.grants:
        if grant.audience == edition.audience:
            sub = notes[grant.material].submitted
            if directory[sub].kind == "person":
                authorized.add(sub)
    blocks = [{"text": edition.text, "language": edition.language,
               "month": None, "date": edition.time[:10],
               "authorized_persons": authorized}]
    risks = assess_edition(blocks, gaz, directory)
    for risk in risks:
        findings.append({
            "code": "reidentification", "severity": risk["level"],
            "message": risk["reason"], "scope": risk["scope"],
            "matched_persons": risk["matched_persons"],
            "evidence_text": risk["evidence_text"]})

    # 3. 限定漂移：已确认安排在稿件中丢了“待确认日期/仅汇总指标”等限定
    for note_id in edition.basis:
        note = notes[note_id]
        for term in _qualifier_terms(note.text, note.language):
            if not _guard_satisfied(term, edition.text):
                findings.append({
                    "code": "qualifier_drift", "severity": "medium",
                    "message": f"依据 {note_id} 原话限定“{term}”在 {edition.id} 中缺失或弱化",
                    "note_id": note_id})

    return {
        "edition_id": edition.id, "audience": edition.audience,
        "phase": edition.phase, "passed": not any(
            f["severity"] == "high" for f in findings),
        "findings": findings,
    }


def _selector_guard_terms(selector: str, language: str) -> list[str]:
    guards = []
    if language == "zh":
        if "仅" in selector:
            guards.append("仅")
        if "原则上" in selector or "待" in selector:
            guards.append("待确认")
    else:
        if " only" in selector.lower():
            guards.append("only")
        if "target" in selector.lower() or "no exact date" in selector.lower():
            guards.append("subject to confirmation")
    return guards


def _qualifier_terms(text: str, language: str) -> list[str]:
    terms = []
    if language == "zh":
        if "仅" in text:
            terms.append("仅")
        if "待" in text:
            terms.append("待确认")
    else:
        if " only" in text.lower():
            terms.append("only")
        if "no exact date" in text.lower() or "target" in text.lower():
            terms.append("subject to confirmation")
    return terms


def _guard_satisfied(term: str, edition_text: str) -> bool:
    table = {
        "仅": ["仅", "only"],
        "待确认": ["待", "subject to confirmation", "target"],
        "only": ["only", "仅"],
        "subject to confirmation": [
            "subject to confirmation", "target", "待", "no exact date"],
    }
    return any(marker in edition_text for marker in table.get(term, [term]))


# ----------------------------------------------------------------------
def audit_all(workspace, gaz, license_book) -> list[dict]:
    return [audit_edition(edition, workspace, gaz, license_book)
            for edition in workspace["editions"].values()]


def save_run(out_dir: str | Path, fingerprint: str,
             edition_results: list[dict], audits: list[dict]) -> Path:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    run_dir = out / "runs" / fingerprint[:12]
    run_dir.mkdir(parents=True, exist_ok=True)
    payload = {"fingerprint": fingerprint, "editions": edition_results,
               "audits": audits}
    path = run_dir / "result.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                    encoding="utf-8")
    return path


def record_sent_edition(out_dir: str | Path, edition_id: str,
                        edition: Edition, audit: dict) -> Path:
    out = Path(out_dir) / "sent"
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{edition_id}.json"
    path.write_text(json.dumps(
        {"edition_id": edition_id, "time": edition.time,
         "audience": edition.audience, "language": edition.language,
         "text": edition.text, "basis": edition.basis, "audit": audit},
        ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def diff_runs(previous: dict, current: dict) -> dict:
    """比较两次出稿：哪些句子的取舍、依据或风险发生了变化。"""
    def index(run: dict) -> dict:
        table = {}
        for edition in run["editions"]:
            for decision in edition["decisions"]:
                table[(edition["audience"], edition["language"],
                       decision["item"])] = decision
        return table

    old, new = index(previous), index(current)
    changed, added, removed = [], [], []
    for key in sorted(set(old) | set(new)):
        if key not in old:
            added.append(new[key])
        elif key not in new:
            removed.append(old[key])
        elif old[key] != new[key]:
            changed.append({"item": key, "before": old[key], "after": new[key]})
    return {"changed": changed, "added": added, "removed": removed}


def load_run(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))
