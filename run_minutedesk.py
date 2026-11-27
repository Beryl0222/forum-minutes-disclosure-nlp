#!/usr/bin/env python3
"""命令行入口脚本：放在包目录之外，避免相对导入问题。

推荐以隔离模式运行，解释器不会从资料目录加载任何代码：
    python3 -I run_minutedesk.py /path/to/materials -o /path/to/out
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from minutedesk.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
