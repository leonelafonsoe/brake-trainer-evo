# Third-party licence texts

`scripts/build_exe.py` copies this folder into the packaged program as `licenses/`, so the texts
travel with the portable zip and with an installed copy. `THIRD_PARTY_NOTICES.md` explains what
each dependency is used for.

| File | Source |
| --- | --- |
| `MIT-acevo-sdk.txt` | The `acevo-sdk` 0.1.1 wheel metadata (MIT). |
| `LGPL-3.0.txt` | The GNU Lesser General Public License v3.0, from <https://www.gnu.org/licenses/lgpl-3.0.txt>. |

PyInstaller is a build-time tool, not part of the program; its licence and bootloader exception are
described in `THIRD_PARTY_NOTICES.md`. Inno Setup is likewise build-time only.

When a dependency or its licence changes, update the text here and the notice together.
