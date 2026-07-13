from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import time
import tomllib
import urllib.error
import urllib.request


def project_metadata(project_file: Path) -> tuple[str, str]:
    project = tomllib.loads(project_file.read_text(encoding="utf-8"))["project"]
    return str(project["name"]), str(project["version"])


def _expected_patterns(name: str, version: str) -> dict[str, re.Pattern[str]]:
    wheel_name = re.sub(r"[-_.]+", "_", name)
    escaped_name = re.escape(wheel_name)
    escaped_version = re.escape(version)
    return {
        "source distribution": re.compile(
            rf"^{escaped_name}-{escaped_version}\.tar\.gz$"
        ),
        "universal wheel": re.compile(
            rf"^{escaped_name}-{escaped_version}-py3-none-any\.whl$"
        ),
        "arm64_v8a Android wheel": re.compile(
            rf"^{escaped_name}-{escaped_version}-cp314-cp314-android_[^-]*arm64_v8a\.whl$"
        ),
        "x86_64 Android wheel": re.compile(
            rf"^{escaped_name}-{escaped_version}-cp314-cp314-android_[^-]*x86_64\.whl$"
        ),
    }


def validate_distribution_names(
    name: str,
    version: str,
    filenames: set[str],
    *,
    exact: bool = True,
) -> set[str]:
    for label, pattern in _expected_patterns(name, version).items():
        matches = sorted(filename for filename in filenames if pattern.fullmatch(filename))
        if len(matches) != 1:
            raise ValueError(
                f"expected one {label} for {name} {version}; found {matches or 'none'}"
            )
    if exact and len(filenames) != 4:
        raise ValueError(
            f"expected exactly four release distributions; found {sorted(filenames)}"
        )
    return filenames


def fetch_release_filenames(name: str, version: str) -> set[str]:
    url = f"https://pypi.org/pypi/{name}/{version}/json"
    try:
        with urllib.request.urlopen(url, timeout=30) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return set()
        raise
    return {str(item["filename"]) for item in payload.get("urls", ())}


def prepare_upload(
    dist_dir: Path,
    upload_dir: Path,
    existing_filenames: set[str],
) -> tuple[Path, ...]:
    shutil.rmtree(upload_dir, ignore_errors=True)
    upload_dir.mkdir(parents=True)
    missing = tuple(
        path
        for path in sorted(dist_dir.iterdir())
        if path.is_file()
        and (path.suffix == ".whl" or path.name.endswith(".tar.gz"))
        and path.name not in existing_filenames
    )
    for source in missing:
        shutil.copy2(source, upload_dir / source.name)
    return missing


def verify_release(
    name: str,
    version: str,
    *,
    attempts: int = 12,
    retry_delay: float = 5.0,
) -> set[str]:
    if attempts < 1:
        raise ValueError("attempts must be >= 1")
    last_error: ValueError | None = None
    for attempt in range(attempts):
        filenames = fetch_release_filenames(name, version)
        try:
            return validate_distribution_names(name, version, filenames, exact=False)
        except ValueError as exc:
            last_error = exc
            if attempt + 1 < attempts:
                time.sleep(retry_delay)
    raise RuntimeError(f"PyPI release is incomplete: {last_error}") from last_error


def _write_outputs(path: Path | None, *, version: str, publish: bool) -> None:
    if path is None:
        return
    with path.open("a", encoding="utf-8") as output:
        print(f"version={version}", file=output)
        print(f"publish={'true' if publish else 'false'}", file=output)


def _prepare(args: argparse.Namespace) -> int:
    name, version = project_metadata(args.project_file)
    filenames = {
        path.name
        for path in args.dist_dir.iterdir()
        if path.is_file() and (path.suffix == ".whl" or path.name.endswith(".tar.gz"))
    }
    validate_distribution_names(name, version, filenames)
    existing = fetch_release_filenames(name, version)
    missing = prepare_upload(args.dist_dir, args.upload_dir, existing)
    _write_outputs(args.github_output, version=version, publish=bool(missing))
    state = "publishing " + ", ".join(path.name for path in missing) if missing else "already complete"
    print(f"{name} {version}: {state}")
    return 0


def _verify(args: argparse.Namespace) -> int:
    name, version = project_metadata(args.project_file)
    filenames = verify_release(name, version)
    print(f"{name} {version}: verified {len(filenames)} PyPI files")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare and verify a Luvatrix PyPI release")
    parser.add_argument("--project-file", type=Path, default=Path("pyproject.toml"))
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare = subparsers.add_parser("prepare")
    prepare.add_argument("--dist-dir", type=Path, default=Path("dist"))
    prepare.add_argument("--upload-dir", type=Path, default=Path("upload-dist"))
    prepare.add_argument(
        "--github-output",
        type=Path,
        default=Path(os.environ["GITHUB_OUTPUT"]) if "GITHUB_OUTPUT" in os.environ else None,
    )
    prepare.set_defaults(handler=_prepare)

    verify = subparsers.add_parser("verify")
    verify.set_defaults(handler=_verify)

    args = parser.parse_args()
    return int(args.handler(args))


if __name__ == "__main__":
    raise SystemExit(main())
