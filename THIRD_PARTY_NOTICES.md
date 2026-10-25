# Third-party software

Brake Trainer EVO is built on the following projects. Their licenses apply to them, not to this
project's own code (see [LICENSE](LICENSE)).

| Project | Used for | License |
| --- | --- | --- |
| [acevo-sdk](https://github.com/glebulon/acevo-sdk) by Gleb Zverinskiy | Reading Assetto Corsa EVO's shared-memory telemetry | MIT |
| [PySide6 / Qt for Python](https://doc.qt.io/qtforpython-6/) | The user interface | LGPLv3 / GPLv3 / Qt commercial |
| [PyInstaller](https://pyinstaller.org) (build time only) | Packaging the Windows executable | GPLv2 with a bootloader exception that allows distributing the built app under its own license |

[Inno Setup](https://jrsoftware.org/isinfo.php) is used at build time to make the installer; it is
not part of the program.

If you distribute a built executable, it contains PySide6 and Qt. The LGPL asks you to pass on
its license text and not to prevent users from replacing the Qt libraries. The default
**folder build** (`scripts/build_exe.py`) keeps them as separate files, which satisfies this more
easily than a single-file build. The MIT and LGPLv3 texts travel beside the program in `licenses/`;
this is a summary, not legal advice. Read the Qt licensing page if you plan to redistribute
binaries.

## Inspiration (not a dependency)

[Brake Trainer](https://www.overtake.gg/downloads/brake-trainer.32511/) by AugGust is the original braking-point trainer for Assetto Corsa. This project reimplements the idea from scratch for Assetto Corsa EVO and contains none of its code.

"Assetto Corsa" and "Assetto Corsa EVO" are trademarks of their respective owners. This project is
an independent, unofficial tool and is not affiliated with or endorsed by them.
