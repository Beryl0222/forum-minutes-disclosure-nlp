"""授权台账：材料 × 受众 × 原文选段。

选段授权只覆盖该原文的对应区间；新授权只作用于所列材料和受众，
同一机构只勘误一份译稿或只许可某段时，不会扩大到其他材料。
"""
from __future__ import annotations

from dataclasses import dataclass

from .models import Note, Permission, Statement
from .extract import split_sentences


@dataclass
class Grant:
    permission_id: str
    material: str
    audience: str
    start: int
    end: int  # 半开区间；全文授权为 (0, len(text))
    selector: str
    note: str


def sentence_bounds(notes: dict[str, Note], abbreviations: list[str] | None = None) -> dict[str, list[tuple[int, int]]]:
    """预计算每条材料中各句子在原文的绝对字符区间。"""
    return {
        note_id: [(s.start, s.end) for s in split_sentences(note, abbreviations)]
        for note_id, note in notes.items()
    }


class LicenseBook:
    def __init__(self, notes: dict[str, Note],
                 permissions: dict[str, Permission],
                 abbreviations: list[str] | None = None):
        self.notes = notes
        self.bounds = sentence_bounds(notes, abbreviations)
        self.grants: list[Grant] = []
        for perm in permissions.values():
            text = notes[perm.material].text
            if perm.selector:
                start = text.index(perm.selector)
                end = start + len(perm.selector)
            else:
                start, end = 0, len(text)
            for audience in perm.audiences:
                self.grants.append(Grant(
                    perm.id, perm.material, audience, start, end,
                    perm.selector, perm.note))

    def covering(self, note_id: str, audience: str, start: int, end: int) -> list[Grant]:
        return [g for g in self.grants
                if g.material == note_id and g.audience == audience
                and g.start <= start and end <= g.end]

    def statement_grants(self, statement: Statement, audience: str) -> list[Grant]:
        """一句话在指定受众下的全部覆盖授权（按句子在原文中的字符区间）。"""
        start, end = self.bounds[statement.note_id][statement.sentence_index]
        return self.covering(statement.note_id, audience, start, end)

    def is_licensed(self, statement: Statement, audience: str) -> bool:
        return bool(self.statement_grants(statement, audience))

    def material_audiences(self, note_id: str) -> set[str]:
        return {g.audience for g in self.grants if g.material == note_id}

    def explain(self, statement: Statement, audience: str) -> dict:
        grants = self.statement_grants(statement, audience)
        return {
            "note_id": statement.note_id,
            "audience": audience,
            "licensed": bool(grants),
            "permissions": [g.permission_id for g in grants],
            "selectors": [g.selector or "<全文>" for g in grants],
        }
