"""人物与机构主体解析。

区分三类易混情形：
1. 同一人的别名（名录 aliases / 同一 id）；
2. 担任过同一职务的不同人（role 相同但 period 不同，按时段与航线过滤）；
3. 仅以联合代表团等机构名义确认的事项（kind=body，不落到个人）。
"""
from __future__ import annotations

import re

from .models import DirectoryEntry, Mention, Note, Surface


def _month_of(date: str) -> str:
    return date[:7]


def in_period(entry: DirectoryEntry, month: str) -> bool:
    return entry.period[0] <= month <= entry.period[1]


def is_former(entry: DirectoryEntry, month: str) -> bool:
    return entry.period[1] < month


class IdentityResolver:
    def __init__(self, directory: dict[str, DirectoryEntry], gazetteer):
        self.directory = directory
        self.gaz = gazetteer
        self.person_alias = gazetteer.person_index()
        self.body_by_name = {e.name: e.id for e in directory.values() if e.kind == "body"}

    # ------------------------------------------------------------------
    def resolve_mentions(self, note: Note, surfaces: list[Surface]) -> list[Mention]:
        mentions: list[Mention] = []
        last_person: Mention | None = None
        note_month = _month_of(note.date)

        for surface in surfaces:
            if surface.kind == "body" and surface.canonical in self.directory:
                mention = Mention(surface.text, "body", [surface.canonical],
                                  surface.canonical, "body", surface.start, surface.end)
                mentions.append(mention)
                continue
            if surface.kind == "body_name":
                body_id = self.body_by_name.get(surface.canonical)
                mentions.append(Mention(
                    surface.text, "body", [body_id] if body_id else [],
                    body_id, "body" if body_id else "unknown",
                    surface.start, surface.end))
                continue
            if surface.kind == "alias":
                candidates = self.person_alias.get(surface.text.lower(), [])
                if not candidates and re.fullmatch(r"[A-Z]\.", surface.text):
                    # 首字母转写（如 P.）：同材料提交方同姓时作为可追溯的弱指称
                    initial = surface.text[0]
                    candidates = [e.id for e in self.directory.values()
                                  if e.kind == "person"
                                  and any(a.startswith(initial + ".")
                                          for a in e.aliases)]
                    status = "anaphora"
                else:
                    status = "exact" if len(candidates) == 1 else (
                        "ambiguous" if candidates else "unknown")
                mention = Mention(surface.text, "person", candidates,
                                  candidates[0] if len(candidates) == 1 else None,
                                  status, surface.start, surface.end)
                mentions.append(mention)
                last_person = mention
                continue
            if surface.kind == "anaphora":
                candidates = last_person.candidates if last_person else []
                mentions.append(Mention(
                    surface.text, "person", list(candidates),
                    candidates[0] if len(candidates) == 1 else None,
                    "anaphora", surface.start, surface.end))
                continue
            if surface.kind == "role":
                mention = self._resolve_role(surface, surfaces, note_month)
                mentions.append(mention)
                if mention.status in {"resolved", "exact"}:
                    last_person = mention
                continue
        return mentions

    def _resolve_role(self, role_surface: Surface, all_surfaces: list[Surface],
                      month: str) -> Mention:
        orgs = {s.canonical for s in all_surfaces if s.kind == "org"}
        routes = {s.canonical for s in all_surfaces if s.kind == "route"}
        tenses = {s.canonical for s in all_surfaces if s.kind == "tense"}
        candidates: list[str] = []
        for entry in self.directory.values():
            if entry.kind != "person" or entry.role != role_surface.canonical:
                continue
            if orgs and entry.organization not in orgs:
                continue
            if routes and not routes.intersection(entry.routes):
                continue
            if "former" in tenses and not is_former(entry, month):
                continue
            if "current" in tenses and not in_period(entry, month):
                continue
            candidates.append(entry.id)
        if len(candidates) == 1:
            status = "resolved"
        elif candidates:
            status = "ambiguous"
        else:
            status = "unknown"
        return Mention(role_surface.text, "person", candidates,
                       candidates[0] if status == "resolved" else None,
                       status, role_surface.start, role_surface.end)

    # ------------------------------------------------------------------
    def resolve_speaker(self, note: Note, sentence_text: str,
                        mentions: list[Mention]) -> tuple[str | None, str]:
        """确定本句说话主体。默认是材料提交方；引语归因以句内称谓为准。

        现任/前任以句内时态词为准（former/current/前任/现任），
        不按名录任期事后改判——同职务历任者正是要保留的区分。
        """
        attribution_verbs = self.gaz.cfg["attribution_verbs"]
        person_mentions = [m for m in mentions if m.kind == "person"]
        body_mentions = [m for m in mentions if m.kind == "body" and m.resolved]
        tenses = {s.canonical for s in self.gaz.scan(sentence_text)
                  if s.kind == "tense"}

        def has_attribution(mention: Mention) -> bool:
            head = sentence_text[: mention.start].lower()
            if any(verb.lower() in head for verb in attribution_verbs):
                return True
            # 句首称谓后直接跟转述动词（P. Xu suggested… / 张三说…）
            tail = sentence_text[mention.end:mention.end + 12].lower()
            return any(verb.lower() in tail for verb in attribution_verbs)

        attributed = [m for m in person_mentions if has_attribution(m)]
        attributed_bodies = [m for m in body_mentions if has_attribution(m)]

        # 句中称谓带转述动词（P. Xu suggested…）：该称谓是被转述者，
        # 说话人仍是材料提交方；转述链通过 mentions/reported 保留。
        if attributed and note.submitted in self.directory:
            submitter = self.directory[note.submitted]
            if submitter.kind == "person" and all(
                    m.resolved != note.submitted for m in attributed):
                tense = "former" if "former" in tenses else (
                    "current" if "current" in tenses else "submitter")
                return note.submitted, tense
        if attributed_bodies and note.submitted in self.directory:
            submitter = self.directory[note.submitted]
            if submitter.kind == "person":
                return note.submitted, "submitter"

        for mention in body_mentions:
            if not person_mentions:
                return mention.resolved, "body"
        for mention in person_mentions:
            if mention.resolved:
                status = "former" if "former" in tenses else (
                    "current" if "current" in tenses else "submitter")
                return mention.resolved, status
        if body_mentions:
            return body_mentions[0].resolved, "body"
        return note.submitted, "submitter"
