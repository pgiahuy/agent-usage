# Packaging

The per-user `./install.sh` in the README is the normal route. This page is
for a shared machine, or for installing with the package manager.

## System-wide (.deb)

```sh
./build-deb.sh                              # -> dist/agent-usage_1.0.0_all.deb
sudo apt install ./dist/agent-usage_1.0.0_all.deb
```

The package puts the collector in `/usr/share/agent-usage`, the command in
`/usr/bin`, the extension in `/usr/share/gnome-shell/extensions`, and the user
service in `/usr/lib/systemd/user`. `postinst` runs `systemctl --global enable
agent-usage.service`, so every user's session starts the collector at login.

The extension stays per-user, because GNOME extensions are per-user by nature:

```sh
gnome-extensions enable agent-usage@pgiahuy.github.io   # once per user, after one logout
```

Do not run `install.sh` as well, or you end up with two copies, one in
`/usr` and one in `$HOME`, and the `$HOME` one wins on `PATH`.

When the panel indicator does not appear, the diagnostic lands with the
package, since there is no checkout to run it from:

```sh
/usr/share/agent-usage/doctor.sh
```

Removal is `sudo apt remove agent-usage`. That leaves each user's
`~/.cache/agent-usage`, which is just cached readings and icons.

## extensions.gnome.org

The store is where most people look for a GNOME extension, and it takes a zip
rather than a repository. The schema goes in as source, not compiled: the
store compiles it, which is why `gschemas.compiled` is not in the tree and why
the installer and `build-deb.sh` each compile their own.

```sh
cd extension
gnome-extensions pack . \
  --extra-source="$(basename "$(ls ui-*.js | sort -V | tail -1)")" \
  --extra-source=prefs.js \
  --schema=schemas/org.gnome.shell.extensions.agent-usage.gschema.xml
```

Two things to settle before submitting.

The loader has to go. `extension.js` picks its entry point by listing the
directory and importing the highest-numbered `ui-<n>.js`. Store review is a
person reading the zip, and the rule is that the code they read is the code
that runs, so anything shaped like finding a file and loading it is refused.
Replacing it with a static `import` of a single `ui.js` is the fix, and it
costs the no-logout upgrade in `install.sh`, which exists only because that
numbering gives the shell a URI it has not cached yet. A store install
upgrades at the next login either way, so the two routes want different
things here.

`shell-version` has to cover the shells you intend to support. The store shows
an extension only to the versions listed, and the shell refuses to load it
anywhere else.

## `apt install agent-usage`, from your own repository

For plain `apt install agent-usage`, and `apt upgrade` picking up new versions
along with everything else, the package has to live in a repository the
machine trusts. `build-apt-repo.sh` builds one into `docs/apt/`, which GitHub
Pages can serve directly from the `main` branch (Settings → Pages → Source:
main, folder `/docs`).

Once, to publish:

```sh
gpg --quick-generate-key "Your Name <you@example.com>" default default 5y
gpg --list-secret-keys --keyid-format long     # the id after "sec ... /"
AGENT_USAGE_GPG_KEY=<that id> ./build-apt-repo.sh
git add docs/apt && git commit -m "publish 1.0.0" && git push
```

The signature is the point of the key: it is how apt knows the package came
from you and not from whoever else could reach the host. Skip it and every
user has to write `[trusted=yes]` in their source line, which switches that
check off.

The script signs only with the key `AGENT_USAGE_GPG_KEY` names, never the
first one in the keyring: the signing key's public half, with its name and
email, is published in `docs/apt/agent-usage.asc`. Use a key made for this.

Then each user adds the source once. The address below is an example built
from this repository's own name: nothing is published there, and the commands
only work once you have run the steps above against a repository of your own.

```sh
sudo install -d /etc/apt/keyrings
curl -fsSL https://pgiahuy.github.io/agent-usage/apt/agent-usage.asc \
  | sudo tee /etc/apt/keyrings/agent-usage.asc > /dev/null
echo "deb [signed-by=/etc/apt/keyrings/agent-usage.asc] https://pgiahuy.github.io/agent-usage/apt stable main" \
  | sudo tee /etc/apt/sources.list.d/agent-usage.list
sudo apt update && sudo apt install agent-usage
```

Shipping a new version is `VERSION=1.1.0 ./build-apt-repo.sh` and another
commit. Note that the repository URL must not contain spaces: apt splits
`sources.list` lines on whitespace, so a path with one in it fails with a
confusing "Release file not found".

The other route is a Launchpad PPA, which builds from source you upload and
gives Ubuntu users `add-apt-repository ppa:you/agent-usage`. It needs a Launchpad
account and a signed source upload; the `.deb` here is the same artifact.
