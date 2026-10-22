"""Root-only, socket-activated maintenance endpoint. Standard library only.

One bounded request per systemd service instance. Never imports application code
or accepts a command, environment, working directory or executable from a client.
"""
import datetime
import json
import os
from pathlib import Path
import re
import signal
import socket
import stat
import struct
import subprocess
import sys
import tempfile
import time
import uuid

HELPER = Path('/opt/gnss-caster/gnss-caster-privileged-helper.sh')
AUDIT = Path('/var/log/gnss-caster-maintenance')
MAX_REQUEST = 8192
MAX_OUTPUT = 131072
READ_ONLY = {'ping', 'release-status', 'systemctl-is-active', 'read-rssi', 'certificate-info'}
ENV = {'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LANG': 'C.UTF-8', 'LC_ALL': 'C.UTF-8', 'HOME': '/root'}


class Rejected(ValueError):
    pass


def matches(value, expression):
    return re.fullmatch(expression, value) is not None


def validate_request(request):
    if not isinstance(request, dict) or set(request) != {'version', 'args'} or type(request['version']) is not int or request['version'] != 1:
        raise Rejected('Unsupported maintenance protocol')
    args = request['args']
    if not isinstance(args, list) or not 1 <= len(args) <= 5 or any(
            not isinstance(a, str) or not a or len(a) > 255 or any(ord(c) < 32 for c in a) for a in args):
        raise Rejected('Invalid maintenance arguments')
    action, rest = args[0], args[1:]
    valid, timeout = False, 30
    mac = lambda v: matches(v, r'(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}')
    number = lambda v, low, high: matches(v, r'[0-9]{1,7}') and low <= int(v) <= high
    unit = lambda kind, v: matches(v, r'gnss-caster-' + kind + r'-[0-9]{1,12}(?:-[0-9a-f]{4})?\.service')
    if action in ('ping', 'release-status', 'release-check', 'rfkill-unblock-bluetooth', 'recover-bluetooth', 'restart-service', 'reboot-host'):
        valid = not rest
        timeout = 120 if action == 'release-check' else 60
    elif action == 'release-install':
        valid = len(rest) == 2 and matches(rest[0], r'v[0-9]{1,5}\.[0-9]{1,5}\.[0-9]{1,5}') and matches(rest[1], r'[0-9a-f]{64}')
        timeout = 60
    elif action == 'systemctl-is-active':
        valid = len(rest) == 1 and rest[0] in ('bluetooth', 'gnss-caster', 'nginx', 'fail2ban', 'cron', 'ssh', 'sshd')
    elif action == 'systemctl-start':
        valid = rest == ['bluetooth']
    elif action == 'rfcomm-bind':
        valid = len(rest) == 3 and number(rest[0], 1, 30) and mac(rest[1]) and number(rest[2], 1, 30)
    elif action == 'rfcomm-release':
        valid = len(rest) == 1 and number(rest[0], 1, 30)
    elif action == 'read-rssi':
        valid = len(rest) == 1 and mac(rest[0])
        timeout = 5
    elif action == 'recover-bluetooth-deep':
        valid = not rest or (len(rest) == 1 and mac(rest[0]))
        timeout = 60
    elif action == 'set-system-clock':
        if len(rest) == 1 and matches(rest[0], r'20[0-9]{2}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}'):
            try:
                datetime.datetime.strptime(rest[0], '%Y-%m-%d %H:%M:%S')
                valid = True
            except ValueError:
                pass
    elif action == 'systemd-job':
        if len(rest) == 2 and rest[0] == 'backup':
            valid = unit('backup', rest[1])
        elif len(rest) in (3, 4) and rest[0] == 'restore':
            valid = unit('restore', rest[1]) and matches(rest[2], r'backup_[A-Za-z0-9_-]{1,180}\.tar\.gz(?:\.enc)?')
            if len(rest) == 4:
                valid = valid and matches(rest[3], r'/run/gnss-caster/restore-[0-9a-f]{16}\.key')
        # Never let IPC select executable restoration. Only root's local helper
        # can request legacy full restoration; releases use a separate verifier.
        if valid and rest[0] == 'restore':
            args = ['systemd-data-restore', *rest[1:]]
    elif action == 'write-logrotate':
        valid = len(rest) == 1 and number(rest[0], 1, 3650)
    elif action == 'write-backup-cron':
        valid = len(rest) == 2 and rest[0] in ('0', '1') and number(rest[1], 3600, 604800)
    elif action == 'certificate-info':
        valid = len(rest) == 1 and (rest[0] == '/etc/ssl/certs/gnss-caster.crt' or matches(rest[0], r'/etc/letsencrypt/(?:live|archive)/[A-Za-z0-9_.-]{1,200}/fullchain[0-9]*\.pem'))
        valid = valid and all(part not in ('.', '..') for part in rest[0].split('/'))
    elif action == 'certbot-renew':
        valid = rest in (['0'], ['1'])
        timeout = 1800
    elif action == 'power':
        valid = len(rest) == 3 and rest[0] in ('reboot', 'shutdown') and unit('power-' + rest[0], rest[1]) and number(rest[2], 1, 60)
    if not valid:
        raise Rejected('Maintenance action or arguments not allowed')
    return args, timeout


def trusted(path, directory=False):
    info = path.lstat()
    if info.st_uid != 0 or info.st_mode & 0o022 or not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)):
        raise Rejected('Unsafe maintenance file permissions')
    if not directory and info.st_nlink != 1:
        raise Rejected('Unsafe maintenance file links')


def audit(record):
    """Append before a mutation, fail closed on storage error. Bounded rotation."""
    import fcntl
    trusted(AUDIT.parent, directory=True)
    AUDIT.mkdir(mode=0o700, exist_ok=True)
    trusted(AUDIT, directory=True)
    if AUDIT.stat().st_mode & 0o077:
        raise Rejected('Unsafe maintenance audit directory')
    flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW
    lock = os.open(AUDIT / '.lock', flags, 0o600)
    try:
        trusted(AUDIT / '.lock')
        fcntl.flock(lock, fcntl.LOCK_EX)
        path = AUDIT / 'actions.jsonl'
        if path.exists() or path.is_symlink():
            trusted(path)
            if path.stat().st_size >= 1024 * 1024:
                for index in (2, 1):
                    old = AUDIT / f'actions.jsonl.{index}'
                    if old.exists() or old.is_symlink():
                        trusted(old)
                        os.replace(old, AUDIT / f'actions.jsonl.{index+1}')
                os.replace(path, AUDIT / 'actions.jsonl.1')
        data = (json.dumps(dict(timestamp=int(time.time()), **record), ensure_ascii=True) + '\n').encode()
        fd = os.open(path, flags, 0o600)
        try:
            trusted(path)
            with os.fdopen(fd, 'ab', closefd=False) as stream:
                stream.write(data)
                stream.flush()
                os.fsync(fd)
        finally:
            os.close(fd)
        directory = os.open(AUDIT, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        os.close(lock)


def execute(args, timeout, request_id):
    trusted(HELPER.parent, directory=True)
    trusted(HELPER)
    # Files cap memory use; stop the entire group on timeout/oversized output.
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        proc = subprocess.Popen([str(HELPER), *args], stdin=subprocess.DEVNULL,
                                stdout=out, stderr=err, start_new_session=True,
                                cwd='/', env=dict(ENV, GNSS_BROKER_REQUEST=request_id))
        deadline = time.monotonic() + timeout
        failure = None
        try:
            while proc.poll() is None:
                if out.tell() + err.tell() > MAX_OUTPUT:
                    failure = 'Maintenance output limit exceeded'; break
                if time.monotonic() >= deadline:
                    failure = 'Maintenance operation timed out; inspect its status before retrying'; break
                time.sleep(0.05)
        finally:
            if proc.poll() is None:
                os.killpg(proc.pid, signal.SIGTERM)
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(proc.pid, signal.SIGKILL)
                    proc.wait()
        if out.tell() + err.tell() > MAX_OUTPUT:
            failure = 'Maintenance output limit exceeded'
        if failure:
            return {'returncode': 1, 'stdout': '', 'stderr': failure}
        out.seek(0); err.seek(0)
        return {'returncode': proc.returncode, 'stdout': out.read(MAX_OUTPUT).decode('utf-8', 'replace'),
                'stderr': err.read(MAX_OUTPUT).decode('utf-8', 'replace')}


def read_request(conn):
    conn.settimeout(5)
    data = bytearray()
    # Caller shuts down its write half; no persistent connections or pipelines.
    deadline = time.monotonic() + 5
    while True:
        conn.settimeout(max(0.001, deadline - time.monotonic()))
        part = conn.recv(min(4096, MAX_REQUEST + 1 - len(data)))
        if not part:
            break
        data.extend(part)
        if len(data) > MAX_REQUEST or time.monotonic() >= deadline:
            raise Rejected('Maintenance request too large or incomplete')
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise Rejected('Duplicate maintenance request field')
            result[key] = value
        return result
    return json.loads(data, object_pairs_hook=unique)


def handle(conn, allowed_uid):
    request_id = uuid.uuid4().hex
    record = {'id': request_id, 'action': 'invalid-request'}
    response = {'returncode': 1, 'stdout': '', 'stderr': 'Maintenance request rejected'}
    try:
        pid, uid, gid = struct.unpack('3i', conn.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
        record.update(pid=pid, uid=uid)
        if uid not in (0, allowed_uid):
            raise Rejected('Maintenance peer not allowed')
        args, timeout = validate_request(read_request(conn))
        record.update(action=args[0], arguments=args[1:])
        needs_audit = args[0] not in READ_ONLY
        if needs_audit:
            audit(dict(record, phase='accepted'))
        if args == ['ping']:
            response = {'returncode': 0, 'stdout': 'maintenance protocol 1', 'stderr': ''}
        else:
            response = execute(args, timeout, request_id)
        if needs_audit:
            audit(dict(record, phase='finished', returncode=response['returncode']))
    except Exception as exc:
        # No request text, environment, file contents or raw exception traces.
        response = {'returncode': 1, 'stdout': '', 'stderr': str(exc) if isinstance(exc, Rejected) else 'Maintenance failed; inspect the protected journal'}
        try:
            audit(dict(record, phase='rejected-or-incomplete'))
        except Exception:
            print('Cannot append maintenance audit; request failed closed', file=sys.stderr)
    response.update(version=1, request_id=request_id)
    conn.settimeout(5)
    try:
        conn.sendall(json.dumps(response).encode())
    except OSError:
        pass  # The protected result remains authoritative if a client disconnects.


def main():
    if os.geteuid() != 0:
        raise SystemExit('Maintenance broker must run as root')
    if len(sys.argv) == 3 and sys.argv[1] == '--audit-local':
        action = sys.argv[2]
        if not matches(action, r'[a-z-]{1,40}'):
            raise SystemExit('Invalid local action')
        audit({'id': uuid.uuid4().hex, 'uid': 0, 'pid': os.getppid(), 'action': action, 'phase': 'local-request'})
        return
    if sys.argv[1:]:
        raise SystemExit('Unsupported broker invocation')
    import pwd
    with socket.socket(fileno=os.dup(0)) as conn:
        handle(conn, pwd.getpwnam('gnss-caster').pw_uid)


if __name__ == '__main__':
    main()
