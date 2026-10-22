"""Embed the independently reviewed maintenance broker/client and systemd units."""
import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
START = '# BEGIN GENERATED MAINTENANCE BROKER\n'
END = '# END GENERATED MAINTENANCE BROKER\n'
broker = (ROOT / 'runtime/maintenance_broker.py').read_text(encoding='utf-8')
client = (ROOT / 'runtime/maintenance_client.py').read_text(encoding='utf-8')
assert '\nPY_MAINTENANCE_BROKER\n' not in broker
assert '\nPY_MAINTENANCE_CLIENT\n' not in client
block = START + '''write_maintenance_broker() {
    local broker_temp client_temp
    mkdir -p "$BASE" "$APP" || return 1
    broker_temp=$(mktemp "$BASE/.maintenance-XXXXXX") || return 1
    cat > "$broker_temp" << 'PY_MAINTENANCE_BROKER' || return 1
''' + broker + '''
PY_MAINTENANCE_BROKER
    chown root:root "$broker_temp" || return 1
    chmod 700 "$broker_temp" || return 1
    mv -f "$broker_temp" "$BASE/maintenance-broker.py" || return 1
    client_temp=$(mktemp "$APP/.maintenance-XXXXXX") || return 1
    cat > "$client_temp" << 'PY_MAINTENANCE_CLIENT' || return 1
''' + client + '''
PY_MAINTENANCE_CLIENT
    chown root:root "$client_temp" || return 1
    chmod 644 "$client_temp" || return 1
    mv -f "$client_temp" "$APP/maintenance.py" || return 1
    # The socket directory cannot be created/replaced by the service account.
    if [ -L /run/gnss-caster-maintenance ] || { [ -e /run/gnss-caster-maintenance ] && {
        [ "$(stat -c %u /run/gnss-caster-maintenance)" != 0 ] ||
        [ "$(stat -c %a /run/gnss-caster-maintenance)" != 755 ]; }; }; then
        echo 'ERROR: Unsafe maintenance socket directory' >&2; return 1
    fi
    install -d -o root -g root -m 755 /run/gnss-caster-maintenance || return 1
    cat > /etc/systemd/system/gnss-caster-maintenance.socket << 'BROKER_SOCKET'
[Unit]
Description=GNSS Caster maintenance requests

[Socket]
ListenStream=/run/gnss-caster-maintenance/control.sock
SocketUser=root
SocketGroup=gnss-caster
SocketMode=0660
DirectoryMode=0755
Accept=yes
MaxConnections=8
MaxConnectionsPerSource=8
Backlog=8
RemoveOnStop=yes
BROKER_SOCKET
    cat > /etc/systemd/system/gnss-caster-maintenance@.service << 'BROKER_SERVICE'
[Unit]
Description=GNSS Caster maintenance request
CollectMode=inactive-or-failed

[Service]
Type=exec
User=root
Group=root
ExecStart=/usr/bin/python3 -I /opt/gnss-caster/maintenance-broker.py
StandardInput=socket
StandardOutput=null
StandardError=journal
NoNewPrivileges=yes
PrivateTmp=yes
ProtectHome=yes
ProtectKernelModules=yes
ProtectControlGroups=yes
RestrictSUIDSGID=yes
LockPersonality=yes
UMask=0077
TasksMax=32
MemoryMax=128M
RuntimeMaxSec=1815
TimeoutStopSec=10
KillMode=control-group
BROKER_SERVICE
    chown root:root /etc/systemd/system/gnss-caster-maintenance.socket /etc/systemd/system/gnss-caster-maintenance@.service || return 1
    chmod 644 /etc/systemd/system/gnss-caster-maintenance.socket /etc/systemd/system/gnss-caster-maintenance@.service || return 1
}
''' + END
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
        raise SystemExit('Embedded maintenance differs; run tools/embed_maintenance.py')
    print('Committed maintenance broker/client match their sources')
else:
    path.write_text(text, encoding='utf-8', newline='\n')
    print('Embedded maintenance broker/client')
