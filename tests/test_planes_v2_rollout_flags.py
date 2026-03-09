from __future__ import annotations

from luvatrix_ui.planes_runtime import resolve_planes_v2_rollout_flags


def test_planes_v2_flags_default_enabled_without_rollback(monkeypatch) -> None:
    monkeypatch.delenv("LUVATRIX_PLANES_V2_SCHEMA", raising=False)
    monkeypatch.delenv("LUVATRIX_PLANES_V2_COMPILER", raising=False)
    monkeypatch.delenv("LUVATRIX_PLANES_V2_RUNTIME", raising=False)
    monkeypatch.delenv("LUVATRIX_PLANES_V2_ROLLBACK_COMPAT_ADAPTER_DEFAULT", raising=False)

    flags = resolve_planes_v2_rollout_flags()
    assert flags.schema_enabled is True
    assert flags.compiler_enabled is True
    assert flags.runtime_enabled is True
    assert flags.rollback_to_compat_adapter_default is False


def test_planes_v2_flags_allow_individual_toggle(monkeypatch) -> None:
    monkeypatch.setenv("LUVATRIX_PLANES_V2_SCHEMA", "1")
    monkeypatch.setenv("LUVATRIX_PLANES_V2_COMPILER", "0")
    monkeypatch.setenv("LUVATRIX_PLANES_V2_RUNTIME", "1")
    monkeypatch.delenv("LUVATRIX_PLANES_V2_ROLLBACK_COMPAT_ADAPTER_DEFAULT", raising=False)

    flags = resolve_planes_v2_rollout_flags()
    assert flags.schema_enabled is True
    assert flags.compiler_enabled is False
    assert flags.runtime_enabled is True
    assert flags.rollback_to_compat_adapter_default is False


def test_planes_v2_rollout_rollback_forces_compat_adapter_default(monkeypatch) -> None:
    monkeypatch.setenv("LUVATRIX_PLANES_V2_SCHEMA", "1")
    monkeypatch.setenv("LUVATRIX_PLANES_V2_COMPILER", "1")
    monkeypatch.setenv("LUVATRIX_PLANES_V2_RUNTIME", "1")
    monkeypatch.setenv("LUVATRIX_PLANES_V2_ROLLBACK_COMPAT_ADAPTER_DEFAULT", "1")

    flags = resolve_planes_v2_rollout_flags()
    assert flags.schema_enabled is False
    assert flags.compiler_enabled is False
    assert flags.runtime_enabled is False
    assert flags.rollback_to_compat_adapter_default is True
