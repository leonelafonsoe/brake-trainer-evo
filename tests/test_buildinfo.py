from __future__ import annotations

import sys

from brake_trainer import buildinfo


def test_the_environment_can_name_the_build(monkeypatch):
    monkeypatch.setenv(buildinfo.BUILD_ENV, "  local-fix  ")
    assert buildinfo.build_id() == "local-fix"


def test_a_frozen_build_reports_packaged(monkeypatch):
    monkeypatch.delenv(buildinfo.BUILD_ENV, raising=False)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert buildinfo.build_id() == buildinfo.PACKAGED


def test_no_checkout_and_no_override_is_unknown(monkeypatch):
    monkeypatch.delenv(buildinfo.BUILD_ENV, raising=False)
    monkeypatch.setattr(buildinfo, "_git_describe", lambda: "")
    assert buildinfo.build_id() == buildinfo.UNKNOWN
