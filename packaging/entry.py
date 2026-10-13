"""PyInstaller entry point (a plain script, so package-relative imports keep working)."""

from brake_trainer.app import main

if __name__ == "__main__":
    raise SystemExit(main())
