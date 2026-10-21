"""Embed the independently testable release helper in the standalone installer."""
import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
START = '# BEGIN GENERATED RELEASE UPDATER\n'
END = '# END GENERATED RELEASE UPDATER\n'
source = (ROOT / 'runtime/release_update.py').read_text(encoding='utf-8')
assert '\nPYTHON_RELEASE_UPDATER\n' not in source
block = (START + 'write_release_updater() {\n'
         '    install -d -o root -g root -m 700 /var/lib/gnss-caster-updates\n'
         '    cat > "$BASE/release-update.py" << \'PYTHON_RELEASE_UPDATER\'\n' + source +
         '\nPYTHON_RELEASE_UPDATER\n'
         '    chown root:root "$BASE/release-update.py"\n'
         '    chmod 700 "$BASE/release-update.py"\n}\n' + END)
path = ROOT / 'gnss-caster-install.sh'
text = path.read_text(encoding='utf-8')
if START in text:
    before, tail = text.split(START, 1)
    _, after = tail.split(END, 1)
    text = before + block + after
else:
    text = text.replace('write_privileged_helper() {\n', block + '\nwrite_privileged_helper() {\n', 1)
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--check', action='store_true')
args = parser.parse_args()
if args.check:
    if path.read_text(encoding='utf-8') != text:
        raise SystemExit('Embedded updater differs from runtime/release_update.py; run tools/embed_release_updater.py')
    print('Committed release updater matches its source')
else:
    path.write_text(text, encoding='utf-8', newline='\n')
    print('Embedded release updater')
