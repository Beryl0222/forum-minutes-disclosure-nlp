"""把各模块串成一次可重复的编校流水线。"""
from __future__ import annotations

from pathlib import Path

from .arrange import align
from .compose import Composer, result_to_dict
from .editions import audit_all, record_sent_edition, save_run
from .extract import extract_all
from .gazetteer import Gazetteer
from .identity import IdentityResolver
from .licensing import LicenseBook
from .loader import input_fingerprint, load_workspace


def run_pipeline(materials_dir: str | Path,
                 config_path: str | Path | None = None) -> dict:
    workspace = load_workspace(materials_dir)
    gaz = (Gazetteer(workspace["directory"], config_path)
           if config_path else Gazetteer(workspace["directory"]))
    resolver = IdentityResolver(workspace["directory"], gaz)
    license_book = LicenseBook(workspace["notes"], workspace["permissions"],
                               gaz.cfg.get("abbreviations", []))

    statements = extract_all(workspace["notes"], gaz, resolver)
    arrangements = align(statements)
    composer = Composer(workspace, arrangements, gaz, license_book)

    edition_results = []
    for audience in ("public", "session"):
        for language in ("zh", "en"):
            result = composer.build(audience, language)
            edition_results.append(result_to_dict(result))

    audits = audit_all(workspace, gaz, license_book)
    return {
        "fingerprint": input_fingerprint(materials_dir),
        "workspace": workspace,
        "gazetteer": gaz,
        "license_book": license_book,
        "statements": statements,
        "arrangements": arrangements,
        "editions": edition_results,
        "audits": audits,
    }


def write_outputs(pipeline: dict, out_dir: str | Path) -> Path:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = save_run(out, pipeline["fingerprint"],
                    pipeline["editions"], pipeline["audits"])
    for edition in pipeline["editions"]:
        target = out / f"{edition['audience']}_{edition['language']}.md"
        lines = [
            f"# {edition['audience']} / {edition['language']}",
            "",
            "## 正文",
            "",
            edition["rendered"] or "（无可用正文）",
            "",
            "## 仅供核对（不随本版本对外发送）",
            "",
        ]
        if edition["review_only"]:
            for block in edition["review_only"]:
                flag = " ⚠匿名后仍可能误导" if block["status"] == "review_only" and (
                    "唯一识别" in (block["review_reason"] or "")) else ""
                lines.append(
                    f"- [{block['source_statements'][0]}]{flag} {block['text']}"
                    f" —— {block['review_reason']}")
        else:
            lines.append("- （无）")
        lines += ["", "## 重识别评估", ""]
        if edition["risks"]:
            for risk in edition["risks"]:
                lines.append(
                    f"- [{risk['level']}/{risk['scope']}] {risk['reason']}"
                    f"（名录匹配：{', '.join(risk['matched_persons'])}）")
        else:
            lines.append("- 未发现指向未授权个人的称谓或跨句组合")
        lines += ["", "## 审稿记录（取舍依据）", ""]
        for decision in edition["decisions"]:
            lines.append(f"- {decision['decision']} | {decision['item']} | "
                         f"{decision['reason']}")
        target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    for edition in pipeline["workspace"]["editions"].values():
        if edition.phase == "sent":
            audit = next(a for a in pipeline["audits"]
                         if a["edition_id"] == edition.id)
            record_sent_edition(out, edition.id, edition, audit)
    return path
