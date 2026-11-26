# Publishing to GitHub

The public repository is `git@github.com:vinaychittora/FALCON.git`. Its branch `main` is
protected: changes reach it only through a pull request, which the owner opens and merges.

## What goes to GitHub

Only the files in `.public-release-files`. Binary files (handbook PDFs, renders, STL, the
print pack, the icons) are pinned by SHA-256 in `.public-release-assets.json`.

`python3 scripts/public_release.py check` reads that list and scans every listed file for
access tokens, private keys, credentials in URLs, private network addresses, precise
coordinates and personal paths, and checks every binary against its pin. It must pass
before anything is published. If it reports findings, fix the file; never weaken the check.

`python3 scripts/release_stage.py` refreshes the list from the files Git would track
(tracked files and untracked files that `.gitignore` does not exclude, so keep the working
tree free of stray files), drops paths the release rules forbid (media, databases, keys,
logs, archives outside `hardware/`), re-pins the binary files, runs the same scan and then
stages exactly the listed files. `--check` does the same without staging.

## Publishing a release

1. Work on a branch, never on `main`.
2. Run `make test`, `make lint` and `python3 scripts/public_release.py check`.
3. Make one commit on top of the current `main` that contains the release.
4. Push it as a branch: `git push origin <branch>`. Never use `--force`.
5. The owner opens the pull request on GitHub and merges it.

`git push` uses this computer's SSH key (`~/.ssh/id_ed25519`), registered on GitHub.
Check it with `ssh -T git@github.com`.

## Extra checks

```bash
python3 scripts/public_release.py history    # scan every file in the Git history
```

A `.gitignore` cannot remove something already committed: if a private file was ever
committed, stop before pushing, because removing it from history needs a rewrite.
