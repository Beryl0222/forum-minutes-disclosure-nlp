"""由合成公开名录和项目同义词配置构建双语地名词表。

术语模板（config/synonyms.json）随项目替换，引擎本身不内置任何专有名称。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from .models import DirectoryEntry, Surface

DEFAULT_CONFIG = Path(__file__).resolve().parents[1] / "config" / "synonyms.json"


class Gazetteer:
    def __init__(self, directory: dict[str, DirectoryEntry], config_path: str | Path = DEFAULT_CONFIG):
        with open(config_path, encoding="utf-8") as fh:
            self.cfg = json.load(fh)
        self.directory = directory
        # canonical surface -> (kind, canonical)
        self._index: list[tuple[str, str, str]] = []
        self._build_person_index()
        self._build_term_index()
        # 长串优先，保证“北环货线”先于“北环”命中
        self._index.sort(key=lambda item: len(item[0]), reverse=True)

    def _add(self, surface: str, kind: str, canonical: str) -> None:
        surface = surface.strip()
        if surface:
            self._index.append((surface, kind, canonical))

    def _build_person_index(self) -> None:
        for entry in self.directory.values():
            if entry.kind == "person":
                self._add(entry.name, "alias", entry.id)
                for alias in entry.aliases:
                    self._add(alias, "alias", entry.id)
            else:
                self._add(entry.name, "body", entry.id)
                for alias in entry.aliases:
                    self._add(alias, "body", entry.id)

    def _build_term_index(self) -> None:
        for canonical, terms in self.cfg["routes"].items():
            self._add(canonical, "route", canonical)
            for term in terms:
                self._add(term, "route", canonical)
        for canonical, terms in self.cfg["organizations"].items():
            self._add(canonical, "org", canonical)
            for term in terms:
                self._add(term, "org", canonical)
        for canonical, terms in self.cfg["roles"].items():
            self._add(canonical, "role", canonical)
            for term in terms:
                self._add(term, "role", canonical)
        for canonical, terms in self.cfg["bodies"].items():
            self._add(canonical, "body_name", canonical)
            for term in terms:
                self._add(term, "body_name", canonical)
        for activity, terms in self.cfg["activities"].items():
            for term in terms:
                self._add(term, "activity", activity)
        for term, month in self.cfg["time_terms"].items():
            self._add(term, "time", month)
        for kind, terms in self.cfg["cues"].items():
            for term in terms:
                self._add(term, "cue", kind)
        for kind, terms in self.cfg["tense"].items():
            for term in terms:
                self._add(term, "tense", kind)
        for term in self.cfg["anaphora"]:
            self._add(term, "anaphora", term)

    # ------------------------------------------------------------------
    def scan(self, text: str) -> list[Surface]:
        """返回互不重叠的词表命中（最长优先、从左到右）。"""
        found: list[Surface] = []
        occupied: list[tuple[int, int]] = []
        lowered = text.lower()
        for surface, kind, canonical in self._index:
            is_latin = bool(re.search(r"[A-Za-z]", surface))
            if is_latin:
                # 含标点的别名（如 P. Xu）不能用标准词边界：句点后接空格会中断 \b
                if re.search(r"[.\s]", surface):
                    pattern = re.escape(surface)
                else:
                    pattern = r"\b" + re.escape(surface) + r"\b"
            else:
                pattern = re.escape(surface)
            for match in re.finditer(pattern, text,
                                     flags=re.IGNORECASE if is_latin else 0):
                start, end = match.span()
                # 中文简称的后续字护栏：银湾仓/银湾港 不是银湾线
                if kind == "route":
                    followers = self.cfg["block_followers"].get(surface, [])
                    if end < len(text) and text[end] in followers:
                        continue
                if any(start < occ_end and end > occ_start for occ_start, occ_end in occupied):
                    continue
                occupied.append((start, end))
                found.append(Surface(text[start:end], kind, canonical, start, end))
        found.sort(key=lambda s: s.start)
        return found

    def find_persons(self, *ids: str | None) -> list[DirectoryEntry]:
        return [self.directory[i] for i in ids if i and i in self.directory]

    def person_index(self) -> dict[str, list[str]]:
        """姓名/别名 -> 候选名录 id。"""
        result: dict[str, list[str]] = {}
        for surface, kind, canonical in self._index:
            if kind == "alias":
                result.setdefault(surface.lower(), [])
                if canonical not in result[surface.lower()]:
                    result[surface.lower()].append(canonical)
        return result

    def route_en(self, canonical: str) -> str:
        return self.cfg["route_en"].get(canonical, canonical)

    def month_label(self, month: str) -> str:
        for term, value in self.cfg["time_terms"].items():
            if value == month and re.search(r"[一-鿿]", term):
                return term
        return month
