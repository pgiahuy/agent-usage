# Packaging

`./install.sh` from the README installs for one user. The routes below are for
everyone on a machine, or for a package manager.

## System-wide (.deb)

```sh
./build-deb.sh                                  # -> dist/agent-usage_1.0.0_all.deb
sudo apt install ./dist/agent-usage_1.0.0_all.deb
```

The package installs the collector in `/usr/share/agent-usage`, the command in
`/usr/bin`, the extension in `/usr/share/gnome-shell/extensions` and the user
service in `/usr/lib/systemd/user`. Its `postinst` enables the service for
every user, so the collector starts at each login.

Each user then enables the extension once, after logging out and back in:

```sh
gnome-extensions enable agent-usage@pgiahuy.github.io
```

Do not also run `install.sh`. You would get a second copy in `$HOME`, which
takes precedence.

After upgrading the package, a collector that is already running keeps the old
code until it restarts: `systemctl --user restart agent-usage`, or the next
login.

If the indicator does not appear, run `/usr/share/agent-usage/doctor.sh`.

To remove it: `sudo apt remove agent-usage`. Each user keeps
`~/.cache/agent-usage`, the extension's settings in dconf, and its entry in the
list of enabled extensions.

## APT repository

`build-apt-repo.sh` builds a repository in `docs/apt/`, signed when
`AGENT_USAGE_GPG_KEY` names a key. GitHub Pages can serve it from the `main`
branch (Settings, Pages, source `main`, folder `/docs`), and users then get the
package and its updates through `apt`.

To publish:

```sh
gpg --quick-generate-key "Your Name <you@example.com>" default default 5y
gpg --list-secret-keys --keyid-format long      # the id after "sec .../"
AGENT_USAGE_GPG_KEY=<that id> ./build-apt-repo.sh
git add docs/apt && git commit -m "publish 1.0.0" && git push
```

The script publishes the key's public half, name and email included, as
`docs/apt/agent-usage.asc`, so use a key made for this. Without a signature,
users have to mark the source `[trusted=yes]`, which turns off apt's check that
the package came from you.

Each user then adds the source. The address below follows this repository's
name as an example; nothing is published there.

```sh
sudo install -d /etc/apt/keyrings
curl -fsSL https://pgiahuy.github.io/agent-usage/apt/agent-usage.asc \
  | sudo tee /etc/apt/keyrings/agent-usage.asc > /dev/null
echo "deb [signed-by=/etc/apt/keyrings/agent-usage.asc] https://pgiahuy.github.io/agent-usage/apt stable main" \
  | sudo tee /etc/apt/sources.list.d/agent-usage.list
sudo apt update && sudo apt install agent-usage
```

To publish a new version, run `build-apt-repo.sh` again and commit. The
repository URL must not contain spaces: apt splits `sources.list` lines on
whitespace and then reports that the repository has no Release file.

## extensions.gnome.org

The store takes a zip. `gnome-extensions pack` includes `prefs.js` and the
`schemas/` folder on its own; the UI module has to be named:

```sh
cd extension
gnome-extensions pack . --extra-source="$(ls ui-*.js | sort -V | tail -1)"
```

`gschemas.compiled` is not in the repository because `install.sh` and
`build-deb.sh` each compile it.

One thing to settle before submitting: the loader. `extension.js` imports
whichever `ui-<n>.js` has the highest number, which is what lets `install.sh`
upgrade without a logout. The review guidelines say nothing about a dynamic
import of a computed path, so whether review accepts it is not known. A static
import of a single `ui.js` would settle the question, at the cost of a logout
on every upgrade. Issue #19 tracks the decision.
