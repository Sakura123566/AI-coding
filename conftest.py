"""pytest 根目录钩子：把项目根塞进 sys.path，保证 `import backend` 在任何目录都能跑。"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
