"""句子切分与说法抽取：转述链、性质标签、日期与限定词。"""
from __future__ import annotations

import re

from .models import Note, Sentence, Statement, Surface

_SPLIT_ZH = re.compile(r"(?<=[。！？；：])")
_SENTENCE_END_EN = re.compile(r"[.!?;]+\s+")


def _split_english(text: str, abbreviations: list[str]) -> list[str]:
    """按句末标点切句，配置中的缩写（P. / Mr. 等）不切断。"""
    pieces: list[str] = []
    start = 0
    for match in _SENTENCE_END_EN.finditer(text):
        cut = match.end()
        # 若标点属于配置缩写，则不在此切分
        if any(text[:match.start() + 1].endswith(ab) for ab in abbreviations):
            continue
        pieces.append(text[start:cut].strip())
        start = cut
    tail = text[start:].strip()
    if tail:
        pieces.append(tail)
    return [p for p in pieces if p]


def split_sentences(note: Note, abbreviations: list[str] | None = None) -> list[Sentence]:
    text = note.text.strip()
    if note.language == "zh":
        pieces = [p for p in _SPLIT_ZH.split(text) if p.strip()]
    else:
        pieces = _split_english(text, abbreviations or [])
    sentences: list[Sentence] = []
    cursor = 0
    for index, piece in enumerate(pieces):
        start = text.index(piece, cursor)
        end = start + len(piece)
        cursor = end
        sentences.append(Sentence(note.id, index, start, end, piece, note.language))
    return sentences


def _next_month(date_str: str) -> str:
    year, month = int(date_str[:4]), int(date_str[5:7])
    if month == 12:
        year, month = year + 1, 1
    else:
        month += 1
    return f"{year:04d}-{month:02d}"


def extract_statement(note: Note, sentence: Sentence, surfaces: list[Surface],
                      mentions: list, speaker: str | None, speaker_status: str,
                      correction_re: re.Pattern) -> Statement:
    text = sentence.text
    cues = {s.canonical for s in surfaces if s.kind == "cue"}
    correction_match = correction_re.search(text)
    correction_target = correction_match.group(1) if correction_match else None
    is_correction = correction_target is not None

    # 句子性质由主导说法决定；同一句出现多个 cue 时，确认/未采纳优先于提议词
    is_confirmed = "confirmed" in cues
    not_adopted = "not_adopted" in cues
    pending = "pending" in cues
    if is_correction:
        primary = "correction"
    elif is_confirmed:
        primary = "confirmed"
    elif not_adopted:
        primary = "caveat"
    elif "proposal" in cues:
        primary = "proposal"
    elif pending:
        primary = "caveat"
    else:
        primary = "other"
    is_proposal = primary == "proposal"

    routes = sorted({s.canonical for s in surfaces if s.kind == "route"})
    orgs = sorted({s.canonical for s in surfaces if s.kind == "org"})
    activities = sorted({s.canonical for s in surfaces if s.kind == "activity"})
    activity = activities[0] if activities else None

    month = None
    month_resolved = True
    for surface in surfaces:
        if surface.kind != "time":
            continue
        if surface.canonical == "next":
            month = _next_month(note.date)
            month_resolved = False  # 相对月份，已按记录日期换算但需保留来源标注
        else:
            month = f"{note.date[:4]}-{surface.canonical}"
            month_resolved = True
    # 限定词只保留范围/时间等修饰，不含说法性质标签（提议/确认本身不是限定）
    qualifiers = [q for q in cues if q in {"pending", "not_adopted"}]
    # 保留原话里的范围限定（如“仅交换汇总指标”“aggregate ... only”）
    if "仅" in text or re.search(r"\bonly\b|aggregate-only", text, flags=re.IGNORECASE):
        qualifiers.append("scope_only")
    if re.search(r"原则上|target|tentative", text, flags=re.IGNORECASE):
        qualifiers.append("target_not_firm")

    return Statement(
        note_id=note.id, sentence_index=sentence.index, language=note.language,
        date=note.date, reporter=note.submitted, speaker=speaker,
        speaker_status=speaker_status,
        reported=[m.resolved for m in mentions
                  if m.kind == "person" and m.resolved and m.resolved != speaker],
        primary_kind=primary,
        is_proposal=is_proposal, is_confirmed=is_confirmed,
        is_correction=is_correction, not_adopted=not_adopted, pending=pending,
        routes=routes, organizations=orgs, activity=activity, month=month,
        month_resolved=month_resolved, qualifiers=qualifiers,
        correction_target=correction_target, surfaces=list(surfaces), text=text,
    )


def extract_all(notes: dict[str, Note], gaz, resolver) -> list[Statement]:
    correction_re = re.compile(gaz.cfg["correction_pattern"])
    abbreviations = gaz.cfg.get("abbreviations", [])
    statements: list[Statement] = []
    for note in notes.values():
        for sentence in split_sentences(note, abbreviations):
            spans = [s for s in gaz.scan(sentence.text)]
            mentions = resolver.resolve_mentions(note, spans)
            speaker, status = resolver.resolve_speaker(note, sentence.text, mentions)
            stmt = extract_statement(note, sentence, spans, mentions, speaker,
                                     status, correction_re)
            stmt.mentions = mentions
            statements.append(stmt)
    return statements
