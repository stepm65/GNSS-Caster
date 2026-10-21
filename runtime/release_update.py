"""Root-owned stable-release updater; stdlib only, no application imports.

The trust boundary is HTTPS GitHub Releases in the fixed owner/repository. An
asset digest verifies integrity, not an independent publisher signature.
"""
import contextlib
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import sqlite3
import stat
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

REPO = 'stepm65/GNSS-Caster'
API = f'https://api.github.com/repos/{REPO}/releases'
BASE = Path('/opt/gnss-caster')
STORE = Path('/var/lib/gnss-caster-updates')
UNIT = 'gnss-caster-release-update.service'
MAX_ASSET = 20 * 1024 * 1024
MAX_JSON = 1024 * 1024
BUSY = {'queued', 'checking', 'downloading', 'installing'}
STAGE_TIMEOUTS = {'snapshot': 600, 'dependencies': 1800, 'configuration': 900,
                  'migration': 600, 'health': 300, 'rollback': 900}
INSTALL_TIMEOUT = 3600
ROLLBACK_TIMEOUT = 900
HEARTBEAT_SECONDS = 5
CLEAN_ENV = {'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LANG': 'C.UTF-8',
             'HOME': '/root', 'DEBIAN_FRONTEND': 'noninteractive'}


class UpdateError(Exception):
    pass


def version(value):
    match = re.fullmatch(r'v?(0|[1-9][0-9]{0,3})\.(0|[1-9][0-9]{0,3})\.(0|[1-9][0-9]{0,3})', str(value))
    if not match:
        raise UpdateError('Unsupported release version')
    return tuple(map(int, match.groups()))


def current_version():
    source = (BASE / 'app/version.py').read_text(encoding='utf-8')
    match = re.search(r'^__version__ = [\'"]([0-9.]+)[\'"]$', source, re.M)
    if not match:
        raise UpdateError('Cannot determine installed version')
    version(match[1])
    return match[1]


def allowed_url(url):
    parsed = urllib.parse.urlsplit(url)
    return (parsed.scheme == 'https' and parsed.port in (None, 443)
            and not parsed.username and not parsed.password
            and parsed.hostname in {'api.github.com', 'github.com',
                                    'release-assets.githubusercontent.com', 'objects.githubusercontent.com'})


class GitHubRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not allowed_url(newurl):
            raise UpdateError('Untrusted download redirect')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch(url, limit):
    if not allowed_url(url):
        raise UpdateError('Untrusted release URL')
    # Do not let service-controlled proxy environment redirect root traffic.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), GitHubRedirect())
    request = urllib.request.Request(url, headers={
        'Accept': 'application/vnd.github+json' if url.startswith(API) else 'application/octet-stream',
        'User-Agent': 'GNSS-Caster-Release-Updater', 'X-GitHub-Api-Version': '2022-11-28',
    })
    deadline = time.monotonic() + (20 if limit == MAX_JSON else 120)
    try:
        with opener.open(request, timeout=10) as response:
            length = int(response.headers.get('Content-Length', '0'))
            if length > limit:
                raise UpdateError('Release download exceeds size limit')
            chunks, total = [], 0
            while True:
                if time.monotonic() > deadline:
                    raise UpdateError('Release download timed out')
                chunk = response.read(min(65536, limit + 1 - total))
                if not chunk:
                    break
                chunks.append(chunk)
                total += len(chunk)
                if total > limit:
                    raise UpdateError('Release download exceeds size limit')
            return b''.join(chunks)
    except urllib.error.HTTPError as error:
        if error.code == 404 and url == API + '/latest':
            return b'null'
        raise UpdateError(f'GitHub request failed (HTTP {error.code})') from error
    except (OSError, ValueError) as error:
        raise UpdateError('Cannot contact GitHub securely; check network and system clock') from error


def release_candidate(data, installed):
    if data is None:
        return None
    if not isinstance(data, dict) or data.get('draft') is not False or data.get('prerelease') is not False:
        raise UpdateError('Only published stable releases are supported')
    tag = data.get('tag_name', '')
    if not re.fullmatch(r'v[0-9]+\.[0-9]+\.[0-9]+', tag):
        raise UpdateError('Unsupported release version')
    target = version(tag)
    assets = [item for item in data.get('assets', []) if item.get('name') == 'gnss-caster-install.sh']
    if len(assets) != 1:
        raise UpdateError('Release has no unique installer asset')
    asset = assets[0]
    digest = str(asset.get('digest') or '')
    if not re.fullmatch(r'sha256:[0-9a-f]{64}', digest):
        raise UpdateError('Release installer has no SHA-256 digest')
    url = f'https://github.com/{REPO}/releases/download/{tag}/gnss-caster-install.sh'
    if asset.get('browser_download_url') != url or asset.get('state') != 'uploaded':
        raise UpdateError('Unexpected release installer URL or state')
    size = asset.get('size')
    if type(size) is not int or not 1 <= size <= MAX_ASSET:
        raise UpdateError('Release installer has an invalid size')
    return {'tag': tag, 'version': '.'.join(map(str, target)), 'sha256': digest[7:],
            'size': size, 'download_url': url, 'available': target > version(installed),
            'url': f'https://github.com/{REPO}/releases/tag/{tag}',
            'notes': str(data.get('body') or '')[:12000], 'published_at': data.get('published_at')}


def ensure_store():
    STORE.mkdir(mode=0o700, parents=False, exist_ok=True)
    info = STORE.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o077:
        raise UpdateError('Update storage must be a private root-owned directory')


def read_json(name, default=None):
    path = STORE / name
    if not path.exists():
        return default
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_nlink != 1:
        raise UpdateError('Unsafe update state file')
    return json.loads(path.read_text(encoding='utf-8'))


def write_json(name, data):
    fd, temporary = tempfile.mkstemp(prefix='.state-', dir=STORE)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            json.dump(data, handle, ensure_ascii=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, STORE / name)
        if os.name == 'posix':
            directory_fd = os.open(STORE, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


@contextlib.contextmanager
def lock(path):
    import fcntl
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_nlink != 1:
            raise UpdateError('Unsafe maintenance lock')
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise UpdateError('Another maintenance operation is running') from error
        yield fd
    finally:
        os.close(fd)


def run(arguments, **kwargs):
    return subprocess.run(arguments, env=CLEAN_ENV, text=True, **kwargs)


def boot_id():
    return Path('/proc/sys/kernel/random/boot_id').read_text().strip()


def status():
    state = read_json('state.json', {'status': 'idle'})
    if state['status'] in BUSY:
        result = run(['/usr/bin/systemctl', 'show', UNIT, '--property=ActiveState', '--value'],
                     capture_output=True, timeout=10)
        active = result.stdout.strip() in ('active', 'activating', 'reloading', 'deactivating')
        if state.get('boot_id') != boot_id() or (not active and time.time() - state['started_at'] > 30):
            # A power cut/SIGKILL is not a successful rollback.
            state = dict(state, status='interrupted', message='Update interrupted; inspect the maintenance log',
                         finished_at=int(time.time()))
            write_json('state.json', state)
    installed = current_version()
    checked = read_json('candidate.json')
    if checked and checked.get('candidate'):
        checked['candidate']['available'] = version(checked['candidate']['tag']) > version(installed)
    return {'current_version': installed, 'job': state,
            'release': checked, 'repository': f'https://github.com/{REPO}'}


def check():
    installed = current_version()
    candidate = release_candidate(json.loads(fetch(API + '/latest', MAX_JSON)), installed)
    result = {'checked_at': int(time.time()), 'candidate': candidate}
    write_json('candidate.json', result)
    return dict(result, current_version=installed)


def active_rovers():
    # Read counters only. No import of code/config from the service account.
    path = BASE / 'instance/db.sqlite'
    config = (BASE / 'instance/config.yaml').read_text(encoding='utf-8')
    configured = re.findall(r'^\s+path:\s*[\'"]?([^\s\'"#]+)[\'"]?\s*(?:#.*)?$', config, re.M)
    if configured != [str(path)]:
        raise UpdateError('Web updates require the standard database location')
    with contextlib.closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=5)) as db:
        return int(db.execute('SELECT COALESCE(SUM(active_conn), 0) FROM rover').fetchone()[0])


def preflight_space():
    # Repair snapshots app, venv and DB. Keep headroom for pip and an additional
    # copy; this is conservative rather than a promise for arbitrary releases.
    total = 0
    for directory in (BASE / 'app', BASE / 'venv', BASE / 'instance'):
        for root, dirs, files in os.walk(directory, followlinks=False):
            for filename in files:
                total += (Path(root) / filename).lstat().st_size
    required = total * 2 + 512 * 1024 * 1024
    for directory in (BASE, Path('/var/backups'), STORE):
        if shutil.disk_usage(directory).free < required:
            raise UpdateError('Not enough free space for update and rollback snapshot')


def start(tag, digest):
    version(tag)
    if not re.fullmatch(r'[0-9a-f]{64}', digest):
        raise UpdateError('Invalid release digest')
    with lock(STORE / 'request.lock'):
        if status()['job']['status'] in BUSY:
            raise UpdateError('An update is already running')
        checked = read_json('candidate.json', {})
        candidate = checked.get('candidate') or {}
        if time.time() - checked.get('checked_at', 0) > 600 or candidate.get('tag') != tag or candidate.get('sha256') != digest:
            raise UpdateError('Check for updates again before installing')
        if version(tag) <= version(current_version()):
            raise UpdateError('Only a newer release can be installed')
        if active_rovers():
            raise UpdateError('Disconnect all rovers before updating')
        preflight_space()
        # Confirm the other maintenance lock is currently free. The worker
        # obtains and retains it again before doing any work.
        with lock(Path('/run/gnss-caster-maintenance.lock')):
            pass
        run(['/usr/bin/systemctl', 'stop', UNIT], capture_output=True, timeout=15)
        run(['/usr/bin/systemctl', 'reset-failed', UNIT], capture_output=True, timeout=15)
        state = {'status': 'queued', 'tag': tag, 'sha256': digest, 'previous_version': current_version(),
                 'started_at': int(time.time()), 'boot_id': boot_id(), 'message': 'Update queued'}
        write_json('state.json', state)
        try:
            result = run(['/usr/bin/systemd-run', '--unit=' + UNIT, '--property=Type=oneshot',
                          '--property=RemainAfterExit=yes', '--property=UMask=0077',
                          '--property=TimeoutStartSec=infinity', f'--property=TimeoutStopSec={ROLLBACK_TIMEOUT + 60}',
                          '--property=KillMode=mixed', '/usr/bin/python3', '-I',
                          str(BASE / 'release-update.py'), 'worker', tag, digest],
                         capture_output=True, timeout=20)
            if result.returncode:
                raise UpdateError('Could not schedule update service')
        except Exception:
            # Scheduling timeout can be ambiguous; status reconciles with the
            # actual unit, and the API never retries a destructive request.
            raise UpdateError('Update scheduling was not confirmed; check status before retrying')
        return state


def install_asset(candidate, content):
    if len(content) != candidate['size'] or hashlib.sha256(content).hexdigest() != candidate['sha256']:
        raise UpdateError('Downloaded installer failed SHA-256 verification')
    text = content.decode('utf-8')
    match = re.search(r'^CASTER_VERSION="([0-9.]+)"$', text, re.M)
    if not match or match[1] != candidate['version']:
        raise UpdateError('Installer version does not match the release')
    path = STORE / 'installer.sh'
    # The store is root-only; replacement never follows a prior symlink.
    fd, temporary = tempfile.mkstemp(prefix='.installer-', dir=STORE)
    try:
        with os.fdopen(fd, 'wb') as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return path


def record_installer_progress(line, state):
    """Keep recovery coordinates while repair runs, not only after its exit."""
    snapshot = re.fullmatch(r'Rollback snapshot created: (/var/backups/gnss-caster/rollback-[^\s/]+)', line)
    if snapshot:
        state['snapshot'] = snapshot[1]
    if line.startswith('GNSS maintenance stage: '):
        name = line.removeprefix('GNSS maintenance stage: ')
        if name in STAGE_TIMEOUTS:
            state['phase'] = name
    if line == 'Rollback completed; previous service state restored.':
        state['rollback_confirmed'] = True


def run_installation(arguments, *, stdout, pass_fds, state):
    """Forward one stop request and allow rollback before escalating.

    A separate process group lets Bash and its current external command receive
    TERM together. The supervisor stays alive so systemd mixed mode cannot kill
    the rollback immediately after the main process exits.
    """
    requested = []
    previous = {}
    process = None
    stopping_at = None
    phase = 'snapshot'

    def request_stop(signum, frame):
        if not requested:
            requested.append('signal')

    def terminate_group(sig):
        try:
            os.killpg(process.pid, sig)
        except ProcessLookupError:
            pass

    try:
        for sig in (signal.SIGTERM, signal.SIGINT):
            previous[sig] = signal.signal(sig, request_stop)
        if requested:
            raise UpdateError('Update stopped before installation')
        process = subprocess.Popen(arguments, env=CLEAN_ENV, text=True, stdout=stdout,
                                   stderr=subprocess.STDOUT, pass_fds=pass_fds, start_new_session=True)
        started = phase_started = last_heartbeat = time.monotonic()
        phase = state.get('phase', 'snapshot')
        partial = ''
        with (STORE / 'maintenance.log').open(encoding='utf-8', errors='replace') as progress:
            while True:
                chunk = progress.read(256 * 1024)
                lines = (partial + chunk).split('\n')
                partial = lines.pop()[-65536:]
                coordinates = (state.get('snapshot'), state.get('phase'), state.get('rollback_confirmed'))
                for line in lines:
                    record_installer_progress(line.strip(), state)
                if coordinates != (state.get('snapshot'), state.get('phase'), state.get('rollback_confirmed')):
                    write_json('state.json', state)
                now = time.monotonic()
                next_phase = state.get('phase', phase)
                if next_phase != phase:
                    phase, phase_started = next_phase, now
                result = process.poll()
                if result is not None:
                    # Drain the remaining log before accepting a final result.
                    if chunk:
                        continue
                    record_installer_progress(partial.strip(), state)
                    return subprocess.CompletedProcess(arguments, result)
                if not requested and (now - started >= INSTALL_TIMEOUT or
                                      now - phase_started >= STAGE_TIMEOUTS.get(phase, 900)):
                    requested.append('timeout')
                if requested and stopping_at is None:
                    state['stop_reason'] = requested[0]
                    state['stop_requested_at'] = int(time.time())
                    state['message'] = 'Stopping update; waiting for rollback'
                    write_json('state.json', state)
                    # A rollback triggered by repair itself must not be interrupted.
                    if phase != 'rollback':
                        terminate_group(signal.SIGTERM)
                    stopping_at = now
                if stopping_at is not None and now - stopping_at >= ROLLBACK_TIMEOUT:
                    state['termination_escalated'] = True
                    write_json('state.json', state)
                    terminate_group(signal.SIGKILL)
                    process.wait(timeout=30)
                    raise UpdateError('Update could not stop safely; inspect the recovery snapshot')
                if now - last_heartbeat >= HEARTBEAT_SECONDS:
                    state['heartbeat_at'] = int(time.time())
                    write_json('state.json', state)
                    last_heartbeat = now
                try:
                    process.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    pass
    finally:
        # An exception in state/log handling must not leave an untracked installer.
        try:
            if process is not None and process.poll() is None:
                if stopping_at is None and phase != 'rollback':
                    terminate_group(signal.SIGTERM)
                try:
                    process.wait(timeout=ROLLBACK_TIMEOUT)
                except subprocess.TimeoutExpired:
                    terminate_group(signal.SIGKILL)
                    process.wait(timeout=30)
        finally:
            for sig, handler in previous.items():
                signal.signal(sig, handler)


def worker(tag, digest):
    state = read_json('state.json')
    if not state or state.get('tag') != tag or state.get('sha256') != digest or state['status'] != 'queued':
        raise UpdateError('No matching update request')

    def stage(name, message):
        state.update(status=name, message=message)
        write_json('state.json', state)

    try:
        with lock(Path('/run/gnss-caster-maintenance.lock')) as maintenance_fd:
            (STORE / 'maintenance.log').write_text(f'Updating to {tag}\n', encoding='utf-8')
            stage('checking', 'Validating stable release')
            candidate = release_candidate(json.loads(fetch(API + '/tags/' + tag, MAX_JSON)), current_version())
            if not candidate or not candidate['available'] or candidate['sha256'] != digest:
                raise UpdateError('Release changed; check for updates again')
            if active_rovers():
                raise UpdateError('Disconnect all rovers before updating')
            preflight_space()
            stage('downloading', 'Downloading and verifying installer')
            path = install_asset(candidate, fetch(candidate['download_url'], MAX_ASSET))
            syntax = run(['/bin/bash', '-n', str(path)], capture_output=True, timeout=15)
            if syntax.returncode:
                raise UpdateError('Release installer syntax check failed')
            if active_rovers():
                raise UpdateError('Disconnect all rovers before updating')
            # Existing repair transaction uses fd 8. Pass the same open-file
            # description so child flock recognizes ownership without bypasses.
            os.dup2(maintenance_fd, 8, inheritable=True)
            try:
                stage('installing', 'Installing; web interface may reconnect')
                with (STORE / 'maintenance.log').open('a', encoding='utf-8') as log:
                    result = run_installation(['/bin/bash', str(path), '--repair'], stdout=log,
                                              pass_fds=(8,), state=state)
                rolled_back = False
                with (STORE / 'maintenance.log').open(encoding='utf-8', errors='replace') as log:
                    for line in iter(lambda: log.readline(65536), ''):
                        snapshot = re.fullmatch(r'Rollback snapshot created: (/var/backups/gnss-caster/[^\s]+)\s*', line)
                        if snapshot:
                            state['snapshot'] = snapshot[1]
                        if line.strip() == 'Rollback completed; previous service state restored.':
                            rolled_back = True
                if result.returncode or state.get('stop_reason'):
                    if rolled_back:
                        stage('rolled_back', 'Update failed; previous version restored')
                    else:
                        stage('failed', 'Update failed; inspect the maintenance log')
                elif current_version() != candidate['version']:
                    stage('failed', 'Installed version could not be confirmed; inspect the maintenance log')
                else:
                    stage('succeeded', 'Update installed successfully; reload the page')
            finally:
                if maintenance_fd != 8:
                    os.close(8)
    except Exception as error:
        message = str(error) if isinstance(error, UpdateError) else 'Update failed; inspect the maintenance log'
        stage('interrupted' if state.get('termination_escalated') else 'failed', message)
    finally:
        state['finished_at'] = int(time.time())
        write_json('state.json', state)
    return state


def main():
    if os.geteuid() != 0:
        raise UpdateError('Updater requires root')
    os.umask(0o077)
    ensure_store()
    args = sys.argv[1:]
    if args == ['check']:
        result = check()
    elif args == ['status']:
        result = status()
    elif len(args) == 3 and args[0] == 'start':
        result = start(*args[1:])
    elif len(args) == 3 and args[0] == 'worker':
        result = worker(*args[1:])
    else:
        raise UpdateError('Unsupported updater command')
    print(json.dumps(result, ensure_ascii=True))


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(json.dumps({'error': str(error) if isinstance(error, UpdateError) else 'Update operation failed'}))
        sys.exit(1)
