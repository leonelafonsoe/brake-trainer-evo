"""Render the application icon to packaging/icon.ico and docs/images/icon.png.

    py scripts/make_icon.py

The runtime icon is drawn in code (src/brake_trainer/ui/icon.py); this script only exports the
same drawing for the executable, the installer and the documentation.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from PySide6.QtGui import QGuiApplication  # noqa: E402

from brake_trainer.ui.icon import ICON_SIZES, ico_entry, pack_ico, png_bytes  # noqa: E402


def main() -> int:
    _app = QGuiApplication.instance() or QGuiApplication([])
    (ROOT / "packaging").mkdir(exist_ok=True)
    entries = {size: ico_entry(size) for size in ICON_SIZES}
    (ROOT / "packaging" / "icon.ico").write_bytes(pack_ico(entries))
    images = ROOT / "docs" / "images"
    images.mkdir(parents=True, exist_ok=True)
    (images / "icon.png").write_bytes(png_bytes(256))
    print("wrote packaging/icon.ico and docs/images/icon.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
