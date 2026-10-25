"""The settings registry is the single source of metadata; guard it against drift."""

from __future__ import annotations

from dataclasses import fields
from typing import get_args, get_type_hints

import pytest

from brake_trainer import settings_spec
from brake_trainer.config import Settings
from brake_trainer.settings_spec import (
    DEFAULTS,
    HIDDEN,
    LIMITS,
    OPTIONAL_INT,
    SPEC_BY_NAME,
    SPECS,
    TAB_ORDER,
    TABS,
)


def test_registry_covers_every_settings_field_exactly_once():
    names = {field.name for field in fields(Settings)}

    assert set(SPEC_BY_NAME) == names
    assert len(SPECS) == len(names)
    assert set(DEFAULTS) == names


def test_visible_hidden_and_internal_fields_are_explicit():
    visible = [spec.name for specs in TABS.values() for spec in specs]

    # TABS groups by tab, so its flattened order need not match SPECS; every visible spec must
    # still appear exactly once.
    assert set(visible) == {spec.name for spec in SPECS if spec.visible}
    assert len(visible) == len(set(visible))
    assert tuple(TABS) == TAB_ORDER
    assert {spec.name for spec in HIDDEN} == {"overlay_x", "overlay_y", "window_geometry"}


@pytest.mark.parametrize("spec", SPECS, ids=lambda spec: spec.name)
def test_kind_default_and_annotation_agree(spec):
    hint = get_type_hints(Settings)[spec.name]

    if spec.kind == "bool":
        assert hint is bool
        assert type(spec.default) is bool
    elif spec.kind == "int":
        assert hint is int
        assert type(spec.default) is int
    elif spec.kind == "float":
        assert hint is float
        assert type(spec.default) is float
    elif spec.kind == "text":
        assert hint is str
        assert type(spec.default) is str
    else:
        assert spec.kind == "optint"
        assert set(get_args(hint)) == {int, type(None)}
        assert spec.default is None or type(spec.default) is int

    assert getattr(Settings(), spec.name) == spec.default


@pytest.mark.parametrize("spec", SPECS, ids=lambda spec: spec.name)
def test_every_spec_coerces_its_own_default(spec):
    assert spec.coerce(spec.default) == spec.default


def test_coercion_rejects_wrong_types_and_non_finite_numbers():
    with pytest.raises(TypeError):
        SPEC_BY_NAME["volume"].coerce(True)  # bool is not a pedal value
    with pytest.raises(TypeError):
        SPEC_BY_NAME["volume"].coerce("0.5")
    with pytest.raises(TypeError):
        SPEC_BY_NAME["volume"].coerce(float("nan"))
    with pytest.raises(TypeError):
        SPEC_BY_NAME["warn_hz"].coerce(True)
    with pytest.raises(TypeError):
        SPEC_BY_NAME["learning_enabled"].coerce(1)
    with pytest.raises(TypeError):
        SPEC_BY_NAME["game_process"].coerce(1)
    with pytest.raises(TypeError):
        SPEC_BY_NAME["overlay_x"].coerce("1")
    assert SPEC_BY_NAME["overlay_x"].coerce(None) is None


def test_bounds_are_derived_and_only_visible_numbers_are_bounded():
    assert {spec.name: spec.bounds for spec in SPECS if spec.bounds is not None} == LIMITS
    assert {"overlay_x", "overlay_y"} == OPTIONAL_INT

    for spec in SPECS:
        if spec.bounds is not None:
            lo, hi = spec.bounds
            assert lo <= hi
            assert spec.kind in {"int", "float"}
        elif spec.visible and spec.kind in {"int", "float"}:
            raise AssertionError(f"{spec.name}: a visible numeric setting needs bounds")
        assert spec.step > 0
        assert spec.decimals >= 0


def test_visible_settings_have_a_label_and_help():
    for spec in SPECS:
        if not spec.visible:
            continue
        assert spec.label, spec.name
        assert spec.tip, spec.name
        if spec.suffix:
            assert spec.kind in {"int", "float", "optint"}, spec.name
        if spec.special:
            assert spec.kind == "int", spec.name
            assert spec.lo == 0, spec.name


def test_the_schema_version_is_not_a_user_setting():
    from brake_trainer.config import SETTINGS_VERSION

    assert SETTINGS_VERSION == settings_spec.SETTINGS_VERSION
    assert "settings_version" not in DEFAULTS
    assert "settings_version" not in SPEC_BY_NAME
