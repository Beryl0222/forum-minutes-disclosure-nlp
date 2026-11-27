"""命令行入口。

脚本只接收路径参数，不切换工作目录；处理不可信资料时请配合 python -I 运行。
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict

from .editions import diff_runs, load_run
from .pipeline import run_pipeline, write_outputs


def _print_summary(pipeline: dict) -> None:
    print(f"输入指纹：{pipeline['fingerprint'][:12]}")
    print(f"说法 {len(pipeline['statements'])} 条，"
          f"对齐为安排 {len(pipeline['arrangements'])} 项")
    for arrangement in pipeline["arrangements"]:
        print(f"  {arrangement.id} 活动={arrangement.activity} "
              f"航线={sorted(arrangement.routes)} 月份={arrangement.month} "
              f"语种={sorted(arrangement.languages)} "
              f"确认={'是' if arrangement.is_confirmed else '否'} "
              f"未采纳={'是' if arrangement.not_adopted else '否'} "
              f"弱关联={[w['other'] for w in arrangement.weak_links]}")
    print("\n== 版本与取舍 ==")
    for edition in pipeline["editions"]:
        print(f"\n[{edition['audience']}/{edition['language']}] "
              f"正文 {len(edition['blocks'])} 段，"
              f"仅供核对 {len(edition['review_only'])} 段，"
              f"重识别风险 {len(edition['risks'])} 条")
        for block in edition["blocks"]:
            print(f"  - ({block['status']}) {block['text']}")
        for risk in edition["risks"]:
            print(f"  ! [{risk['level']}/{risk['scope']}] {risk['reason']}")
    print("\n== 存稿审计 ==")
    for audit in pipeline["audits"]:
        mark = "通过" if audit["passed"] else "不通过"
        print(f"  {audit['edition_id']}（{audit['phase']}）：{mark}，"
              f"问题 {len(audit['findings'])} 条")
        for finding in audit["findings"]:
            print(f"    [{finding['severity']}/{finding['code']}] "
                  f"{finding['message']}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="minutedesk", description="跨境论坛纪要编校与授权核对工具")
    parser.add_argument("materials", help="JSONL 资料目录（不可信数据应独立存放）")
    parser.add_argument("-o", "--out", default="build", help="输出目录")
    parser.add_argument("--config", help="同义词与模板配置（默认 config/synonyms.json）")
    parser.add_argument("--json", action="store_true", help="输出完整 JSON 而非摘要")
    parser.add_argument("--compare", help="与历史 run 结果 JSON 比较后退出")
    args = parser.parse_args(argv)

    pipeline = run_pipeline(args.materials, args.config)
    if args.compare:
        diff = diff_runs(load_run(args.compare), {
            "editions": pipeline["editions"], "audits": pipeline["audits"]})
        print(json.dumps(diff, ensure_ascii=False, indent=2))
        return 0

    path = write_outputs(pipeline, args.out)
    if args.json:
        payload = {
            "fingerprint": pipeline["fingerprint"],
            "arrangements": [
                {**asdict(a), "routes": sorted(a.routes)}
                for a in pipeline["arrangements"]],
            "editions": pipeline["editions"],
            "audits": pipeline["audits"],
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        _print_summary(pipeline)
        print(f"\n结果已写入：{path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
