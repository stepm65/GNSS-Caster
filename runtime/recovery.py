"""Durable repair journal and explicit local recovery. Stdlib, root-only.

Snapshots and this program live outside the application account's writable
directories. Nothing is recovered automatically after an unclean shutdown.
"""
import contextlib
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import subprocess
import sys
import tempfile
import time

ROOT = Path('/var/backups/gnss-caster')
BASE = Path('/opt/gnss-caster')
MAINTENANCE_LOCK = Path('/run/gnss-caster-maintenance.lock')
ADMISSION_LOCK = Path('/var/lib/gnss-caster-admission.lock')
TERMINAL = {'committed', 'rolled_back', 'snapshot_failed'}
PHASES = {'snapshotting', 'prepared', 'dependencies', 'configuration', 'migration',
          'health', 'rollback', 'recovery', 'resuming', 'rollback_failed'} | TERMINAL
ENV = {'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LANG': 'C.UTF-8', 'HOME': '/root'}


class RecoveryError(Exception):
    pass


def trusted_directory(path):
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o077:
        raise RecoveryError('Recovery directory must be private and root-owned')


def trusted_file(path):
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_nlink != 1 or info.st_mode & 0o022:
        raise RecoveryError('Unsafe recovery metadata')


def snapshot_path(value):
    path = Path(value)
    if not path.is_absolute():
        path = ROOT / path
    if path.parent != ROOT or not re.fullmatch(r'rollback-[A-Za-z0-9_-]{1,100}', path.name):
        raise RecoveryError('Expected a snapshot ID in the rollback directory')
    trusted_directory(ROOT)
    trusted_directory(path)
    return path


def fsync_directory(path):
    if os.name == 'posix':
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def write_json(path, data):
    fd, temporary = tempfile.mkstemp(prefix='.journal-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(data, stream, ensure_ascii=True, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        fsync_directory(path.parent)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def read_state(path):
    trusted_file(path / 'transaction.json')
    data = json.loads((path / 'transaction.json').read_text(encoding='utf-8'))
    if (data.get('format') != 1 or data.get('id') != path.name
            or data.get('phase') not in PHASES or type(data.get('snapshot_ready')) is not bool):
        raise RecoveryError('Unsupported or invalid recovery journal')
    return data


def boot_id():
    return Path('/proc/sys/kernel/random/boot_id').read_text().strip()


def process_identity(pid):
    # comm can contain spaces and parentheses. starttime is field 22.
    return Path(f'/proc/{int(pid)}/stat').read_text().rsplit(')', 1)[1].split()[19]


def set_owner(data, pid):
    data.update(owner_pid=int(pid), owner_start=process_identity(pid), boot_id=boot_id())


def save(path, data, phase):
    if phase not in PHASES:
        raise RecoveryError('Unknown maintenance phase')
    data.update(phase=phase, updated_at=int(time.time()))
    write_json(path / 'transaction.json', data)


def begin(path, mode, target, pid):
    if (path / 'transaction.json').exists():
        raise RecoveryError('Snapshot already has a transaction journal')
    trusted_file(path / 'recover.sh')
    trusted_file(path / 'service-state.json')
    services = json.loads((path / 'service-state.json').read_text(encoding='utf-8'))
    previous = 'unknown'
    try:
        source = (BASE / 'app/version.py').read_text(encoding='utf-8')
        match = re.search(r'^__version__ = [\'"]([0-9.]+)[\'"]$', source, re.M)
        if match:
            previous = match[1]
    except OSError:
        pass
    # Persist the service-only recovery program before stopping any writer.
    evidence = inventory(path, names=('recover.sh', 'service-state.json', 'paths.list'), durable=True)
    data = {'format': 1, 'id': path.name, 'mode': mode, 'previous_version': previous,
            'target_version': target, 'created_at': int(time.time()), 'services': services,
            'snapshot_ready': False, 'initial_inventory': evidence}
    set_owner(data, pid)
    save(path, data, 'snapshotting')
    # The directory entry itself must survive power loss as well as its files.
    fsync_directory(ROOT)
    fsync_directory(ROOT.parent)


def inventory(path, names=('files', 'recover.sh', 'service-state.json', 'paths.list',
                           'existed.list', 'missing.list'), durable=False):
    result = {}

    def visit(item):
        info = item.lstat()
        record = {'mode': stat.S_IMODE(info.st_mode), 'uid': info.st_uid, 'gid': info.st_gid}
        if stat.S_ISLNK(info.st_mode):
            record.update(kind='link', target=os.readlink(item))
        elif stat.S_ISDIR(info.st_mode):
            record['kind'] = 'directory'
            for child in sorted(item.iterdir()):
                visit(child)
            if durable:
                fsync_directory(item)
        elif stat.S_ISREG(info.st_mode):
            digest = hashlib.sha256()
            with item.open('rb') as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                    digest.update(chunk)
                if durable and os.name == 'posix':
                    os.fsync(stream.fileno())
            record.update(kind='file', size=info.st_size, sha256=digest.hexdigest())
        else:
            raise RecoveryError('Snapshot contains an unsupported filesystem object')
        result[str(item.relative_to(path))] = record

    for name in names:
        visit(path / name)
    if durable:
        fsync_directory(path)
    return result


def ready(path):
    data = read_state(path)
    if data['phase'] != 'snapshotting' or data['snapshot_ready']:
        raise RecoveryError('Snapshot cannot be prepared from this state')
    data['inventory'] = inventory(path, durable=True)
    data['snapshot_ready'] = True
    save(path, data, 'prepared')


def mark(path, phase):
    data = read_state(path)
    if phase not in TERMINAL:
        set_owner(data, os.getppid())
    save(path, data, phase)


def list_states():
    if not ROOT.exists():
        return []
    trusted_directory(ROOT)
    result = []
    for path in sorted(ROOT.glob('rollback-*')):
        # Older snapshots have no journal and are deliberately not guessed.
        if not (path / 'transaction.json').exists():
            continue
        path = snapshot_path(path)
        result.append((path, read_state(path)))
    return result


def owner_alive(data):
    try:
        return (data['boot_id'] == boot_id()
                and data['owner_start'] == process_identity(data['owner_pid']))
    except (OSError, KeyError, ValueError, IndexError):
        return False


def pending():
    return [(path, data) for path, data in list_states() if data['phase'] not in TERMINAL]


@contextlib.contextmanager
def exclusive(path, create=False):
    import fcntl
    fd = os.open(path, os.O_RDWR | os.O_NOFOLLOW | (os.O_CREAT if create else 0), 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_nlink != 1:
            raise RecoveryError('Unsafe maintenance lock')
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RecoveryError('Another maintenance operation or rover admission is running') from error
        yield fd
    finally:
        os.close(fd)


def preflight():
    unfinished = pending()
    if unfinished:
        raise RecoveryError('Unfinished maintenance requires local recovery: ' + ', '.join(path.name for path, _ in unfinished))


def boot_check():
    unfinished = pending()
    if not unfinished:
        return
    # A current, identifiable installer may start the service for its health
    # gate. An old PID, a new boot or a lost lock never authorizes startup.
    if all(data['phase'] in ('health', 'resuming') and owner_alive(data) for _, data in unfinished):
        try:
            with exclusive(MAINTENANCE_LOCK, create=True):
                pass
        except RecoveryError as error:
            if str(error) == 'Another maintenance operation or rover admission is running':
                return
            raise
    raise RecoveryError('Caster startup blocked by unfinished maintenance. Run recovery.py status, then recover the indicated snapshot.')


def verify(path, data):
    if data['snapshot_ready']:
        actual = inventory(path)
        expected = data.get('inventory')
    else:
        if data['phase'] not in ('snapshotting', 'recovery', 'resuming', 'rollback_failed'):
            raise RecoveryError('Incomplete snapshot cannot restore application files')
        actual = inventory(path, names=('recover.sh', 'service-state.json', 'paths.list'))
        expected = data.get('initial_inventory')
    if actual != expected:
        raise RecoveryError('Snapshot contents differ from the durable manifest; no recovery was started')


def run(arguments, **kwargs):
    return subprocess.run(arguments, env=ENV, text=True, **kwargs)


def check_live_work():
    result = run(['/usr/bin/systemctl', 'show', 'gnss-caster', '--property=ActiveState', '--value'],
                 capture_output=True, timeout=15)
    state = result.stdout.strip()
    if result.returncode or state not in ('active', 'inactive', 'failed'):
        raise RecoveryError('Cannot establish whether caster is stopped')
    if state in ('inactive', 'failed'):
        return  # Explicit local recovery is allowed even with a broken DB.
    database = BASE / 'instance/db.sqlite'
    config = (BASE / 'instance/config.yaml').read_text(encoding='utf-8')
    configured = re.findall(r'^\s+path:\s*[\'"]?([^\s\'"#]+)[\'"]?\s*(?:#.*)?$', config, re.M)
    if configured != [str(database)]:
        raise RecoveryError('Recovery of a running caster requires the standard database location')
    with contextlib.closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True, timeout=5)) as db:
        field = db.execute("SELECT value FROM system_setting WHERE key='field_work_active'").fetchone()
        if field and str(field[0]).strip().lower() in ('1', 'true', 'yes', 'on'):
            raise RecoveryError('Finish field work mode before recovery')
        if db.execute('SELECT COALESCE(SUM(active_conn), 0) FROM rover').fetchone()[0]:
            raise RecoveryError('Disconnect all rovers before recovery')


def recover(path):
    with exclusive(MAINTENANCE_LOCK, create=True) as maintenance_fd, exclusive(ADMISSION_LOCK) as admission_fd:
        data = read_state(path)
        if data['phase'] in TERMINAL:
            raise RecoveryError('Transaction is already complete; this command only recovers unfinished work')
        others = [item.name for item, _ in pending() if item != path]
        if others:
            raise RecoveryError('More than one unfinished transaction requires manual inspection')
        verify(path, data)
        check_live_work()
        set_owner(data, os.getpid())
        save(path, data, 'recovery')
        try:
            # This root-owned, hashed program contains the exact rollback
            # functions and original service settings captured before mutation.
            result = run(['/bin/bash', '--noprofile', '--norc', str(path / 'recover.sh'),
                          '--restore' if data['snapshot_ready'] else '--services-only'],
                         pass_fds=(maintenance_fd, admission_fd))
            if result.returncode:
                raise RecoveryError('Recovery failed; inspect the retained snapshot and service logs')
        except BaseException:
            save(path, data, 'rollback_failed')
            raise
        save(path, data, 'rolled_back' if data['snapshot_ready'] else 'snapshot_failed')
        return data


def summary(path, data):
    return {**{key: value for key, value in data.items()
               if key not in ('inventory', 'initial_inventory', 'owner_start')},
            'snapshot': str(path),
            'recovery_command': f'sudo python3 -I /var/lib/gnss-caster-maintenance/recovery.py recover {path.name} --confirm'}


def main(arguments):
    if os.geteuid() != 0:
        raise RecoveryError('Run this recovery command as root')
    if arguments == ['status']:
        print(json.dumps([summary(path, data) for path, data in list_states()], ensure_ascii=True, indent=2))
    elif arguments == ['preflight']:
        preflight()
    elif arguments == ['boot-check']:
        boot_check()
    elif len(arguments) == 3 and arguments[0] == 'recover' and arguments[2] == '--confirm':
        path = snapshot_path(arguments[1])
        print(json.dumps(summary(path, recover(path)), ensure_ascii=True))
    elif len(arguments) == 5 and arguments[0] == 'begin':
        begin(snapshot_path(arguments[1]), arguments[2], arguments[3], int(arguments[4]))
    elif len(arguments) == 2 and arguments[0] == 'ready':
        ready(snapshot_path(arguments[1]))
    elif len(arguments) == 3 and arguments[0] == 'mark':
        mark(snapshot_path(arguments[1]), arguments[2])
    else:
        raise RecoveryError('Usage: recovery.py status | recover SNAPSHOT_ID --confirm')


if __name__ == '__main__':
    try:
        main(sys.argv[1:])
    except (RecoveryError, OSError, ValueError, sqlite3.Error) as error:
        print('ERROR: ' + str(error), file=sys.stderr)
        sys.exit(1)
