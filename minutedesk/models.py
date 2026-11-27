"""纪要编校工具的数据模型。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class Span:
    """原文中的字符区间，便于回指原话。"""

    start: int
    end: int
    text: str


@dataclass
class DirectoryEntry:
    id: str
    name: str
    aliases: list[str]
    organization: str
    role: str
    period: tuple[str, str]
    routes: list[str]
    kind: str  # person / body


@dataclass
class Note:
    id: str
    date: str
    session: str
    language: str
    submitted: str
    text: str


@dataclass
class Permission:
    id: str
    time: str
    material: str
    audiences: list[str]
    selector: str
    note: str


@dataclass
class Edition:
    id: str
    audience: str
    language: str
    time: str
    phase: str
    text: str
    basis: list[str]


@dataclass
class Sentence:
    note_id: str
    index: int
    start: int
    end: int
    text: str
    language: str


@dataclass
class Surface:
    """文句中命中的一个词表项。"""

    text: str
    kind: str  # alias / body / role / org / route / activity / time / cue / tense / anaphora
    canonical: str
    start: int
    end: int


@dataclass
class Mention:
    """对人物或机构主体的一次指称及其解析结果。"""

    surface: str
    kind: str
    candidates: list[str]
    resolved: Optional[str]
    status: str  # exact / resolved / ambiguous / unknown / body
    start: int
    end: int


@dataclass
class Statement:
    """从一句话中抽出的说法：谁说的、什么性质、哪些限定。"""

    note_id: str
    sentence_index: int
    language: str
    date: str
    reporter: str
    speaker: Optional[str]
    speaker_status: str
    primary_kind: str  # proposal / confirmed / correction / caveat / other
    is_proposal: bool
    is_confirmed: bool
    is_correction: bool
    not_adopted: bool
    pending: bool
    routes: list[str]
    organizations: list[str]
    activity: Optional[str]
    month: Optional[str]
    month_resolved: bool  # 下月等相对月份是否已按记录日期换算
    qualifiers: list[str]
    correction_target: Optional[str]
    surfaces: list[Surface] = field(default_factory=list)
    mentions: list[Mention] = field(default_factory=list)
    text: str = ""
    reported: list[str] = field(default_factory=list)  # 句中转述到的其他主体


@dataclass
class Arrangement:
    """跨语种对齐后的同一项安排。"""

    id: str
    activity: Optional[str]
    routes: frozenset[str]
    month: Optional[str]
    statements: list[Statement] = field(default_factory=list)
    weak_links: list[dict] = field(default_factory=list)
    created_order: int = 0

    @property
    def languages(self) -> set[str]:
        return {s.language for s in self.statements}

    @property
    def is_confirmed(self) -> bool:
        return any(s.is_confirmed and s.speaker_status == "body" for s in self.statements)

    @property
    def not_adopted(self) -> bool:
        return any(s.not_adopted for s in self.statements)

    def proposals(self) -> list[Statement]:
        return [s for s in self.statements if s.is_proposal]


@dataclass
class Decision:
    """一条出稿取舍记录，供有权编辑回查。"""

    item: str
    decision: str  # include / redact / review_only / exclude
    reason: str
    evidence: dict = field(default_factory=dict)


@dataclass
class Risk:
    chain_id: int
    surfaces: list[str]
    orgs: list[str]
    routes: list[str]
    tense: Optional[str]
    matched_persons: list[str]
    level: str  # high / medium / low
    reason: str
    spans: list[Span] = field(default_factory=list)
