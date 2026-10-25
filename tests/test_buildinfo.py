from __future__ import annotations

import sys

from brake_trainer import buildinfo


def test_the_environment_can_name_the_build(monkeypatch):
    monkeypatch.setenv(buildinfo.BUILD_ENV, "  local-fix  ")
    assert buildinfo.build_id() == "local-fix"


def test_a_frozen_build_uses_the_identifier_baked_in_at_build_time(tmp_path, monkeypatch):
    (tmp_path / buildinfo.BUILD_FILE).write_text("abc123def456\n", encoding="utf-8")
    monkeypatch.delenv(buildinfo.BUILD_ENV, raising=False)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    assert buildinfo.build_id() == "abc123def456"


def test_the_environment_outranks_the_baked_identifier(tmp_path, monkeypatch):
    (tmp_path / buildinfo.BUILD_FILE).write_text("abc123\n", encoding="utf-8")
    monkeypatch.setenv(buildinfo.BUILD_ENV, "local-fix")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    assert buildinfo.build_id() == "local-fix"


def test_a_frozen_build_reports_packaged(monkeypatch):
    monkeypatch.delenv(buildinfo.BUILD_ENV, raising=False)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", "/nonexistent-brake-trainer", raising=False)
    assert buildinfo.build_id() == buildinfo.PACKAGED


def test_no_checkout_and_no_override_is_unknown(monkeypatch):
    monkeypatch.delenv(buildinfo.BUILD_ENV, raising=False)
    monkeypatch.setattr(buildinfo, "_git_describe", lambda: "")
    assert buildinfo.build_id() == buildinfo.UNKNOWN
