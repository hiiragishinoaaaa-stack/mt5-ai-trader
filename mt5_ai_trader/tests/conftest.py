"""pytest設定。

tests/ から見て一つ上の mt5_ai_trader/ ディレクトリを sys.path に追加し、
`import config` / `import indicators` のようなフラットな import を
どのカレントディレクトリから実行しても解決できるようにする。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
