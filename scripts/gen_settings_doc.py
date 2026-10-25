"""Generate docs/SETTINGS.md from the settings registry.

py scripts/gen_settings_doc.py            # rewrite docs/SETTINGS.md
py scripts/gen_settings_doc.py --check    # exit 1 if the file is out of date (used by tests)
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from brake_trainer.config import Settings  # noqa: E402
from brake_trainer.settings_spec import HIDDEN, TABS, SettingSpec  # noqa: E402

OUT = ROOT / "docs" / "SETTINGS.md"

_INTRO = """# Settings reference

*Generated from the settings window by `scripts/gen_settings_doc.py`. Do not edit by hand.*

Open the settings window from the overlay (hover, then the gear), the overlay's right-click menu,
or the tray icon. **Apply** saves and takes effect immediately. Settings are stored in
`%APPDATA%\\BrakeTrainerEvo\\settings.json`; the "Key" column is the name used in that file.

Every setting applies to the running session; no restart is needed. Two kinds do extra work when
they change: a different **Preferred reference car** is looked up again, and a lower **Fastest runs
kept per sector** removes the slower stored runs and rebuilds the braking points. Turning **Follow
the game's log** off stops waiting for its sector lines (the equal splits stay), and turning it on
again starts that wait for an entry with no runs yet. The **Telemetry rate** is used the next time
telemetry capture starts.
"""


def _fmt(value: object) -> str:
    if isinstance(value, bool):
        return "on" if value else "off"
    if value is None:
        return "auto"
    if value == "":
        return "empty"
    if isinstance(value, float):
        return f"{value:g}"
    return str(value)


def _range(spec: SettingSpec) -> str:
    if spec.kind == "bool":
        return "on / off"
    if spec.kind == "text":
        return "text"
    assert spec.lo is not None and spec.hi is not None
    lo, hi, unit = _fmt(spec.lo), _fmt(spec.hi), spec.suffix.strip()
    text = f"{lo} - {hi}{' ' + unit if unit else ''}"
    if spec.kind == "optint":
        return f"auto, or {max(int(spec.lo), 1)} - {hi}"
    if spec.special:
        suffix = f" {unit}" if unit else ""
        return f"{spec.special.lower()} ({lo}), or {int(spec.lo) + 1} - {hi}{suffix}"
    return text


def render() -> str:
    defaults = Settings()
    parts = [_INTRO]
    for tab, specs in TABS.items():
        parts.append(f"\n## {tab}\n")
        parts.append("| Setting | Key | Default | Range | What it does |")
        parts.append("| --- | --- | --- | --- | --- |")
        for spec in specs:
            default = _fmt(getattr(defaults, spec.name))
            if spec.suffix and default not in ("on", "off", "auto", "empty"):
                default += spec.suffix
            tip = spec.tip.replace("|", "\\|") or "-"
            parts.append(f"| {spec.label} | `{spec.name}` | {default} | {_range(spec)} | {tip} |")
    parts.append("\n## Stored but not shown in the window\n")
    for spec in HIDDEN:
        parts.append(f"- `{spec.name}` (default {_fmt(getattr(defaults, spec.name))})")
    parts.append(
        "\nThe overlay position is saved when you drag the window. "
        '"Reset position" in the overlay or tray menu moves it back to the top centre.\n'
    )
    return "\n".join(parts).rstrip("\n") + "\n"


def main() -> int:
    text = render()
    if "--check" in sys.argv:
        current = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
        if current != text:
            print("docs/SETTINGS.md is out of date: run py scripts/gen_settings_doc.py")
            return 1
        return 0
    OUT.write_text(text, encoding="utf-8")
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
