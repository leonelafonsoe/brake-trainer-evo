from __future__ import annotations

from brake_trainer import paths


def test_the_app_folder_holds_settings_data_and_logs(tmp_path, monkeypatch):
    monkeypatch.setenv(paths.HOME_ENV, str(tmp_path / "home"))

    assert paths.app_dir() == tmp_path / "home"
    assert paths.data_dir() == tmp_path / "home" / "data"
    assert paths.data_dir().is_dir()
    assert paths.settings_path() == tmp_path / "home" / "settings.json"
    assert paths.log_path() == tmp_path / "home" / "brake_trainer.log"


def test_an_unusable_app_folder_falls_back_to_the_temp_folder(tmp_path, monkeypatch):
    # A file where the folder should be makes mkdir fail. The app must still start, with its files
    # in the temp folder, instead of dying before the overlay appears.
    blocked = tmp_path / "blocked"
    blocked.write_text("a file, not a folder", encoding="utf-8")
    fallback = tmp_path / "temp"
    fallback.mkdir()
    monkeypatch.setenv(paths.HOME_ENV, str(blocked))
    monkeypatch.setattr(paths.tempfile, "gettempdir", lambda: str(fallback))

    assert paths.app_dir() == fallback / paths.APP_NAME
    assert paths.app_dir().is_dir()
