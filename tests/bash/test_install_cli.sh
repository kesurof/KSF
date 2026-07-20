#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TMP_HOME="$(mktemp -d "${TMPDIR:-/tmp}/ksf-cli-home.XXXXXX")"
trap 'rm -rf "${TMP_HOME}"' EXIT

fail() {
  printf 'ECHEC: %s\n' "$*" >&2
  exit 1
}

output="${TMP_HOME}/install-cli.out"
HOME="${TMP_HOME}" "${ROOT_DIR}/ksf.sh" install-cli --dry-run --yes >"${output}" 2>&1

[ ! -e "${TMP_HOME}/.local" ] || fail 'install-cli --dry-run a cree ~/.local.'
[ ! -e "${TMP_HOME}/.profile" ] || fail 'install-cli --dry-run a modifie ~/.profile.'
[ ! -e "${TMP_HOME}/.bashrc" ] || fail 'install-cli --dry-run a modifie ~/.bashrc.'
grep -q '\[DRY-RUN\]' "${output}" || fail 'Le plan install-cli dry-run est absent.'

printf 'OK: install-cli dry-run sans ecriture dans HOME\n'
