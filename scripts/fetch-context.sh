#!/usr/bin/env bash
#
# Fetch the optional third-party rules content that this project does not vendor.
#
# `context/DnD-Character-Sheet-Helper/` is a checkout of someone else's repository. It is
# ignored by git and is *not* required for anything the backend does - see
# context/DnD-Character-Sheet-Helper.PROVENANCE.md for what it is and why it is separate.
# This script exists so the directory can be reproduced on a fresh clone without a git
# submodule: a submodule stores only a commit pointer, so a clone that forgets
# `--recurse-submodules` gets an empty directory and no explanation.
#
# The download is pinned to a commit *and* verified against its SHA-256, so a moved tag or
# a re-published tarball fails loudly instead of silently changing the rules text.
#
# Usage:
#   scripts/fetch-context.sh          # fetch into context/DnD-Character-Sheet-Helper
#   scripts/fetch-context.sh --check  # verify what is already there, fetch nothing

set -euo pipefail

REPO="IonasPolitis/DnD-Character-Sheet-Helper"

# Pinned deliberately. A branch name here would make the fetched rules change without a
# commit in this repository, which is the thing the pin exists to prevent.
COMMIT="21c7635b3c6fd7b6f9d15e727dc61d3051c39b00"  # tag 2.0.5-beta
TARBALL_SHA256="cf53241145c057de18f235b6ab3a390cea1438e68a9674d26d290018d2fa0844"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="$ROOT/context/DnD-Character-Sheet-Helper"
URL="https://codeload.github.com/$REPO/tar.gz/$COMMIT"

die() { printf 'error: %s\n' "$*" >&2; exit 1; }

for tool in curl tar sha256sum; do
  command -v "$tool" >/dev/null 2>&1 || die "$tool is required but not installed"
done

# A checksum of the download, not of the extracted tree: the tarball is byte-stable for a
# given commit, so this catches a truncated transfer as well as a changed upstream.
verify_checksum() {
  local archive="$1"
  local actual
  actual="$(sha256sum "$archive" | cut -d' ' -f1)"
  [ "$actual" = "$TARBALL_SHA256" ] \
    || die "checksum mismatch for $REPO@$COMMIT
  expected $TARBALL_SHA256
  got      $actual
The upstream tarball has changed. Check what moved before updating the pin."
}

# Strip the archive's leading `<repo>-<sha>/` directory, and take the whole tree rather
# than only `rulebook/`: the plugin source and its release notes are what identify which
# rules version the JSON was generated from.
extract() {
  tar -xzf "$1" -C "$DEST" --strip-components=1
}

if [ "${1:-}" = "--check" ]; then
  [ -d "$DEST" ] || die "$DEST is missing - run scripts/fetch-context.sh"
  # Cheap integrity signal: the rulebook is the part worth having, and it is large enough
  # that a partial extract is obvious from its file count.
  count="$(find "$DEST/rulebook" -type f 2>/dev/null | wc -l | tr -d ' ')"
  [ "$count" -ge 800 ] \
    || die "$DEST/rulebook has $count files, expected ~826 - the checkout is incomplete"
  printf 'ok: %s (%s rulebook files)\n' "${DEST#"$ROOT"/}" "$count"
  exit 0
fi

[ -f "$ROOT/context/DnD-Character-Sheet-Helper.PROVENANCE.md" ] \
  || die "context/DnD-Character-Sheet-Helper.PROVENANCE.md is missing; it is tracked and must exist before fetching"

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

printf 'fetching %s@%.7s ...\n' "$REPO" "$COMMIT"
curl --fail --location --silent --show-error "$URL" -o "$tmp/archive.tar.gz"

# Verify before destroying anything. Checking after the wipe meant a checksum mismatch
# deleted a good checkout and then refused to replace it.
verify_checksum "$tmp/archive.tar.gz"

# Replace the contents outright. Nothing in here is tracked, so nothing needs preserving -
# the provenance file is a sibling of this directory, not a member of it. `mkdir -p`
# because the directory is gitignored and so does not exist on a fresh clone.
mkdir -p "$DEST"
find "$DEST" -mindepth 1 -maxdepth 1 -exec rm -rf {} +
extract "$tmp/archive.tar.gz"

printf 'ok: fetched into %s\n' "${DEST#"$ROOT"/}"
