"""重识别评估（纯函数，不联网、不读项目资料以外的任何来源）。

评估依据仅限：
1. 合成公开名录（directory）及其姓名、别名、机构、职务、任期、航线；
2. 同一版本将同时呈现的文字（传入的句子列表）。

单句直接称谓与跨句共指组合分别检查：删除姓名后，罕见职务 + 机构 + 航线
（可再叠加任/前任时态）是否仍把读者指向唯一的未授权个人。
"""
from __future__ import annotations

import re

from .models import DirectoryEntry


def _month_of(date: str) -> str:
    return date[:7]


def candidate_persons(directory: dict[str, DirectoryEntry], month: str | None,
                      org: str | None, role: str | None,
                      routes: set[str], tense: str | None) -> list[DirectoryEntry]:
    if not role:
        # 仅凭机构/航线不能把文字指向具体个人，避免把机构事项误判成个人风险
        return []
    results = []
    for entry in directory.values():
        if entry.kind != "person":
            continue
        if entry.role != role:
            continue
        if org and entry.organization != org:
            continue
        if routes:
            # 多航线组合要求全部命中其职责，单航线用交集，
            # 让“罕见职务+机构+负责的多条航线”能收窄到唯一人
            if len(routes) > 1 and not routes.issubset(set(entry.routes)):
                continue
            if len(routes) == 1 and not routes.intersection(entry.routes):
                continue
        if month:
            if tense == "former" and not entry.period[1] < month:
                continue
            if tense == "current" and not entry.period[0] <= month <= entry.period[1]:
                continue
        results.append(entry)
    return results


def _level(persons: list[DirectoryEntry], named: bool) -> tuple[str, str]:
    if len(persons) == 1:
        who = persons[0]
        if named:
            return "high", f"直接称谓或组合唯一指向 {who.name}（{who.organization}/{who.role}）"
        return "high", (f"即使删去姓名，{who.organization}的{who.role}与其航线组合"
                        f"仍唯一指向 {who.name}")
    if len(persons) > 1:
        return "medium", f"组合指向 {len(persons)} 名同职务者：{', '.join(p.id for p in persons)}"
    return "low", "未能在公开名录中定位到具体个人"


def assess_text(text: str, language: str, gazetteer,
                directory: dict[str, DirectoryEntry],
                month: str | None, date: str | None) -> dict:
    """评估一段文字（可以是多句）单独看时的重识别风险。"""
    surfaces = gazetteer.scan(text)
    names = [s for s in surfaces if s.kind == "alias"]
    role_surfaces = [s for s in surfaces if s.kind == "role"]
    org_surfaces = [s for s in surfaces if s.kind == "org"]
    route_surfaces = {s.canonical for s in surfaces if s.kind == "route"}
    tense_surfaces = {s.canonical for s in surfaces if s.kind == "tense"}
    tense = "former" if "former" in tense_surfaces else (
        "current" if "current" in tense_surfaces else None)

    risks = []
    for name in names:
        ids = gazetteer.person_index().get(name.text.lower(), [])
        persons = [directory[i] for i in ids if i in directory]
        level, reason = _level(persons, named=True)
        risks.append({"level": level, "reason": reason,
                      "matched": [p.id for p in persons], "surface": name.text})

    if role_surfaces:
        org = org_surfaces[0].canonical if org_surfaces else None
        role = role_surfaces[0].canonical
        persons = candidate_persons(directory, month or _month_of(date or "2026-12"),
                                    org, role, route_surfaces, tense)
        level, reason = _level(persons, named=bool(names))
        risks.append({"level": level, "reason": reason,
                      "matched": [p.id for p in persons],
                      "surface": role_surfaces[0].text})

    high = [r for r in risks if r["level"] == "high"]
    return {
        "text": text,
        "level": "high" if high else ("medium" if risks else "low"),
        "risks": risks,
        "routes": sorted(route_surfaces),
        "orgs": sorted({s.canonical for s in org_surfaces}),
        "tense": tense,
        "named": bool(names),
    }


def assess_edition(blocks: list[dict], gazetteer,
                   directory: dict[str, DirectoryEntry]) -> list[dict]:
    """评估整个版本：先逐块，再按跨句共指链组合。

    blocks: [{"text", "language", "month", "date", "authorized_persons"}]
    authorized_persons 中的 id 已获该受众授权，不计为未授权指向。
    返回的每条风险对应一条“公开文字合在一起”的具体组合。
    """
    from .extract import split_sentences
    from .models import Note

    findings = []
    chain_orgs: set[str] = set()
    chain_tense: set[str] = set()
    chain_role: str | None = None
    chain_surfaces: list[str] = []
    chain_spans_text: list[str] = []
    # 逐句收集与角色共现的航线组合，跨句取交集以模拟读者的逐步收窄
    per_sentence_route_sets: list[set[str]] = []

    expanded: list[dict] = []
    for block in blocks:
        pseudo = Note(id="_audit", date=block.get("date") or "2026-11-01",
                      session="", language=block["language"],
                      submitted="", text=block["text"])
        for sentence in split_sentences(pseudo, gazetteer.cfg.get("abbreviations")):
            expanded.append({
                "text": sentence.text, "language": block["language"],
                "month": block.get("month"), "date": block.get("date"),
                "authorized_persons": block.get("authorized_persons", set())})

    for block in expanded:
        single = assess_text(block["text"], block["language"], gazetteer,
                             directory, block.get("month"), block.get("date"))
        for risk in single["risks"]:
            unauthorized = [p for p in risk["matched"]
                            if p not in block.get("authorized_persons", set())]
            if not unauthorized:
                continue
            level, reason = _level([directory[p] for p in unauthorized],
                                   named=single["named"])
            findings.append({
                "scope": "sentence",
                "level": level,
                "reason": reason,
                "matched_persons": unauthorized,
                "evidence_text": block["text"],
            })

        surfaces = gazetteer.scan(block["text"])
        sentence_routes = {s.canonical for s in surfaces if s.kind == "route"}
        role_here = next((s.canonical for s in surfaces if s.kind == "role"), None)
        for surface in surfaces:
            if surface.kind == "org":
                chain_orgs.add(surface.canonical)
            elif surface.kind == "tense":
                chain_tense.add(surface.canonical)
            elif surface.kind == "role":
                chain_role = surface.canonical
            if surface.kind in {"role", "org", "route", "tense", "anaphora"}:
                chain_surfaces.append(surface.text)
        if role_here or any(s.kind == "anaphora" for s in surfaces):
            per_sentence_route_sets.append(sentence_routes)
        if surfaces:
            chain_spans_text.append(block["text"])

    # 跨句组合：同一版本中机构 + 职务 + 航线（含代词承接）是否收窄到唯一人。
    # 必须在版本文字中实际出现职务称谓；纯机构/航线表述不推断个人。
    if chain_role and per_sentence_route_sets:
        tense = next(iter(chain_tense)) if chain_tense else None
        org = next(iter(chain_orgs)) if len(chain_orgs) == 1 else None
        # 每句的航线组合分别匹配，再取交集：读者正是靠多句信息逐步锁定个人
        candidate_ids: set[str] | None = None
        for routes in per_sentence_route_sets:
            if not routes:
                continue
            persons = candidate_persons(directory, "2026-11", org, chain_role,
                                        routes, tense)
            ids = {p.id for p in persons}
            candidate_ids = ids if candidate_ids is None else candidate_ids & ids
        if candidate_ids is None:
            candidate_ids = set()
        authorized = set().union(*[set(b.get("authorized_persons", set()))
                                   for b in blocks]) if blocks else set()
        unauthorized = sorted(candidate_ids - authorized)
        if unauthorized:
            level, reason = _level([directory[p] for p in unauthorized], named=False)
            findings.append({
                "scope": "cross_sentence",
                "level": level,
                "reason": f"跨句组合（{ '、'.join(chain_surfaces) }）" + reason,
                "matched_persons": unauthorized,
                "evidence_text": " || ".join(chain_spans_text),
            })
    return findings
