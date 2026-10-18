# Publishing to GitHub

FALCON lives in one folder, `~/Workspace/FALCON`, which is also the Git repository connected
to `git@github.com:vinaychittora/FALCON.git` (branch `main`). Its Git history is the clean
public history; the old private development history is archived in `data/private/backups/`
and must never be pushed.

## What goes to GitHub

Only the files in `.public-release-files`. `scripts/release_stage.py` builds that list from
the files Git would track (`.gitignore` keeps `data/`, `models/`, tool folders, validation
reports and manufacturer drawings out), removes anything the release rules forbid (media,
databases, keys, logs, archives outside `hardware/`), and pins binary files (handbook PDFs,
renders, STL, the print pack) by SHA-256 in `.public-release-assets.json`. It then scans every
listed file for access tokens, private keys, credentials in URLs, private network addresses,
precise coordinates and personal paths, and stages exactly that list.

## Publishing a change

```bash
cd ~/Workspace/FALCON
make test
make lint
python3 scripts/release_stage.py
git status
git diff --cached --stat
git commit -m "Describe the change in one line"
git push
```

- `release_stage.py` prints new and removed files and anything it left out. Read the list.
- If the scan reports findings, fix the file (never weaken the check), then run it again.
- `git push` uses this computer's SSH key (`~/.ssh/id_ed25519`), already registered on GitHub.
  Test it with `ssh -T git@github.com`; it answers "Hi vinaychittora!".
- Never use `git push --force`, and never `git add -A` without the staging script.

## Before the first push from a new computer

1. Create a key: `ssh-keygen -t ed25519 -C "your-github-email"` (press Enter for the defaults).
2. Copy the public key: `cat ~/.ssh/id_ed25519.pub`.
3. On GitHub: **Settings → SSH and GPG keys → New SSH key**, paste it, save.
4. Check: `ssh -T git@github.com`.
5. Clone: `git clone git@github.com:vinaychittora/FALCON.git` and run `make install`.

## Extra checks

```bash
python3 scripts/public_release.py check      # scan the listed files again
python3 scripts/public_release.py history    # scan every file in the Git history
```

The history scan should report nothing for this repository. A `.gitignore` cannot remove
something already committed: if a private file was ever committed, stop and ask for help
before pushing, because removing it from history needs a rewrite.

Repository visibility (private or public) is set on GitHub under **Settings → General**;
these steps do not change it.
