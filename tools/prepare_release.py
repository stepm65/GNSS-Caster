"""Prepare immutable release inputs; creating/publishing the release is separate."""
import hashlib
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]


def prepare(version, root=ROOT):
    if not re.fullmatch(r'(0|[1-9][0-9]{0,3})\.(0|[1-9][0-9]{0,3})\.(0|[1-9][0-9]{0,3})', version):
        raise ValueError('Expected stable version X.Y.Z')
    installer = (root / 'gnss-caster-install.sh').read_bytes()
    text = installer.decode('utf-8')
    if not re.search(r'^CASTER_VERSION="' + re.escape(version) + r'"$', text, re.M):
        raise ValueError('Release version differs from installer')
    changes = (root / 'CHANGES.md').read_text(encoding='utf-8')
    match = re.search(r'^## ' + re.escape(version) + r'\b[^\n]*\n(.*?)(?=^## |\Z)', changes, re.M | re.S)
    if not match:
        raise ValueError('Release has no changelog entry')
    (root / 'SHA256SUMS').write_text(hashlib.sha256(installer).hexdigest() + '  gnss-caster-install.sh\n', encoding='utf-8')
    (root / 'release-notes.md').write_text(match[0].strip() + '\n', encoding='utf-8')


if __name__ == '__main__':
    if len(sys.argv) != 2:
        raise SystemExit('Usage: python tools/prepare_release.py X.Y.Z')
    prepare(sys.argv[1])
