"""跨语种安排对齐。

同一项安排的判定看活动类型、适用航线（同集合或真包含）、月份与确认轨迹，
而不是只看相近数字或合作名称。相近但不满足条件的说法只建立“弱关联”，
把分歧留给编辑，不自动合并。勘误链（Correction to sX / 勘误 sX）强制归并。

关键约束：活动、航线等关键要素缺失的说法不充当跨材料合并的通配符，
只允许附到同一材料的主说法或勘误链上，避免“一句无信息句把全场并成一项”。
"""
from __future__ import annotations

from .models import Arrangement, Statement


def _key(statement: Statement) -> tuple:
    return (statement.activity or "", tuple(statement.routes), statement.month or "")


def is_key(statement: Statement) -> bool:
    return bool(statement.activity and statement.routes and statement.month)


class _UnionFind:
    def __init__(self, n: int):
        self.parent = list(range(n))

    def find(self, x: int) -> int:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[max(ra, rb)] = min(ra, rb)


def _strong_compatible(a: Statement, b: Statement) -> bool:
    """活动相同，月份一致（含一方缺省），航线同集合或真包含。

    双方都必须是带要素的关键说法；要素缺失不构成合并理由。
    """
    if not (is_key(a) and is_key(b)):
        return False
    if a.activity != b.activity:
        return False
    if a.month is not None and b.month is not None and a.month != b.month:
        return False
    ra, rb = set(a.routes), set(b.routes)
    return ra == rb or ra < rb or rb < ra


def _weak_reason(a: Statement, b: Statement) -> str | None:
    """解释为什么不自动合并；数字/名称相近不构成同项证据。"""
    shared_routes = set(a.routes) & set(b.routes)
    if not shared_routes:
        return None
    if a.activity != b.activity:
        return f"同航线但活动不同（{a.activity} / {b.activity}）"
    if a.month and b.month and a.month != b.month:
        return f"活动与航线相近但月份不一致（{a.month} / {b.month}）"
    if a.activity == b.activity and a.month == b.month and (
            set(a.routes) != set(b.routes)):
        return f"同活动同月但航线集合不同（{sorted(a.routes)} / {sorted(b.routes)}）"
    return None


def align(statements: list[Statement]) -> list[Arrangement]:
    n = len(statements)
    uf = _UnionFind(n)

    note_to_indices: dict[str, list[int]] = {}
    for i, stmt in enumerate(statements):
        note_to_indices.setdefault(stmt.note_id, []).append(i)

    # 1. 勘误链强制归并
    for i, stmt in enumerate(statements):
        if stmt.correction_target:
            for j in note_to_indices.get(stmt.correction_target, []):
                uf.union(i, j)

    # 2. 关键说法按 (活动, 航线集合, 月份) 精确归并（跨语种对齐主路径）
    by_key: dict[tuple, list[int]] = {}
    for i, stmt in enumerate(statements):
        if is_key(stmt):
            by_key.setdefault(_key(stmt), []).append(i)
    for indices in by_key.values():
        for j in indices[1:]:
            uf.union(indices[0], j)

    # 3. 关键说法之间的强兼容（真包含）
    key_indices = [i for i, s in enumerate(statements) if is_key(s)]
    for x_pos in range(len(key_indices)):
        for y_pos in range(x_pos + 1, len(key_indices)):
            i, j = key_indices[x_pos], key_indices[y_pos]
            if uf.find(i) != uf.find(j) and _strong_compatible(
                    statements[i], statements[j]):
                uf.union(i, j)

    # 4. 非关键说法只附到同一材料、同航线的主说法；要素对不上就独立成组
    for i, stmt in enumerate(statements):
        if is_key(stmt):
            continue
        candidates = [j for j in note_to_indices[stmt.note_id]
                      if is_key(statements[j])]
        if stmt.routes:
            same_route = [j for j in candidates
                          if set(statements[j].routes) & set(stmt.routes)]
            if same_route:
                for j in same_route:
                    uf.union(i, j)
            # 同材料但无同航线主说法：不并入，避免把不同安排粘在一起
        elif candidates:
            # 无航线的句子（如纯勘误/纯态度句）附到同材料唯一主说法
            if len(candidates) == 1:
                uf.union(i, candidates[0])

    groups: dict[int, list[int]] = {}
    for i in range(n):
        groups.setdefault(uf.find(i), []).append(i)

    arrangements: list[Arrangement] = []
    for order, (_, indices) in enumerate(sorted(groups.items()), 1):
        members = [statements[i] for i in sorted(indices)]
        key_members = [m for m in members if is_key(m)]
        if key_members:
            activities = {m.activity for m in key_members}
            routes = frozenset(r for m in key_members for r in m.routes)
            months = sorted({m.month for m in key_members if m.month})
        else:
            activities = {m.activity for m in members if m.activity}
            routes = frozenset(r for m in members for r in m.routes)
            months = sorted({m.month for m in members if m.month})
        arrangement = Arrangement(
            id=f"A{order}",
            activity=next(iter(activities)) if len(activities) == 1 else None,
            routes=routes, month=months[0] if months else None,
            statements=members, created_order=order,
        )
        arrangements.append(arrangement)

    # 5. 弱关联：相近但不能合并的安排互相标记，留给编辑。
    #    关键说法按要素比较；同安排内的非关键句点到的航线/活动也作为线索。
    for x in range(len(arrangements)):
        for y in range(x + 1, len(arrangements)):
            ax, ay = arrangements[x], arrangements[y]
            reason = None
            for sa in ax.statements:
                if not is_key(sa):
                    continue
                for sb in ay.statements:
                    if is_key(sb):
                        reason = reason or _weak_reason(sa, sb)
            if reason is None:
                reason = _contextual_reason(ax, ay)
            if reason:
                ax.weak_links.append({"other": ay.id, "reason": reason})
                ay.weak_links.append({"other": ax.id, "reason": reason})

    return arrangements


def _contextual_reason(ax: Arrangement, ay: Arrangement) -> str | None:
    """利用非关键句中的航线/活动线索解释两项安排为何相关但不能合并。"""
    ax_routes = set(ax.routes)
    ay_routes = set(ay.routes)
    for stmt in ax.statements:
        if is_key(stmt):
            continue
        shared = set(stmt.routes) & ay_routes
        if shared and stmt.not_adopted:
            return (f"说法 {stmt.note_id}#{stmt.sentence_index} 指出 "
                    f"{sorted(shared)} 的提议未获采纳，与另一安排相关但事项不同")
    for stmt in ay.statements:
        if is_key(stmt):
            continue
        shared = set(stmt.routes) & ax_routes
        if shared and stmt.not_adopted:
            return (f"说法 {stmt.note_id}#{stmt.sentence_index} 指出 "
                    f"{sorted(shared)} 的提议未获采纳，与另一安排相关但事项不同")
    if ax_routes & ay_routes and ax.activity != ay.activity:
        return f"航线有交集但活动不同（{ax.activity} / {ay.activity}）"
    return None


def arrangement_note_ids(arrangement: Arrangement) -> list[str]:
    return sorted({s.note_id for s in arrangement.statements})
