from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def preferred_cjk_font_name() -> str:
    candidates = [
        ("Noto Sans CJK SC", Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc")),
        ("Noto Sans CJK SC", Path("/usr/share/fonts/opentype/noto/NotoSansCJKsc-Regular.otf")),
        ("Noto Sans CJK SC", Path("/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc")),
        ("PingFang SC", Path("/System/Library/Fonts/PingFang.ttc")),
        ("Hiragino Sans GB", Path("/System/Library/Fonts/Hiragino Sans GB.ttc")),
        ("Heiti SC", Path("/System/Library/Fonts/STHeiti Medium.ttc")),
    ]
    windows = Path(os.environ.get("WINDIR") or "C:/Windows") / "Fonts"
    candidates.extend(
        [
            ("Microsoft YaHei", windows / "msyh.ttc"),
            ("SimHei", windows / "simhei.ttf"),
        ]
    )
    for name, path in candidates:
        if path.is_file():
            return name
    return "Noto Sans CJK SC"
