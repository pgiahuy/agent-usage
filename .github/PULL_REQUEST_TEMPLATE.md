## What this changes

<!-- One or two sentences. Why the change is right, not what the diff says. -->

Closes #

## What I ran

- [ ] `python3 -m unittest discover -s tests`
- [ ] `ruff check daemon tests`
- [ ] `shellcheck install.sh uninstall.sh build-deb.sh build-apt-repo.sh tools/doctor.sh bin/agent-usage.in`
- [ ] `./install.sh` and looked at the real panel
- [ ] Added or updated a test, if this touches the collector

## Anything you are unsure about

<!-- Decisions worth a second opinion. Say so rather than hiding it. -->

## Checklist

- [ ] One concern per commit, subject in the imperative and lowercase
- [ ] No em-dashes, in code, comments, docs or commit messages
- [ ] No number is shown that a provider did not give
- [ ] Documentation updated if behaviour or a setting changed
