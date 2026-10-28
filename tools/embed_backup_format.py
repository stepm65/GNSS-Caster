"""Embed shared archive inspection for root scripts and the unprivileged web."""
import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
START = '# BEGIN GENERATED BACKUP FORMAT\n'
END = '# END GENERATED BACKUP FORMAT\n'
source = (ROOT / 'runtime/backup_format.py').read_text(encoding='utf-8')
assert '\nPY_BACKUP_FORMAT\n' not in source
block = START + '''write_backup_format() {
    local format_temp
    format_temp=$(mktemp "$BASE/.backup-format-XXXXXX") || return 1
    cat > "$format_temp" << 'PY_BACKUP_FORMAT' || return 1
''' + source + '''
PY_BACKUP_FORMAT
    chown root:root "$format_temp" || return 1
    chmod 700 "$format_temp" || return 1
    mv -f "$format_temp" "$BASE/backup-format.py" || return 1
    install -o root -g root -m 644 "$BASE/backup-format.py" "$APP/backup_format.py" || return 1
}
''' + END
path = ROOT / 'gnss-caster-install.sh'
original = path.read_text(encoding='utf-8')
if START in original:
    before, tail = original.split(START, 1)
    _, after = tail.split(END, 1)
    updated = before + block + after
else:
    updated = original.replace('write_privileged_helper() {\n', block + '\nwrite_privileged_helper() {\n', 1)
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--check', action='store_true')
args = parser.parse_args()
if args.check:
    if original != updated:
        raise SystemExit('Embedded backup format differs; run tools/embed_backup_format.py')
    print('Committed backup format matches its source')
else:
    path.write_text(updated, encoding='utf-8', newline='\n')
    print('Embedded backup format')
