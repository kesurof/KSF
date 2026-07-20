#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
version="$(tr -d '[:space:]' < "${ROOT_DIR}/VERSION")"

if ! [[ "${version}" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  printf 'ECHEC: VERSION doit respecter MAJEUR.MINEUR.CORRECTIF.\n' >&2
  exit 1
fi

if ! grep -qF "## [${version}]" "${ROOT_DIR}/CHANGELOG.md"; then
  printf 'ECHEC: CHANGELOG.md ne contient pas la version %s.\n' "${version}" >&2
  exit 1
fi

printf 'OK: VERSION %s referencee dans CHANGELOG.md\n' "${version}"
