"""读取 JSONL 交接资料并做结构校验。

所有资料视为不可信外部数据：只按显式字段解析，不执行任何内容。
"""
from __future__ import annotations

import json
from pathlib import Path

from .models import DirectoryEntry, Edition, Note, Permission

NOTE_FIELDS = {"id", "date", "session", "language", "submitted", "text"}
PERMISSION_FIELDS = {"id", "time", "material", "audiences", "selector", "note"}
EDITION_FIELDS = {"id", "audience", "language", "time", "phase", "text", "basis"}
DIRECTORY_FIELDS = {"id", "name", "aliases", "organization", "role", "period", "routes"}


class MaterialError(ValueError):
    """资料结构或引用不符合约定。"""


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        raise MaterialError(f"资料文件不存在：{path}")
    rows: list[dict] = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise MaterialError(f"{path.name} 第 {lineno} 行不是合法 JSON：{exc}") from exc
        if not isinstance(value, dict):
            raise MaterialError(f"{path.name} 第 {lineno} 行应为对象")
        rows.append(value)
    return rows


def _check_fields(rows: list[dict], fields: set[str], filename: str) -> None:
    ids: list[str] = []
    for i, row in enumerate(rows, 1):
        if set(row) != fields:
            raise MaterialError(
                f"{filename} 第 {i} 行字段为 {sorted(row)}，应为 {sorted(fields)}"
            )
        if not isinstance(row["id"], str) or not row["id"]:
            raise MaterialError(f"{filename} 第 {i} 行 id 必须为非空字符串")
        ids.append(row["id"])
    if len(ids) != len(set(ids)):
        dupes = sorted({x for x in ids if ids.count(x) > 1})
        raise MaterialError(f"{filename} 存在重复 id：{dupes}")


def load_workspace(materials_dir: str | Path) -> dict:
    """加载并交叉校验整个资料目录。"""
    base = Path(materials_dir)
    raw = {name: _read_jsonl(base / f"{name}.jsonl") for name in
           ("directory", "notes", "permissions", "editions")}
    _check_fields(raw["directory"], DIRECTORY_FIELDS, "directory.jsonl")
    _check_fields(raw["notes"], NOTE_FIELDS, "notes.jsonl")
    _check_fields(raw["permissions"], PERMISSION_FIELDS, "permissions.jsonl")
    _check_fields(raw["editions"], EDITION_FIELDS, "editions.jsonl")

    directory: dict[str, DirectoryEntry] = {}
    for row in raw["directory"]:
        if not isinstance(row["period"], list) or len(row["period"]) != 2:
            raise MaterialError(f"directory {row['id']} 的 period 应为起止月份二元组")
        kind = "body" if row["role"] == "机构" or row["organization"] == "联合代表团" else "person"
        directory[row["id"]] = DirectoryEntry(
            id=row["id"], name=row["name"], aliases=list(row["aliases"]),
            organization=row["organization"], role=row["role"],
            period=(row["period"][0], row["period"][1]),
            routes=list(row["routes"]), kind=kind,
        )

    notes: dict[str, Note] = {}
    for row in raw["notes"]:
        if row["submitted"] not in directory:
            raise MaterialError(f"note {row['id']} 的 submitted 指向不存在的名录项 {row['submitted']}")
        if row["language"] not in {"zh", "en"}:
            raise MaterialError(f"note {row['id']} 的 language 仅支持 zh/en")
        notes[row["id"]] = Note(**row)

    permissions: dict[str, Permission] = {}
    for row in raw["permissions"]:
        if row["material"] not in notes:
            raise MaterialError(
                f"permission {row['id']} 指向不存在的材料 {row['material']}"
            )
        selector = row["selector"]
        if selector and selector not in notes[row["material"]].text:
            raise MaterialError(
                f"permission {row['id']} 的 selector 不是 {row['material']} 中的原文选段"
            )
        if not isinstance(row["audiences"], list) or not row["audiences"]:
            raise MaterialError(f"permission {row['id']} 必须列明 audiences")
        permissions[row["id"]] = Permission(**row)

    editions: dict[str, Edition] = {}
    for row in raw["editions"]:
        if row["audience"] not in {"public", "session"}:
            raise MaterialError(f"edition {row['id']} 的 audience 取值非法")
        for ref in row["basis"]:
            if ref not in notes:
                raise MaterialError(f"edition {row['id']} 的 basis 引用了不存在的材料 {ref}")
        editions[row["id"]] = Edition(**row)

    return {"directory": directory, "notes": notes,
            "permissions": permissions, "editions": editions}


def input_fingerprint(materials_dir: str | Path) -> str:
    """对四个输入文件求稳定指纹，用于重跑时判断输入是否变化。"""
    import hashlib

    base = Path(materials_dir)
    hasher = hashlib.sha256()
    for name in ("directory", "notes", "permissions", "editions"):
        data = (base / f"{name}.jsonl").read_bytes()
        hasher.update(name.encode())
        hasher.update(data)
    return hasher.hexdigest()
