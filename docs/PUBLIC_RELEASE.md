# Publishing a clean source release

Use the same process for a private repository. Privacy settings on the hosting
service do not replace a clean source export, and this process never changes the
repository's visibility. SSH authentication can be used without putting a token
in a remote URL.

The working repository and its historical validation reports are private development
material. A public release must use an inspected source export and a separate public
checkout. This preserves the local installation, data and history. If the intended
public repository already has an initialization commit, preserve that commit and
its license; never overwrite it with private history or a force push.

## What is included

`.public-release-files` is an exact allowlist of application source, tests, dependency
lockfiles, installation/launch scripts, original interface icons and public
documentation. `.public-release-assets.json` pins the reviewed generated PNG icons
by SHA256. The generator is included so those assets can be reproduced and inspected.
Changing an icon intentionally requires regenerating and reviewing its hash entry.

The exporter excludes runtime directories, original media, source catalogs,
observations, reviews, camera settings, credentials and keys, model weights, private
environment files, operational logs, user-media validation reports and Git history.
Adding a dangerous path to the allowlist still fails the independent path check.
Symlinks are rejected, including symlinked parent directories inside the source tree.
There is no wildcard copy and no automatic `git add` or network publishing.

New source files must be explicitly added to the allowlist after review. A missing
listed file fails the export rather than silently creating an incomplete package.
The exporter reads from the current working tree; finish and test all edits first.

## Inspect and export

From the Linux repository root:

```bash
python3 scripts/public_release.py history
python3 scripts/public_release.py check
python3 scripts/public_release.py export --destination ../FALCON-public
python3 ../FALCON-public/scripts/public_release.py verify
```

The history command scans blobs reachable through all refs and reflogs, plus
unreachable blobs. Historical findings are expected in the private development
repository and explain why it must not be pushed. Findings show only file paths,
line numbers and categories. They never echo matching values. The command returns
nonzero when it finds something needing review.

`check` examines only the explicit public source set. It detects common access token
formats, private keys, embedded URL credentials, private network addresses, literal
credentials, precise location assignments and personal paths. Synthetic credentials
in tests are permitted only for reserved fixture hosts. Package version strings in
lockfiles are not mistaken for camera addresses. Inspect all findings rather than
removing checks to get a passing result.

The destination must not exist and must be outside the working repository. The scan
finishes before export starts. Each exported file has a SHA256 entry in
`PUBLIC_RELEASE_MANIFEST.json`; this receipt contains no source-machine paths, user
settings or historical commit identifiers. Verification rejects changed, extra or
unapproved files. It is an integrity check, not a signed provenance certificate.

## Review and initialize the public repository

Review the new directory and run the installation/static checks described in the
[installation guide](INSTALLATION.md). Use a separate disposable copy for install
tests: setup generates private runtime files that do not belong in a clean release.
Confirm the README's support claims match the actual tests and that model/data
licenses are retained in [model provenance](model-licenses.md).

For an empty public repository, when the exported source is final:

```bash
cd ../FALCON-public
git init -b main
git config user.name "Vinay Chittora"
# Set user.email locally to the developer's approved public or hosting noreply email.
git add --all
git diff --cached --stat
git diff --cached
git commit -m "Initial public release of FALCON"
python3 scripts/public_release.py verify --allow-initial-git
```

Inspect the complete staged diff before committing, including files not highlighted
by the heuristic scanner. Check the commit's public author name and email. This form
of final verification permits only zero or one commit, verifies the file inventory
and checks that committed content matches the inspected export. Do not merge or
fetch the private development history into this public repository.

### Preserve an existing public initialization

If the public repository already contains a root commit with only `README.md` and
`LICENSE`, first inspect those public files and record the full commit hash from the
remote. Keep its license unchanged in the exported source; add the appropriate
developer attribution in `NOTICE`. Use a separate clone of the public remote:

```bash
git clone --no-checkout https://github.com/vinaychittora/FALCON.git ../FALCON-public-checkout
cp -R ../FALCON-public/. ../FALCON-public-checkout/
cd ../FALCON-public-checkout
git config user.name "Vinay Chittora"
# Configure the approved public/noreply email locally before committing.
git add --all
git diff --cached --stat
git diff --cached
git commit -m "Add the inspected FALCON source release"
python3 scripts/public_release.py verify --public-base-commit FULL_PUBLIC_COMMIT_HASH
```

The copied export must pass `verify` before this step; it contains no `.git` directory.
Only the clone's public history is retained. Replace `FULL_PUBLIC_COMMIT_HASH` with
the inspected full hash, not a branch name or an abbreviated hash. This verification
requires the release commit's sole parent to be that exact public root commit. It
also checks that no extra commits are reachable through refs or reflogs, the root
contains only ordinary README/license files, its contents pass the source scan, and
its license bytes are preserved. The normal receipt and committed-content checks
still apply. Any other existing remote history requires a separate manual review;
do not bypass the check, replace the public branch or force-push.

Configure the intended public remote using its ordinary HTTPS or SSH URL, with
authentication handled outside the URL. Inspect `git remote -v` locally, then push
only the new branch. Do not use `--mirror`, `--all` or `--tags` from the development
checkout. Remote publication is a separate deliberate action; the exporter never
performs it.

For later releases, inspect changes through the same allowlist/scan workflow and
apply only public source changes to the public repository. Do not replace its
history with the private development repository. Both initial-history verification
modes are specifically for the first source release; subsequent public commits
require normal diff review and the source scan.
