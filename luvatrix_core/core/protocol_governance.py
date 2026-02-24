from __future__ import annotations

from dataclasses import dataclass


CURRENT_PROTOCOL_VERSION = "1"
SUPPORTED_PROTOCOL_VERSIONS = {"1"}
DEPRECATED_PROTOCOL_VERSIONS: set[str] = set()


@dataclass(frozen=True)
class ProtocolCompatibility:
    accepted: bool
    warning: str | None


def check_protocol_compatibility(
    manifest_version: str,
    min_runtime_version: str | None = None,
    max_runtime_version: str | None = None,
) -> ProtocolCompatibility:
    if manifest_version not in SUPPORTED_PROTOCOL_VERSIONS:
        return ProtocolCompatibility(
            accepted=False,
            warning=f"unsupported app protocol_version={manifest_version}",
        )
    cur = int(CURRENT_PROTOCOL_VERSION)
    if min_runtime_version is not None and cur < int(min_runtime_version):
        return ProtocolCompatibility(
            accepted=False,
            warning=(
                f"runtime protocol {CURRENT_PROTOCOL_VERSION} is below app min_runtime_protocol_version "
                f"{min_runtime_version}"
            ),
        )
    if max_runtime_version is not None and cur > int(max_runtime_version):
        return ProtocolCompatibility(
            accepted=False,
            warning=(
                f"runtime protocol {CURRENT_PROTOCOL_VERSION} is above app max_runtime_protocol_version "
                f"{max_runtime_version}"
            ),
        )
    if manifest_version in DEPRECATED_PROTOCOL_VERSIONS:
        return ProtocolCompatibility(
            accepted=True,
            warning=f"app protocol_version={manifest_version} is deprecated",
        )
    return ProtocolCompatibility(accepted=True, warning=None)
