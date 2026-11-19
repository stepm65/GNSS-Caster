"""Publish the prepared release files for a vX.Y.Z tag on GitHub.

Used by .github/workflows/release.yml after tools/prepare_release.py. Both ways
of starting a release end with the same published (non-draft) release:

- a pushed tag: the release does not exist yet and is created here;
- a release drafted or published on github.com: the files are attached to it,
  an empty title or description is filled in, and a draft is published.

A file already attached to a published release is never replaced. Running the
workflow again for the same commit is harmless (identical files are skipped);
different content under an existing published version is refused, so a fix
always needs a new version. Needs the gh CLI and GH_TOKEN with contents: write.
"""
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ('gnss-caster-install.sh', 'SHA256SUMS')
NOTES = 'release-notes.md'
TAG = re.compile(r'v(0|[1-9][0-9]{0,3})\.(0|[1-9][0-9]{0,3})\.(0|[1-9][0-9]{0,3})')


class PublishError(Exception):
    pass


def run_gh(arguments):
    result = subprocess.run(['gh', *arguments], capture_output=True, text=True)
    if result.returncode != 0:
        raise PublishError(f'gh {arguments[0]} failed: {result.stderr.strip() or result.stdout.strip()}')
    return result.stdout


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def find_release(repo, tag, gh):
    # The /releases/tags/{tag} endpoint hides drafts, so look through the list.
    output = gh(['api', '--paginate', f'repos/{repo}/releases?per_page=100',
                 '--jq', f'.[] | select(.tag_name == "{tag}")'])
    found = [json.loads(line) for line in output.splitlines() if line.strip()]
    if len(found) > 1:
        raise PublishError(f'More than one release uses tag {tag}')
    return found[0] if found else None


def publish(tag, repo, root=ROOT, gh=run_gh, wait=time.sleep, attempts=6):
    if not TAG.fullmatch(tag):
        raise PublishError(f'Release tags must look like v1.2.3, got {tag!r}')
    files = [root / name for name in ASSETS]
    notes = root / NOTES
    for path in (*files, notes):
        if not path.is_file():
            raise PublishError(f'Missing {path.name}; run tools/prepare_release.py first')
    local = {path.name: sha256(path) for path in files}
    title = f'GNSS Caster {tag[1:]}'

    release = find_release(repo, tag, gh)
    if release is None:
        gh(['release', 'create', tag, *map(str, files), '--repo', repo, '--verify-tag',
            '--title', title, '--notes-file', str(notes)])
    else:
        draft = release.get('draft') is True
        existing = {item.get('name'): item for item in release.get('assets', [])}
        for path in files:
            asset = existing.get(path.name)
            if asset is None:
                gh(['release', 'upload', tag, str(path), '--repo', repo])
            elif asset.get('digest') == 'sha256:' + local[path.name]:
                continue
            elif draft:
                gh(['release', 'upload', tag, str(path), '--repo', repo, '--clobber'])
            else:
                raise PublishError(
                    f'Published release {tag} already has a different {path.name}. '
                    'Published files are never replaced: release the fix as a new version.')
        edits = []
        if not str(release.get('name') or '').strip():
            edits += ['--title', title]
        if not str(release.get('body') or '').strip():
            edits += ['--notes-file', str(notes)]
        if release.get('prerelease') is True:
            edits += ['--prerelease=false']
        if draft:
            edits += ['--draft=false']
        if edits:
            gh(['release', 'edit', tag, '--repo', repo, *edits])

    # The web updater needs a published stable release whose installer asset has
    # a GitHub SHA-256 digest equal to the file built here. Confirm that state.
    for attempt in range(attempts):
        release = find_release(repo, tag, gh)
        digests = {item.get('name'): item.get('digest') for item in (release or {}).get('assets', [])}
        if (release and release.get('draft') is False and release.get('prerelease') is False
                and all(digests.get(name) == 'sha256:' + value for name, value in local.items())):
            return release
        if attempt + 1 < attempts:
            wait(5)
    raise PublishError(f'Release {tag} is not published with the expected files and digests')


def main(argv):
    if len(argv) != 3:
        raise SystemExit('Usage: python tools/publish_release.py vX.Y.Z OWNER/REPO')
    try:
        release = publish(argv[1], argv[2])
    except PublishError as error:
        print(f'::error::{error}', file=sys.stderr)
        return 1
    print(f'Published {release.get("html_url", argv[1])}')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
