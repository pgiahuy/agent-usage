#!/usr/bin/env bash
# Build an APT repository under docs/apt/ so that, once the repo is served over
# HTTPS (GitHub Pages will do), users can install with plain `apt install
# agent-usage` and get upgrades from `apt upgrade` like any other package.
#
# The layout is the standard one apt expects:
#
#   docs/apt/pool/main/agent-usage_<version>_all.deb     the package
#   docs/apt/dists/stable/main/binary-all/Packages    its index
#   docs/apt/dists/stable/Release                     checksums of the indexes
#   docs/apt/dists/stable/{InRelease,Release.gpg}     signatures over Release
#   docs/apt/agent-usage.asc                             the public key
#
# Signing is what makes `apt update` accept the repo without `trusted=yes`.
# With no secret key present the script still builds a working unsigned repo
# and prints how to make a key.
set -euo pipefail
umask 022

SRC=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
VERSION=${VERSION:-1.0.0}
REPO="$SRC/docs/apt"
DIST="$REPO/dists/stable"
POOL="$REPO/pool/main"

command -v dpkg-scanpackages >/dev/null || { echo "need dpkg-dev (dpkg-scanpackages)" >&2; exit 1; }

DEB="$SRC/dist/agent-usage_${VERSION}_all.deb"
[ -f "$DEB" ] || VERSION=$VERSION "$SRC/build-deb.sh" >/dev/null
[ -f "$DEB" ] || { echo "missing $DEB" >&2; exit 1; }

rm -rf "$REPO"
install -d "$POOL" "$DIST/main/binary-all"
install -m 644 "$DEB" "$POOL/"

# Paths inside Packages must be relative to the repository root, which is why
# this runs from $REPO rather than anywhere else.
( cd "$REPO" && dpkg-scanpackages --multiversion pool/main /dev/null ) \
    > "$DIST/main/binary-all/Packages" 2>/dev/null
gzip -9nc "$DIST/main/binary-all/Packages" > "$DIST/main/binary-all/Packages.gz"

# Release, written by hand: apt-ftparchive lives in apt-utils, which is not
# installed everywhere, and the file is only a header plus two checksum lists.
checksums() {
  local prog=$1
  cd "$DIST"
  for f in main/binary-all/Packages main/binary-all/Packages.gz; do
    printf ' %s %16d %s\n' "$($prog "$f" | cut -d' ' -f1)" "$(stat -c%s "$f")" "$f"
  done
}
{
  echo "Origin: agent-usage"
  echo "Label: agent-usage"
  echo "Suite: stable"
  echo "Codename: stable"
  echo "Architectures: all"
  echo "Components: main"
  echo "Description: Claude Code and Kimi Code usage in the GNOME top bar"
  echo "Date: $(date -Ru)"
  echo "MD5Sum:"
  checksums md5sum
  echo "SHA256:"
  checksums sha256sum
} > "$DIST/Release"

# --- signing --------------------------------------------------------------
KEY=${AGENT_USAGE_GPG_KEY:-$(gpg --list-secret-keys --with-colons 2>/dev/null \
                          | awk -F: '/^sec:/ {print $5; exit}')}
if [ -n "${KEY:-}" ]; then
  rm -f "$DIST/Release.gpg" "$DIST/InRelease"
  gpg --default-key "$KEY" --batch --yes --armor --detach-sign \
      -o "$DIST/Release.gpg" "$DIST/Release"
  gpg --default-key "$KEY" --batch --yes --clearsign \
      -o "$DIST/InRelease" "$DIST/Release"
  gpg --armor --export "$KEY" > "$REPO/agent-usage.asc"
  echo "signed with $KEY"
else
  cat >&2 <<'EOF'
No secret GPG key found, so the repository is unsigned: apt will refuse it
unless the source line says [trusted=yes], which turns off the check that the
package came from you. To sign it, make a key once and re-run this script:

    gpg --quick-generate-key "Your Name <you@example.com>" default default 5y
    ./build-apt-repo.sh

EOF
fi

echo "$REPO"
