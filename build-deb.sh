#!/usr/bin/env bash
# Build dist/ai-usage_<version>_all.deb: a system-wide install of the same
# files install.sh puts in $HOME.
#
# The split matters: a .deb owns /usr, but a GNOME extension and a systemd user
# service are per-user things. So the package ships them where every user can
# see them (/usr/share/gnome-shell/extensions, /usr/lib/systemd/user) and each
# user still turns them on for their own session. postinst does what it can:
# `systemctl --global enable` covers the service for all users at once.
set -euo pipefail
# dpkg wants 0755 directories; mktemp -d makes 0700 and a lax umask makes 0775.
umask 022

VERSION=${VERSION:-1.0.0}
# Whoever builds the package owns it. Override with the real address before
# handing the .deb to anyone: MAINTAINER="You <you@example.com>" ./build-deb.sh
MAINTAINER=${MAINTAINER:-"ai-usage contributors <ai-usage@users.noreply.github.com>"}
UUID=ai-usage@pgiahuy.github.io
SRC=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
STAGE=$(mktemp -d)
chmod 755 "$STAGE"
trap 'rm -rf "$STAGE"' EXIT

command -v dpkg-deb >/dev/null || { echo "dpkg-deb not found" >&2; exit 1; }

install -d "$STAGE/usr/share/ai-usage" \
           "$STAGE/usr/bin" \
           "$STAGE/usr/share/gnome-shell/extensions/$UUID" \
           "$STAGE/usr/lib/systemd/user" \
           "$STAGE/usr/share/doc/ai-usage" \
           "$STAGE/DEBIAN"

install -m 644 "$SRC"/daemon/*.py         "$STAGE/usr/share/ai-usage/"
install -m 644 "$SRC"/extension/*         "$STAGE/usr/share/gnome-shell/extensions/$UUID/"
install -m 644 "$SRC/systemd/ai-usage.service" "$STAGE/usr/lib/systemd/user/ai-usage.service"
install -m 644 "$SRC/README.md"           "$STAGE/usr/share/doc/ai-usage/README.md"
install -d "$STAGE/usr/share/doc/ai-usage/docs"
install -m 644 "$SRC"/docs/*.md           "$STAGE/usr/share/doc/ai-usage/docs/"

# The launcher is the one file that has to know where things landed.
sed -e "s|@PYTHON@|/usr/bin/python3|" -e "s|@APP_DIR@|/usr/share/ai-usage|" \
    "$SRC/bin/ai-usage.in" > "$STAGE/usr/bin/ai-usage"
chmod 755 "$STAGE/usr/bin/ai-usage"

# The unit is started per user, so %h resolves to that user's home; the
# launcher is on PATH now, unlike the $HOME install.
sed -i 's|ExecStart=%h/.local/bin/ai-usage --daemon|ExecStart=/usr/bin/ai-usage --daemon|' \
    "$STAGE/usr/lib/systemd/user/ai-usage.service"

cat > "$STAGE/usr/share/doc/ai-usage/copyright" <<EOF
Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/
Upstream-Name: ai-usage

Files: *
Copyright: 2026 ai-usage contributors
License: MIT
$(sed 's/^$/./; s/^/ /' "$SRC/LICENSE")
EOF

cat > "$STAGE/DEBIAN/control" <<EOF
Package: ai-usage
Version: $VERSION
Section: utils
Priority: optional
Architecture: all
Depends: python3 (>= 3.8)
Recommends: gnome-shell (>= 48)
Suggests: python3-gi
Maintainer: $MAINTAINER
Description: Claude Code and Kimi Code usage in the GNOME top bar
 Shows how much of each plan is spent, when it resets, and how many tokens
 went out today and over the week. Quota percentages come from each
 provider's own API; token counts are parsed from the local session logs.
 .
 A collector runs as a systemd user service and writes a small JSON file;
 a GNOME Shell extension reads that file and draws it. The terminal command
 "ai-usage" prints the same reading without GNOME.
EOF

cat > "$STAGE/DEBIAN/postinst" <<'EOF'
#!/bin/sh
set -e
if [ "$1" = configure ] && command -v systemctl >/dev/null 2>&1; then
    # Enables the user service for every user, without starting anything now:
    # it is bound to graphical-session.target and starts with the next login.
    systemctl --global enable ai-usage.service >/dev/null 2>&1 || true
fi
cat <<'MSG'
ai-usage installed.

Each user turns the panel indicator on for their own session:

    gnome-extensions enable ai-usage@pgiahuy.github.io

A running GNOME session will not see a newly installed extension until the
user logs out and back in. Without GNOME, "ai-usage" still prints the table.
MSG
EOF
chmod 755 "$STAGE/DEBIAN/postinst"

cat > "$STAGE/DEBIAN/prerm" <<'EOF'
#!/bin/sh
set -e
if [ "$1" = remove ] && command -v systemctl >/dev/null 2>&1; then
    systemctl --global disable ai-usage.service >/dev/null 2>&1 || true
fi
EOF
chmod 755 "$STAGE/DEBIAN/prerm"

install -d "$SRC/dist"
OUT="$SRC/dist/ai-usage_${VERSION}_all.deb"
dpkg-deb --build --root-owner-group "$STAGE" "$OUT" >/dev/null
echo "$OUT"
