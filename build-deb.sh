#!/usr/bin/env bash
# Build dist/agent-usage_<version>_all.deb: a system-wide install of the same
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

SRC=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
# The VERSION file is the only place the release number is written down, so a
# bump is one edit and the .deb, the APT repo and the tag cannot disagree.
VERSION=${VERSION:-$(cat "$SRC/VERSION")}
# Whoever builds the package owns it. Override with the real address before
# handing the .deb to anyone: MAINTAINER="You <you@example.com>" ./build-deb.sh
MAINTAINER=${MAINTAINER:-"agent-usage contributors <agent-usage@users.noreply.github.com>"}
UUID=agent-usage@pgiahuy.github.io
STAGE=$(mktemp -d)
chmod 755 "$STAGE"
trap 'rm -rf "$STAGE"' EXIT

command -v dpkg-deb >/dev/null || { echo "dpkg-deb not found" >&2; exit 1; }
command -v glib-compile-schemas >/dev/null || { echo "glib-compile-schemas not found (libglib2.0-bin)" >&2; exit 1; }

install -d "$STAGE/usr/share/agent-usage" \
           "$STAGE/usr/bin" \
           "$STAGE/usr/share/gnome-shell/extensions/$UUID" \
           "$STAGE/usr/lib/systemd/user" \
           "$STAGE/usr/share/doc/agent-usage" \
           "$STAGE/DEBIAN"

install -d "$STAGE/usr/share/agent-usage/providers"
install -m 644 "$SRC"/daemon/*.py           "$STAGE/usr/share/agent-usage/"
install -m 644 "$SRC"/daemon/providers/*.py "$STAGE/usr/share/agent-usage/providers/"
EXT="$STAGE/usr/share/gnome-shell/extensions/$UUID"
install -d "$EXT/schemas"
install -m 644 "$SRC"/extension/*.js "$SRC"/extension/*.json "$SRC"/extension/*.css "$EXT/"
install -m 644 "$SRC"/extension/schemas/*.gschema.xml "$EXT/schemas/"
# Compiled here rather than in postinst: an extension's schema lives inside
# the extension, so the compiled file is just another file the package owns.
glib-compile-schemas "$EXT/schemas"
install -m 644 "$SRC/systemd/agent-usage.service" "$STAGE/usr/lib/systemd/user/agent-usage.service"
# A .deb install has no repository checkout, so the diagnostic the readme and
# the installer both point at has to travel with the package.
install -m 755 "$SRC/tools/doctor.sh" "$STAGE/usr/share/agent-usage/doctor.sh"
install -m 644 "$SRC/README.md"           "$STAGE/usr/share/doc/agent-usage/README.md"
# The readme links to these, so they travel with it or the links dead-end.
install -m 644 "$SRC/CONTRIBUTING.md" "$SRC/SECURITY.md" "$SRC/CODE_OF_CONDUCT.md" \
                                          "$STAGE/usr/share/doc/agent-usage/"
# Debian looks for the upstream changelog under this exact name.
install -m 644 "$SRC/CHANGELOG.md"        "$STAGE/usr/share/doc/agent-usage/changelog.md"
install -d "$STAGE/usr/share/doc/agent-usage/docs"
install -m 644 "$SRC"/docs/*.md           "$STAGE/usr/share/doc/agent-usage/docs/"

# The launcher is the one file that has to know where things landed.
sed -e "s|@PYTHON@|/usr/bin/python3|" -e "s|@APP_DIR@|/usr/share/agent-usage|" \
    "$SRC/bin/agent-usage.in" > "$STAGE/usr/bin/agent-usage"
chmod 755 "$STAGE/usr/bin/agent-usage"

# The unit is started per user, so %h resolves to that user's home; the
# launcher is on PATH now, unlike the $HOME install.
sed -i 's|ExecStart=%h/.local/bin/agent-usage --daemon|ExecStart=/usr/bin/agent-usage --daemon|' \
    "$STAGE/usr/lib/systemd/user/agent-usage.service"

cat > "$STAGE/usr/share/doc/agent-usage/copyright" <<EOF
Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/
Upstream-Name: agent-usage

Files: *
Copyright: 2026 agent-usage contributors
License: MIT
$(sed 's/^$/./; s/^/ /' "$SRC/LICENSE")
EOF

cat > "$STAGE/DEBIAN/control" <<EOF
Package: agent-usage
Version: $VERSION
Section: utils
Priority: optional
Architecture: all
Depends: python3 (>= 3.8)
Recommends: gnome-shell (>= 48)
Maintainer: $MAINTAINER
Description: Claude Code and Kimi Code usage in the GNOME top bar
 Shows how much of each plan is spent, when it resets, and how many tokens
 went out today and over the week. Quota percentages come from each
 provider's own API; token counts are parsed from the local session logs.
 .
 A collector runs as a systemd user service and writes a small JSON file;
 a GNOME Shell extension reads that file and draws it. The terminal command
 "agent-usage" prints the same reading without GNOME.
EOF

cat > "$STAGE/DEBIAN/postinst" <<'EOF'
#!/bin/sh
set -e
if [ "$1" = configure ] && command -v systemctl >/dev/null 2>&1; then
    # Enables the user service for every user, without starting anything now:
    # it is bound to graphical-session.target and starts with the next login.
    systemctl --global enable agent-usage.service >/dev/null 2>&1 || true
fi
cat <<'MSG'
agent-usage installed.

Each user turns the panel indicator on for their own session:

    gnome-extensions enable agent-usage@pgiahuy.github.io

A running GNOME session will not see a newly installed extension until the
user logs out and back in. Without GNOME, "agent-usage" still prints the table.
MSG
EOF
chmod 755 "$STAGE/DEBIAN/postinst"

cat > "$STAGE/DEBIAN/prerm" <<'EOF'
#!/bin/sh
set -e
if [ "$1" = remove ] && command -v systemctl >/dev/null 2>&1; then
    systemctl --global disable agent-usage.service >/dev/null 2>&1 || true
fi
EOF
chmod 755 "$STAGE/DEBIAN/prerm"

install -d "$SRC/dist"
OUT="$SRC/dist/agent-usage_${VERSION}_all.deb"
dpkg-deb --build --root-owner-group "$STAGE" "$OUT" >/dev/null
echo "$OUT"
