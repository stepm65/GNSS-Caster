"""Embed the root-only recovery journal in the standalone installer."""
import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
START = '# BEGIN GENERATED RECOVERY JOURNAL\n'
END = '# END GENERATED RECOVERY JOURNAL\n'
source = (ROOT / 'runtime/recovery.py').read_text(encoding='utf-8')
assert '\nPYTHON_RECOVERY_JOURNAL\n' not in source
block = START + """write_recovery_support() {
    local recovery_store="/var/lib/gnss-caster-maintenance"
    local recovery_temp
    if [ -L "$recovery_store" ] || { [ -e "$recovery_store" ] && {
        [ ! -d "$recovery_store" ] || [ "$(stat -c %u "$recovery_store")" != 0 ] ||
        [ "$(stat -c %a "$recovery_store")" != 700 ]; }; }; then
        echo "ERROR: Unsafe recovery storage" >&2
        return 1
    fi
    install -d -o root -g root -m 700 "$recovery_store" || return 1
    recovery_temp=$(mktemp "$recovery_store/.recovery-XXXXXX") || return 1
    cat > "$recovery_temp" << 'PYTHON_RECOVERY_JOURNAL' || return 1
""" + source + """
PYTHON_RECOVERY_JOURNAL
    chown root:root "$recovery_temp" || return 1
    chmod 700 "$recovery_temp" || return 1
    mv -f "$recovery_temp" "$recovery_store/recovery.py" || return 1
    sync -f "$recovery_store"
}
""" + END
path = ROOT / 'gnss-caster-install.sh'
text = path.read_text(encoding='utf-8')
if START in text:
    before, tail = text.split(START, 1)
    _, after = tail.split(END, 1)
    text = before + block + after
else:
    text = text.replace('rollback_backup_path() {\n', block + '\nrollback_backup_path() {\n', 1)
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--check', action='store_true')
args = parser.parse_args()
if args.check:
    if path.read_text(encoding='utf-8') != text:
        raise SystemExit('Embedded recovery differs; run tools/embed_recovery.py')
    print('Committed recovery journal matches its source')
else:
    path.write_text(text, encoding='utf-8', newline='\n')
    print('Embedded recovery journal')
