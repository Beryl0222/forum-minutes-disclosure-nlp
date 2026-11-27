"""分受众出稿：公开简报 / 会内核对稿。

每条取舍弃四类之一，并完整记录依据（授权编号或原话、重识别评估、
替换与泛化措辞），让有权编辑看出哪些公开文字合在一起会出问题，
以及哪个许可或哪句原话决定了取舍。
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

from .models import Arrangement, Statement
from .reident import assess_text


@dataclass
class Block:
    arrangement_id: str
    text: str
    language: str
    status: str  # confirmed / proposal / not_adopted / review_only
    source_statements: list[str]  # note#sentence
    permissions: list[str]
    qualifiers: list[str]
    month: str | None
    routes: list[str]
    generalized: bool = False
    review_reason: str | None = None


@dataclass
class EditionResult:
    audience: str
    language: str
    blocks: list[Block] = field(default_factory=list)
    review_only: list[Block] = field(default_factory=list)
    decisions: list[dict] = field(default_factory=list)
    risks: list[dict] = field(default_factory=list)

    def render(self) -> str:
        return "\n".join(block.text for block in self.blocks)


def _route_label(routes: frozenset[str] | list[str], language: str, gaz) -> str:
    labels = []
    for route in sorted(routes):
        labels.append(gaz.route_en(route) if language == "en" else route)
    if language == "zh":
        return "、".join(labels)
    return " and ".join(labels)


def _qualifier_suffix(statement: Statement, language: str) -> str:
    parts = []
    if "scope_only" in statement.qualifiers:
        parts.append("仅交换汇总指标" if language == "zh" else "aggregate metrics only")
    if "target_not_firm" in statement.qualifiers or statement.pending:
        parts.append("具体日期待各方确认" if language == "zh"
                     else "exact date subject to confirmation")
    if not parts:
        return ""
    return ("（" + "，".join(parts) + "）") if language == "zh" else (
        " (" + "; ".join(parts) + ")")


def _body_confirmed(arrangement: Arrangement) -> list[Statement]:
    return [s for s in arrangement.statements
            if s.is_confirmed and s.speaker_status == "body"]


def _latest(statements: list[Statement]) -> Statement:
    return sorted(statements, key=lambda s: (s.date, s.note_id, s.sentence_index))[-1]


class Composer:
    def __init__(self, workspace, arrangements, gaz, license_book):
        self.ws = workspace
        self.arrangements = arrangements
        self.gaz = gaz
        self.lic = license_book
        self.directory = workspace["directory"]

    # ------------------------------------------------------------------
    def build(self, audience: str, language: str) -> EditionResult:
        result = EditionResult(audience, language)
        for arrangement in self.arrangements:
            if audience == "public":
                self._build_public(arrangement, language, result)
            else:
                self._build_session(arrangement, language, result)
        # 重识别：同一版本将同时呈现的文字合在一起评估
        blocks_for_check = [
            {"text": b.text, "language": b.language, "month": b.month,
             "date": "2026-11",
             "authorized_persons": self._authorized_persons(audience)}
            for b in result.blocks
        ]
        from .reident import assess_edition
        result.risks = assess_edition(blocks_for_check, self.gaz, self.directory)
        return result

    # ------------------------------------------------------------------
    def _build_public(self, arrangement: Arrangement, language: str,
                      result: EditionResult) -> None:
        confirmed = _body_confirmed(arrangement)
        licensed_confirmed = [s for s in confirmed
                              if self.lic.is_licensed(s, "public")]
        if licensed_confirmed:
            self._emit_confirmed(arrangement, licensed_confirmed, language, result)
        else:
            for stmt in confirmed:
                result.decisions.append({
                    "item": f"{arrangement.id}:{stmt.note_id}#{stmt.sentence_index}",
                    "decision": "exclude",
                    "reason": "机构确认说法无公开授权",
                    "evidence": self.lic.explain(stmt, "public")})

        licensed_proposals = [s for s in arrangement.statements
                              if s.is_proposal
                              and self.lic.is_licensed(s, "public")
                              and s not in licensed_confirmed]
        for stmt in licensed_proposals:
            # 同一事实已由获许可的共同确认来源承载时，不重复引用个人提议原话
            if licensed_confirmed and stmt.activity:
                result.decisions.append({
                    "item": f"{arrangement.id}:{stmt.note_id}#{stmt.sentence_index}",
                    "decision": "exclude",
                    "reason": "相同事实与限定已由共同确认来源承载，个人提议原话不重复进公开稿",
                    "evidence": {"carried_by": [
                        f"{s.note_id}#{s.sentence_index}"
                        for s in licensed_confirmed],
                        "licensing": self.lic.explain(stmt, "public")}})
                continue
            self._emit_public_proposal(arrangement, stmt, language, result)

        # 未授权说法：匿名后若仍误导则仅供核对，否则排除；事实可由共同来源承载时保留事实
        for stmt in arrangement.statements:
            if self.lic.is_licensed(stmt, "public"):
                continue
            self._emit_unlicensed(arrangement, stmt, language, result,
                                  bool(licensed_confirmed))

        # “未获采纳”只用于提议类安排；已由机构确认的安排不套用该模板
        if (not licensed_confirmed and arrangement.not_adopted
                and any(self.lic.is_licensed(s, "public")
                        for s in arrangement.statements)
                and not any(b.status == "not_adopted" for b in result.blocks)):
            self._emit_not_adopted(arrangement, language, result)

    def _emit_confirmed(self, arrangement: Arrangement,
                        statements: list[Statement], language: str,
                        result: EditionResult) -> None:
        anchor = _latest(statements)
        same_lang = [s for s in statements if s.language == language]
        source = _latest(same_lang) if same_lang else anchor
        # 限定词以最新权威说法为准（勘误链生效），并保留早先确认中的范围限定，
        # 例如“仅交换汇总指标”不会因为后续只谈日期而丢失
        merged_qualifiers = list(dict.fromkeys(
            q for s in statements for q in s.qualifiers))
        # 限定词同样吸收勘误链上的说法（s6 修正 s4 的日期措辞）
        correction_qualifiers = [
            q for s in arrangement.statements if s.is_correction
            for q in s.qualifiers]
        merged_qualifiers = list(dict.fromkeys(
            merged_qualifiers + correction_qualifiers))
        anchor_for_suffix = type(anchor)(**{**anchor.__dict__,
                                            "qualifiers": merged_qualifiers})
        # 限定词以最新权威说法为准（勘误链生效），并标注限定来自哪句原话
        text = self._fact_text(arrangement, source, language)
        suffix = _qualifier_suffix(anchor_for_suffix, language)
        block = Block(
            arrangement_id=arrangement.id, text=text + suffix, language=language,
            status="confirmed",
            source_statements=[f"{s.note_id}#{s.sentence_index}" for s in statements],
            permissions=sorted({p for s in statements
                                for p in self._perm_ids(s, "public")}),
            qualifiers=merged_qualifiers, month=arrangement.month,
            routes=sorted(arrangement.routes))
        if source.language != language:
            block.generalized = True
            result.decisions.append({
                "item": arrangement.id, "decision": "include",
                "reason": f"无{language}授权原话，按已授权共同来源的事实改写，限定沿用最新勘误",
                "evidence": {"fact_source": f"{anchor.note_id}#{anchor.sentence_index}",
                             "wording_source": f"{source.note_id}#{source.sentence_index}",
                             "permissions": block.permissions}})
        else:
            result.decisions.append({
                "item": arrangement.id, "decision": "include",
                "reason": "共同来源已确认且有公开授权，保留事实与原话限定",
                "evidence": {"permissions": block.permissions,
                             "source": block.source_statements}})
        result.blocks.append(block)

    def _fact_text(self, arrangement: Arrangement, source: Statement,
                   language: str) -> str:
        label = _route_label(arrangement.routes, language, self.gaz)
        month = arrangement.month
        if language == "zh":
            month_label = self.gaz.month_label(month[5:7]) if month else ""
            return f"{label}拟于{month_label}进行资料交换"
        month_names = ["", "January", "February", "March", "April", "May",
                       "June", "July", "August", "September", "October",
                       "November", "December"]
        month_label = month_names[int(month[5:7])] if month else ""
        return f"A data exchange is planned for {label} in {month_label}"

    def _emit_public_proposal(self, arrangement: Arrangement, stmt: Statement,
                              language: str, result: EditionResult) -> None:
        assessment = assess_text(stmt.text, stmt.language, self.gaz,
                                 self.directory, stmt.month, stmt.date)
        if assessment["level"] == "high":
            # 换成活动/议题表述，并验证剩余句子仍能区分提议与商定
            phrase = self.gaz.cfg["issue_phrasing"].get(
                stmt.activity or "data_exchange",
                {"zh": "有关安排", "en": "the relevant arrangement"})[language]
            text = (f"会上就{phrase}提出单方提议，尚未共同确认。" if language == "zh"
                    else f"A party proposed {phrase}; it was not jointly confirmed.")
            block = Block(arrangement.id, text, language, "proposal",
                          [f"{stmt.note_id}#{stmt.sentence_index}"],
                          self._perm_ids(stmt, "public"),
                          list(stmt.qualifiers), stmt.month, stmt.routes,
                          generalized=True,
                          review_reason="原话含可唯一识别个人的职务/机构/航线组合，已泛化为议题表述")
            result.decisions.append({
                "item": f"{arrangement.id}:{stmt.note_id}#{stmt.sentence_index}",
                "decision": "redact",
                "reason": "重识别风险为 high，改为议题表述并保留“单方提议”性质",
                "evidence": {"risk": assessment,
                             "permissions": self.lic.explain(stmt, "public")}})
        else:
            block = Block(arrangement.id, stmt.text, stmt.language, "proposal",
                          [f"{stmt.note_id}#{stmt.sentence_index}"],
                          self._perm_ids(stmt, "public"),
                          list(stmt.qualifiers), stmt.month, stmt.routes)
            result.decisions.append({
                "item": f"{arrangement.id}:{stmt.note_id}#{stmt.sentence_index}",
                "decision": "include", "reason": "已授权且无高重识别风险",
                "evidence": self.lic.explain(stmt, "public")})
        result.blocks.append(block)

    def _emit_unlicensed(self, arrangement: Arrangement, stmt: Statement,
                         language: str, result: EditionResult,
                         fact_carried: bool) -> None:
        assessment = assess_text(stmt.text, stmt.language, self.gaz,
                                 self.directory, stmt.month, stmt.date)
        if fact_carried and stmt.is_confirmed:
            decision, reason = "exclude", "相同事实已由获许可的共同来源承载，未授权原话不重复引用"
        elif assessment["level"] == "high":
            decision, reason = "review_only", "匿名后仍可能唯一识别个人且无公开授权，保留为仅供核对事项"
        else:
            decision, reason = "review_only", "无该受众授权，保留在仅供核对区供有权编辑审阅，不进公开正文"
        block = Block(arrangement.id, stmt.text, stmt.language, "review_only",
                      [f"{stmt.note_id}#{stmt.sentence_index}"], [],
                      list(stmt.qualifiers), stmt.month, stmt.routes,
                      review_reason=reason)
        result.review_only.append(block)
        result.decisions.append({
            "item": f"{arrangement.id}:{stmt.note_id}#{stmt.sentence_index}",
            "decision": decision, "reason": reason,
            "evidence": {"risk": assessment,
                         "licensing": self.lic.explain(stmt, "public"),
                         "original_text": stmt.text}})

    def _emit_not_adopted(self, arrangement: Arrangement, language: str,
                          result: EditionResult) -> None:
        sources = [s for s in arrangement.statements if s.not_adopted]
        source_languages = {s.language for s in sources}
        template = self.gaz.cfg["templates"]["not_adopted"][language]
        text = template.format(routes=_route_label(arrangement.routes, language, self.gaz))
        block = Block(arrangement.id, text, language, "not_adopted",
                      [f"{s.note_id}#{s.sentence_index}" for s in sources],
                      sorted({p for s in arrangement.statements
                              if self.lic.is_licensed(s, "public")
                              for p in self._perm_ids(s, "public")}),
                      ["not_adopted"], arrangement.month,
                      sorted(arrangement.routes),
                      generalized=language not in source_languages)
        result.blocks.append(block)
        result.decisions.append({
            "item": arrangement.id, "decision": "include",
            "reason": "保留“未获采纳”的区分性事实，采用不含个人指称的模板措辞"
                      + ("（目标语种无授权原话，按事实模板生成）"
                         if language not in source_languages else ""),
            "evidence": {"source": block.source_statements,
                         "permissions": block.permissions}})

    # ------------------------------------------------------------------
    def _build_session(self, arrangement: Arrangement, language: str,
                       result: EditionResult) -> None:
        for stmt in arrangement.statements:
            grants = self.lic.statement_grants(stmt, "session")
            if stmt.is_confirmed and stmt.speaker_status == "body":
                status = "confirmed"
            elif stmt.not_adopted:
                status = "not_adopted"
            elif stmt.is_proposal:
                status = "proposal"
            else:
                status = "review_only"
            if not grants:
                # 未涉及会内授权的内部记录仍供审阅，但不进核对稿正文
                reason = "内部记录未获会内核对授权，保留在审阅区不进正文"
                result.review_only.append(Block(
                    arrangement.id, stmt.text, stmt.language, "review_only",
                    [f"{stmt.note_id}#{stmt.sentence_index}"], [],
                    list(stmt.qualifiers), stmt.month, stmt.routes,
                    review_reason=reason))
                result.decisions.append({
                    "item": f"{arrangement.id}:{stmt.note_id}#{stmt.sentence_index}",
                    "decision": "review_only",
                    "reason": reason,
                    "evidence": {"licensing": self.lic.explain(stmt, "session")}})
                continue
            speaker_label = self._speaker_label(stmt)
            if stmt.language == "en":
                prefix = f"{speaker_label}: "
            else:
                prefix = f"{speaker_label}："
            block = Block(arrangement.id, prefix + stmt.text, stmt.language, status,
                          [f"{stmt.note_id}#{stmt.sentence_index}"],
                          [g.permission_id for g in grants],
                          list(stmt.qualifiers), stmt.month, stmt.routes)
            result.blocks.append(block)
            if stmt.mentions and any(m.status in {"ambiguous", "unknown"}
                                     for m in stmt.mentions):
                result.decisions.append({
                    "item": f"{arrangement.id}:{stmt.note_id}#{stmt.sentence_index}",
                    "decision": "include",
                    "reason": "指称解析存在歧义，已在核对稿保留原文并标记，请编辑确认",
                    "evidence": {"mentions": [
                        {"surface": m.surface, "status": m.status,
                         "candidates": m.candidates}
                        for m in stmt.mentions
                        if m.status in {"ambiguous", "unknown"}]}})
            else:
                result.decisions.append({
                    "item": f"{arrangement.id}:{stmt.note_id}#{stmt.sentence_index}",
                    "decision": "include",
                    "reason": "会内核对授权覆盖，保留原话与说话人归因",
                    "evidence": {"licensing": self.lic.explain(stmt, "session"),
                                 "speaker": stmt.speaker,
                                 "speaker_status": stmt.speaker_status}})

    # ------------------------------------------------------------------
    def _speaker_label(self, stmt: Statement) -> str:
        if stmt.speaker_status == "body" and stmt.speaker:
            return self.directory[stmt.speaker].name
        if stmt.speaker and stmt.speaker in self.directory:
            entry = self.directory[stmt.speaker]
            tense = "（前任）" if stmt.speaker_status == "former" else ""
            label = f"{entry.name}{tense}" if stmt.language == "zh" else (
                f"{entry.name} (former)" if tense else entry.name)
        else:
            label = stmt.reporter
        if stmt.reported:
            names = "、".join(self.directory[r].name for r in stmt.reported
                              if r in self.directory)
            if names:
                return (f"{label}（转述：{names}）" if stmt.language == "zh"
                        else f"{label} (reporting: {names})")
        return label

    def _perm_ids(self, stmt: Statement, audience: str) -> list[str]:
        return [g.permission_id
                for g in self.lic.statement_grants(stmt, audience)]

    def _authorized_persons(self, audience: str) -> set[str]:
        """该受众下，以个人名义获授权出现的名录 id（机构授权不计个人）。"""
        allowed = set()
        for grant in self.lic.grants:
            if grant.audience != audience:
                continue
            submitter = self.ws["notes"][grant.material].submitted
            if self.directory[submitter].kind == "person":
                allowed.add(submitter)
        return allowed


def result_to_dict(result: EditionResult) -> dict:
    return {
        "audience": result.audience,
        "language": result.language,
        "rendered": result.render(),
        "blocks": [asdict(b) for b in result.blocks],
        "review_only": [asdict(b) for b in result.review_only],
        "decisions": result.decisions,
        "risks": result.risks,
    }
