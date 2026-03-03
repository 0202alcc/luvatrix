#!/usr/bin/env bash
set -euo pipefail

BASE_REF="${BASE_REF:-origin/main}"
PATH_SCOPE="${PATH_SCOPE:-ops/planning}"
COMMIT_MSG="${COMMIT_MSG:-chore(planning): sync ops/planning from origin/main}"
DO_FETCH="${DO_FETCH:-1}"

current_branch="$(git rev-parse --abbrev-ref HEAD)"
if [[ "${current_branch}" == "main" ]]; then
  echo "error: run sync on a milestone branch, not on main" >&2
  exit 2
fi

if [[ "${DO_FETCH}" == "1" ]]; then
  git fetch origin main
fi

if ! git rev-parse --verify "${BASE_REF}" >/dev/null 2>&1; then
  echo "error: base ref not found: ${BASE_REF}" >&2
  exit 2
fi

if [[ -n "$(git status --porcelain -- "${PATH_SCOPE}")" ]]; then
  echo "error: local changes detected in ${PATH_SCOPE}; commit/stash first" >&2
  exit 2
fi

if git diff --quiet "${BASE_REF}...HEAD" -- "${PATH_SCOPE}"; then
  echo "[OK] ${PATH_SCOPE} already in sync with ${BASE_REF}"
  exit 0
fi

git restore --source "${BASE_REF}" -- "${PATH_SCOPE}"

if [[ -z "$(git status --porcelain -- "${PATH_SCOPE}")" ]]; then
  echo "[OK] no sync changes produced after restore"
  exit 0
fi

git add "${PATH_SCOPE}"
git commit -m "${COMMIT_MSG}"
echo "[OK] synced ${PATH_SCOPE} from ${BASE_REF} on branch ${current_branch}"
