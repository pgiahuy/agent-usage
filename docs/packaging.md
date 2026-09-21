# Packaging

The per-user `./install.sh` in the README is the normal route. This page is
for a shared machine, or for installing with the package manager.

## System-wide (.deb)

```sh
./build-deb.sh                              # -> dist/ai-usage_1.0.0_all.deb
sudo apt install ./dist/ai-usage_1.0.0_all.deb
```

The package puts the collector in `/usr/share/ai-usage`, the command in
`/usr/bin`, the extension in `/usr/share/gnome-shell/extensions`, and the user
service in `/usr/lib/systemd/user`. `postinst` runs `systemctl --global enable
ai-usage.service`, so every user's session starts the collector at login.

The extension stays per-user, because GNOME extensions are per-user by nature:

```sh
gnome-extensions enable ai-usage@pgiahuy.github.io   # once per user, after one logout
```

Do not run `install.sh` as well, or you end up with two copies, one in
`/usr` and one in `$HOME`, and the `$HOME` one wins on `PATH`.

Removal is `sudo apt remove ai-usage`. That leaves each user's
`~/.cache/ai-usage`, which is just cached readings and icons.

## `apt install ai-usage`, from your own repository

For plain `apt install ai-usage`, and `apt upgrade` picking up new versions
along with everything else, the package has to live in a repository the
machine trusts. `build-apt-repo.sh` builds one into `docs/apt/`, which GitHub
Pages can serve directly from the `main` branch (Settings → Pages → Source:
main, folder `/docs`).

Once, to publish:

```sh
gpg --quick-generate-key "Your Name <you@example.com>" default default 5y
./build-apt-repo.sh
git add docs/apt && git commit -m "publish 1.0.0" && git push
```

The signature is the point of the key: it is how apt knows the package came
from you and not from whoever else could reach the host. Skip it and every
user has to write `[trusted=yes]` in their source line, which switches that
check off.

Then each user adds the source once:

```sh
sudo install -d /etc/apt/keyrings
curl -fsSL https://pgiahuy.github.io/ai-usage/apt/ai-usage.asc \
  | sudo tee /etc/apt/keyrings/ai-usage.asc > /dev/null
echo "deb [signed-by=/etc/apt/keyrings/ai-usage.asc] https://pgiahuy.github.io/ai-usage/apt stable main" \
  | sudo tee /etc/apt/sources.list.d/ai-usage.list
sudo apt update && sudo apt install ai-usage
```

Shipping a new version is `VERSION=1.1.0 ./build-apt-repo.sh` and another
commit. Note that the repository URL must not contain spaces: apt splits
`sources.list` lines on whitespace, so a path with one in it fails with a
confusing "Release file not found".

The other route is a Launchpad PPA, which builds from source you upload and
gives Ubuntu users `add-apt-repository ppa:you/ai-usage`. It needs a Launchpad
account and a signed source upload; the `.deb` here is the same artifact.
