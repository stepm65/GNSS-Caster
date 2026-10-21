"""Exercise embedded SQLite code and installer rollback in an isolated Bash harness.

System services are mocked. All filesystem mutations stay in a temporary test
directory; no installer entry point or privileged system command is executed.
"""
from contextlib import closing
import contextlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / 'gnss-caster-install.sh').read_text(encoding='utf-8')
SQLITE_CODE = SOURCE.split("<< 'PY_SQLITE_TOOL'\n", 1)[1].split('\nPY_SQLITE_TOOL\n', 1)[0]


def bash_function(name):
    start = SOURCE.index(name + '() {\n')
    return SOURCE[start:SOURCE.index('\n}\n', start) + 3]


def find_bash():
    if shutil.which('bash'):
        return shutil.which('bash')
    bundled = Path.home() / '.cache/codex-runtimes/codex-primary-runtime/dependencies/native/git/usr/bin/sh.exe'
    return str(bundled) if bundled.is_file() else None


def cleanup_test_directory(directory):
    # Windows can briefly retain a just-closed SQLite directory entry.
    # Retry only these transient cleanup errors; never hide a final failure.
    for attempt in range(3):
        try:
            directory.cleanup()
            return
        except OSError as exc:
            if os.name != 'nt' or getattr(exc, 'winerror', None) not in (32, 145) or attempt == 2:
                raise
            time.sleep(0.1)


class SQLiteSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ROOT / 'tests')
        self.addCleanup(cleanup_test_directory, self.temp)
        self.root = Path(self.temp.name)
        self.ns = {'__name__': 'test_sqlite_tool'}
        exec(compile(SQLITE_CODE, '<embedded SQLite tool>', 'exec'), self.ns)
        self.tool = self.ns['sqlite_database_tool']

    def database(self, name, value):
        path = self.root / name
        with closing(sqlite3.connect(path)) as db:
            db.execute('CREATE TABLE data (value TEXT)')
            db.execute('INSERT INTO data VALUES (?)', (value,))
            db.commit()
        return path

    def value(self, path):
        with closing(sqlite3.connect(path)) as db:
            self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
            return db.execute('SELECT value FROM data').fetchone()[0]

    def test_snapshot_includes_committed_uncheckpointed_wal(self):
        source = self.database('source.sqlite', 'old')
        with closing(sqlite3.connect(source)) as writer:
            writer.execute('PRAGMA journal_mode=WAL')
            writer.execute('PRAGMA wal_autocheckpoint=0')
            writer.execute("UPDATE data SET value='new-in-wal'")
            writer.commit()
            self.assertGreater(Path(str(source) + '-wal').stat().st_size, 0)
            snapshot = self.root / 'snapshot.sqlite'
            self.tool('snapshot', source, snapshot)
            self.assertEqual(self.value(snapshot), 'new-in-wal')
            with closing(sqlite3.connect(snapshot)) as db:
                self.assertEqual(db.execute('PRAGMA journal_mode').fetchone()[0], 'delete')
            self.assertFalse(Path(str(snapshot) + '-wal').exists())

    def test_snapshot_excludes_uncommitted_changes(self):
        source = self.database('source.sqlite', 'committed')
        with closing(sqlite3.connect(source)) as writer:
            writer.execute('PRAGMA journal_mode=WAL')
            writer.execute("UPDATE data SET value='not-committed'")
            snapshot = self.root / 'snapshot.sqlite'
            self.tool('snapshot', source, snapshot)
            self.assertEqual(self.value(snapshot), 'committed')
            writer.rollback()

    def test_restore_removes_old_sidecars(self):
        snapshot = self.database('snapshot.sqlite', 'restored')
        live = self.database('live.sqlite', 'old')
        for suffix in ('-wal', '-shm', '-journal'):
            Path(str(live) + suffix).write_bytes(b'stale')
        self.tool('restore', snapshot, live)
        self.assertEqual(self.value(live), 'restored')
        for suffix in ('-wal', '-shm', '-journal'):
            self.assertFalse(Path(str(live) + suffix).exists())

    def test_corrupt_snapshot_never_overwrites_live_database(self):
        corrupt = self.root / 'corrupt.sqlite'
        corrupt.write_bytes(b'not a database')
        live = self.database('live.sqlite', 'keep')
        with self.assertRaises(sqlite3.DatabaseError):
            self.tool('restore', corrupt, live)
        self.assertEqual(self.value(live), 'keep')
        self.assertEqual(list(self.root.glob('.gnss-db-*')), [])

    def test_missing_source_does_not_create_empty_database(self):
        with self.assertRaises(FileNotFoundError):
            self.tool('snapshot', self.root / 'missing', self.root / 'destination')
        self.assertFalse((self.root / 'missing').exists())
        self.assertFalse((self.root / 'destination').exists())

    def test_same_source_and_destination_are_rejected(self):
        source = self.database('source.sqlite', 'keep')
        with self.assertRaises(ValueError):
            self.tool('snapshot', source, source)
        self.assertEqual(self.value(source), 'keep')

    def test_timeout_cleans_staging_and_preserves_destination(self):
        source = self.database('source.sqlite', 'new')
        destination = self.database('destination.sqlite', 'keep')
        with patch.object(self.ns['time'], 'monotonic', side_effect=[0, 31]):
            with self.assertRaises(TimeoutError):
                self.tool('snapshot', source, destination)
        self.assertEqual(self.value(destination), 'keep')
        self.assertEqual(list(self.root.glob('.gnss-db-*')), [])


@unittest.skipUnless(find_bash(), 'Bash is required for the isolated rollback harness')
class InstallerRollbackTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ROOT / 'tests')
        self.addCleanup(cleanup_test_directory, self.temp)
        self.root = Path(self.temp.name).resolve()
        self.functions = '\n'.join(bash_function(name) for name in (
            'sqlite_database_tool', 'rollback_backup_path', 'backup_path_for_rollback',
            'create_install_rollback_snapshot', 'restore_install_service_state',
            'validate_install_rollback_snapshot', 'restore_install_rollback_snapshot',
            'handle_install_exit', 'record_maintenance_phase', 'record_install_journal',
            'begin_runtime_transaction', 'finish_repair_transaction',
        ))

    def run_case(self, failure, initially_active=True, prefix='', journal=False):
        env = os.environ.copy()
        env['TEST_ROOT'] = self.root.as_posix()
        env['TEST_PYTHON'] = Path(sys.executable).as_posix()
        env['TEST_BASH'] = Path(find_bash()).as_posix()
        if journal:
            shim = f"""
import contextlib, importlib.util, os, sys
from pathlib import Path
spec = importlib.util.spec_from_file_location('recovery', {str(ROOT / 'runtime/recovery.py')!r})
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
m.ROOT = Path({str(self.root / 'snapshots')!r})
m.BASE = Path({str(self.root / 'runtime')!r})
# Only ownership and /proc are simulated; journal, hashes and scripts are real.
m.trusted_directory = lambda path: None
m.trusted_file = lambda path: None
m.boot_id = lambda: 'fixture-boot'
m.process_identity = lambda pid: 'fixture-' + str(pid)
os.geteuid = lambda: 0
m.main(sys.argv[1:])
"""
            (self.root / 'recovery-fixture.py').write_text(shim, encoding='utf-8')
        harness = r'''
set -eE
export PATH="/usr/bin:/bin:$PATH"
TEST_ROOT=$(cd "$TEST_ROOT" && pwd -P)
BASE="$TEST_ROOT/runtime"
INST="$BASE/instance"
APP="$BASE/app"
VENV="$BASE/venv"
SERVICE="$BASE/unit"
NGINX_AVAILABLE="$BASE/nginx"
PRIVILEGED_HELPER="$BASE/helper"
SUDOERS_FILE="$BASE/sudoers"
POLKIT_RULE="$BASE/polkit"
SECRET_KEY_ENV_FILE="$INST/secret.env"
ROLLBACK_ROOT="$TEST_ROOT/snapshots"
ROLLBACK_DIR=""
ROLLBACK_ACTIVE=0
INSTALL_STATE_CAPTURED=0
INSTALL_COMMITTED=0
INSTALL_CASTER_WAS_ACTIVE=0
INSTALL_NGINX_WAS_ACTIVE=0
INSTALL_HEALTH_WAS_OK=0
INSTALL_HEALTH_URL=""
INSTALL_CASTER_ENABLED=disabled
INSTALL_FAILED_LINE=unknown
SCRIPT_MODE=install
CASTER_VERSION=3.3.3
acquire_admission_guard() { :; }  # Admission is exercised by its own lock/SQLite tests.
write_recovery_support() { :; }
prepare_install_recovery() { :; }  # Durable journal has separate tests.
mkdir -p "$INST"
printf old > "$APP"
printf old-unit > "$SERVICE"
printf old-config > "$INST/config.yaml"
printf disabled > "$TEST_ROOT/enabled"

# Guard every recursive removal in the extracted rollback code.
rm() {
    local arg
    for arg in "$@"; do
        case "$arg" in
            -*) ;;
            "$TEST_ROOT"/*) ;;
            *) echo "UNSAFE TEST DELETE: $arg" >&2; return 99 ;;
        esac
    done
    command rm "$@"
}
cp() {
    local destination arg
    for arg in "$@"; do destination="$arg"; done
    if [ "${FAIL_SNAPSHOT:-0}" = 1 ] && [ "$2" = "$APP" ]; then return 19; fi
    if [ "${FAIL_RESTORE:-0}" = 1 ] && [ "$destination" = "$APP" ]; then return 20; fi
    command cp "$@"
}
chown() { :; }
chmod() { :; }  # POSIX ownership/modes are not emulated by the Windows harness.
bash() { "$TEST_BASH" "$@"; }
python3() {
    if [ "${2:-}" = /var/lib/gnss-caster-maintenance/recovery.py ]; then return 0; fi
    "$TEST_PYTHON" "$@"
}
get_config_value() { printf 8080; }
curl() { [ "${FAIL_HEALTH:-0}" != 1 ]; }
nginx() { :; }
ufw() {
    if [ "$1" = status ]; then echo 'Status: inactive'; else
        echo "Unexpected firewall operation in isolated test" >&2; return 90
    fi
}
sleep() { :; }
systemctl() {
    printf '%s\n' "$*" >> "$TEST_ROOT/services.log"
    local action="$1" unit arg
    for arg in "$@"; do unit="$arg"; done
    case "$action" in
        is-active) [ -f "$TEST_ROOT/$unit.active" ] ;;
        is-enabled) cat "$TEST_ROOT/enabled"; return 1 ;;
        stop) rm -f "$TEST_ROOT/$unit.active" ;;
        start) [ "${FAIL_START:-0}" != 1 ] || return 1; : > "$TEST_ROOT/$unit.active" ;;
        enable) printf enabled > "$TEST_ROOT/enabled" ;;
        disable) printf disabled > "$TEST_ROOT/enabled" ;;
        daemon-reload|reload) : ;;
        *) echo "Unexpected systemctl action" >&2; return 90 ;;
    esac
}
print_install_rollback_paths() {
    printf '%s\n' "$APP" "$SERVICE" "$INST/config.yaml" "$INST/db.sqlite" "$SECRET_KEY_ENV_FILE"
}
'''
        if initially_active:
            harness += '\n: > "$TEST_ROOT/gnss-caster.active"\n'
        if journal:
            harness += '\n' + bash_function('prepare_install_recovery') + r'''
python3() {
    if [ "${2:-}" = /var/lib/gnss-caster-maintenance/recovery.py ]; then
        shift 2
        "$TEST_PYTHON" "$TEST_ROOT/recovery-fixture.py" "$@"
    else
        "$TEST_PYTHON" "$@"
    fi
}
'''
        self.recovery_harness = harness
        self.recovery_env = env
        harness += '\n' + self.functions + '\n' + prefix + r'''
begin_runtime_transaction
printf new > "$APP"
printf new-secret > "$SECRET_KEY_ENV_FILE"
systemctl enable gnss-caster
'''
        result = subprocess.run([find_bash()], input=harness + '\n' + failure,
                                env=env, encoding='utf-8', capture_output=True, timeout=15)
        self.assertNotIn('UNSAFE TEST DELETE', result.stderr)
        return result

    def assert_restored(self, result, expected_code, active=True):
        self.assertEqual(result.returncode, expected_code, result.stdout + result.stderr)
        self.assertEqual((self.root / 'runtime/app').read_text(), 'old')
        self.assertFalse((self.root / 'runtime/instance/secret.env').exists())
        self.assertEqual((self.root / 'gnss-caster.active').exists(), active)
        self.assertEqual((self.root / 'enabled').read_text(), 'disabled')
        self.assertIn('Rollback completed', result.stdout)

    def test_explicit_exit_rolls_back_and_restarts_previous_service(self):
        self.assert_restored(self.run_case('exit 17'), 17)

    def test_repair_explicit_exit_rolls_back(self):
        self.assert_restored(self.run_case('exit 9', prefix='SCRIPT_MODE=repair'), 9)

    def test_repair_command_failure_rolls_back(self):
        self.assert_restored(self.run_case('false', prefix='SCRIPT_MODE=repair'), 1)

    def test_repair_signal_rolls_back_once(self):
        self.assert_restored(self.run_case('kill -TERM "$$"', prefix='SCRIPT_MODE=repair'), 143)

    def test_repair_failed_health_gate_rolls_back(self):
        self.assert_restored(self.run_case('run_install_smoke_tests() { return 1; }\nfinish_repair_transaction',
                                          prefix='SCRIPT_MODE=repair'), 1)

    def test_repair_snapshot_failure_preserves_runtime(self):
        result = self.run_case('exit 0', prefix='SCRIPT_MODE=repair\nFAIL_SNAPSHOT=1')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((self.root / 'runtime/app').read_text(), 'old')
        self.assertTrue((self.root / 'gnss-caster.active').exists())

    def test_repair_reload_previously_active_firewall(self):
        prefix = '''SCRIPT_MODE=repair
ufw() { if [ "$1" = status ]; then echo 'Status: active'; else echo reload >> "$TEST_ROOT/firewall.log"; fi; }
'''
        result = self.run_case('exit 9', prefix=prefix)
        self.assert_restored(result, 9)
        self.assertEqual((self.root / 'firewall.log').read_text().strip(), 'reload')

    def test_repair_firewall_reload_failure_is_reported(self):
        prefix = '''SCRIPT_MODE=repair
ufw() { if [ "$1" = status ]; then echo 'Status: active'; else return 1; fi; }
'''
        result = self.run_case('exit 9', prefix=prefix)
        self.assertEqual(result.returncode, 9)
        self.assertFalse((self.root / 'gnss-caster.active').exists())
        self.assertIn('Automatic rollback failed', result.stderr)

    def test_repair_success_keeps_new_runtime_and_previous_enablement(self):
        result = self.run_case('run_install_smoke_tests() { :; }\nmanage_secret_files() { :; }\nfinish_repair_transaction',
                               prefix='SCRIPT_MODE=repair')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.root / 'runtime/app').read_text(), 'new')
        self.assertEqual((self.root / 'enabled').read_text(), 'disabled')
        self.assertTrue((self.root / 'gnss-caster.active').exists())

    def test_repair_success_preserves_inactive_service(self):
        result = self.run_case('run_install_smoke_tests() { :; }\nmanage_secret_files() { :; }\nfinish_repair_transaction',
                               initially_active=False, prefix='SCRIPT_MODE=repair')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.root / 'gnss-caster.active').exists())
        self.assertEqual((self.root / 'runtime/app').read_text(), 'new')

    def test_repair_cleanup_failure_after_commit_does_not_roll_back(self):
        result = self.run_case('run_install_smoke_tests() { :; }\nmanage_secret_files() { return 3; }\nfinish_repair_transaction',
                               prefix='SCRIPT_MODE=repair')
        self.assertEqual(result.returncode, 3, result.stderr)
        self.assertEqual((self.root / 'runtime/app').read_text(), 'new')
        self.assertNotIn('Rollback completed', result.stdout)

    def test_secret_directory_migration_rolls_back_with_legacy_file(self):
        prefix = r'''
SECRET_DIR="$TEST_ROOT/secure-secrets"
printf old-key > "$INST/secret.env"
print_install_rollback_paths() {
    printf '%s\n' "$APP" "$SERVICE" "$INST/config.yaml" "$INST/db.sqlite" "$INST/secret.env" "$SECRET_DIR"
}
'''
        result = self.run_case('mkdir -p "$SECRET_DIR"\nprintf new-key > "$SECRET_DIR/secret.env"\nexit 9', prefix=prefix)
        self.assertEqual(result.returncode, 9, result.stderr)
        self.assertEqual((self.root / 'runtime/instance/secret.env').read_text(), 'old-key')
        self.assertFalse((self.root / 'secure-secrets').exists())
        self.assertTrue((self.root / 'gnss-caster.active').exists())

    def test_failed_command_uses_same_exit_rollback(self):
        self.assert_restored(self.run_case('false'), 1)

    def test_signal_rolls_back_once(self):
        result = self.run_case('kill -TERM "$$"')
        self.assert_restored(result, 143)
        self.assertEqual(result.stdout.count('Rollback completed'), 1)

    def test_previously_inactive_service_stays_inactive(self):
        self.assert_restored(self.run_case('exit 7', initially_active=False), 7, active=False)

    def test_success_does_not_restore_old_files(self):
        result = self.run_case('INSTALL_COMMITTED=1\nROLLBACK_ACTIVE=0\nexit 0')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.root / 'runtime/app').read_text(), 'new')
        self.assertNotIn('Rollback completed', result.stdout)

    def test_incomplete_snapshot_resumes_service_without_replacing_files(self):
        result = self.run_case('exit 0', prefix='FAIL_SNAPSHOT=1')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((self.root / 'runtime/app').read_text(), 'old')
        self.assertTrue((self.root / 'gnss-caster.active').exists())
        self.assertNotIn('Rollback completed', result.stdout)

    def test_missing_snapshot_component_aborts_before_live_deletion(self):
        result = self.run_case('rm -f "$(rollback_backup_path "$APP")"\nexit 9')
        self.assertEqual(result.returncode, 9)
        self.assertEqual((self.root / 'runtime/app').read_text(), 'new')
        self.assertFalse((self.root / 'gnss-caster.active').exists(), result.stdout + result.stderr + (self.root / 'services.log').read_text())
        self.assertIn('snapshot is incomplete', result.stderr)

    def test_failed_file_restore_does_not_restart_partial_runtime(self):
        result = self.run_case('FAIL_RESTORE=1\nexit 9')
        self.assertEqual(result.returncode, 9)
        self.assertFalse((self.root / 'gnss-caster.active').exists(), result.stdout + result.stderr + (self.root / 'services.log').read_text())
        self.assertIn('File rollback was incomplete', result.stderr)

    def test_unexpected_manifest_path_is_rejected(self):
        result = self.run_case('printf "/etc/not-owned\\n" >> "$ROLLBACK_DIR/missing.list"\nexit 9')
        self.assertEqual(result.returncode, 9)
        self.assertIn('snapshot is incomplete', result.stderr)
        self.assertEqual((self.root / 'runtime/app').read_text(), 'new')

    def test_health_failure_is_not_reported_as_successful_rollback(self):
        result = self.run_case('FAIL_HEALTH=1\nexit 9')
        self.assertEqual(result.returncode, 9)
        self.assertIn('did not recover its previous web health', result.stderr, result.stdout + (self.root / 'services.log').read_text())
        self.assertNotIn('Rollback completed', result.stdout)

    def test_database_rollback_replaces_data_and_removes_stale_wal(self):
        database = self.root / 'runtime/instance/db.sqlite'
        database.parent.mkdir(parents=True)
        with closing(sqlite3.connect(database)) as connection:
            connection.execute('CREATE TABLE data (value TEXT)')
            connection.execute("INSERT INTO data VALUES ('original')")
            connection.commit()
        failure = r'''
python3 -c "import sqlite3,sys; c=sqlite3.connect(sys.argv[1]); c.execute('DELETE FROM data'); c.commit(); c.close()" "$INST/db.sqlite"
printf stale > "$INST/db.sqlite-wal"
printf stale > "$INST/db.sqlite-shm"
exit 9
'''
        result = self.run_case(failure)
        self.assert_restored(result, 9)
        with closing(sqlite3.connect(database)) as connection:
            self.assertEqual(connection.execute('SELECT value FROM data').fetchone()[0], 'original')
        self.assertFalse(Path(str(database) + '-wal').exists())

    def test_durable_journal_survives_killed_installer_with_complete_snapshot(self):
        result = self.run_case('kill -KILL "$BASHPID"', journal=True)
        self.assertNotEqual(result.returncode, 0)
        snapshot = next((self.root / 'snapshots').glob('rollback-*'))
        state = json.loads((snapshot / 'transaction.json').read_text())
        self.assertTrue(state['snapshot_ready'])
        self.assertEqual(state['phase'], 'prepared')
        self.assertEqual(state['services']['caster_active'], '1')
        self.assertEqual((self.root / 'runtime/app').read_text(), 'new')
        self.assertFalse((self.root / 'gnss-caster.active').exists())
        parsed = subprocess.run([find_bash(), '-n', str(snapshot / 'recover.sh')],
                                text=True, capture_output=True, timeout=10)
        self.assertEqual(parsed.returncode, 0, parsed.stderr)

    def test_durable_journal_records_confirmed_automatic_rollback(self):
        result = self.run_case('false', journal=True)
        self.assert_restored(result, 1)
        snapshot = next((self.root / 'snapshots').glob('rollback-*'))
        state = json.loads((snapshot / 'transaction.json').read_text())
        self.assertEqual(state['phase'], 'rolled_back')

    def test_saved_program_recovers_after_installer_process_is_gone(self):
        result = self.run_case('kill -KILL "$BASHPID"', journal=True)
        self.assertNotEqual(result.returncode, 0)
        snapshot = next((self.root / 'snapshots').glob('rollback-*'))
        spec = importlib.util.spec_from_file_location('isolated_recovery', ROOT / 'runtime/recovery.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        definitions = ['set -eE', 'export PATH="/usr/bin:/bin:$PATH"', 'TEST_ROOT="$(cd "$TEST_ROOT" && pwd)"']
        for name in ('rm', 'cp', 'curl', 'nginx', 'ufw', 'sleep', 'systemctl', 'python3'):
            start = self.recovery_harness.rindex(name + '() {')
            first_end = self.recovery_harness.index('\n', start)
            end = first_end if self.recovery_harness[first_end - 1] == '}' else self.recovery_harness.index('\n}', start) + 2
            definitions.append(self.recovery_harness[start:end])
        def run_saved(arguments, **kwargs):
            program = '\n'.join(definitions) + '\n' + Path(arguments[-2]).read_text()
            result = subprocess.run([find_bash(), '-s', '--', arguments[-1]], input=program,
                                    env=self.recovery_env, text=True, capture_output=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            return result
        with patch.multiple(module, ROOT=self.root / 'snapshots', BASE=self.root / 'runtime'), \
             patch.object(module, 'trusted_directory'), patch.object(module, 'trusted_file'), \
             patch.object(module, 'boot_id', return_value='fixture-boot'), \
             patch.object(module, 'process_identity', return_value='fixture-process'), \
             patch.object(module, 'exclusive', side_effect=lambda *a, **kw: contextlib.nullcontext(7)), \
             patch.object(module, 'check_live_work'), patch.object(module, 'run', side_effect=run_saved):
            outcome = module.recover(snapshot)
        self.assertEqual(outcome['phase'], 'rolled_back')
        self.assertEqual((self.root / 'runtime/app').read_text(), 'old')
        self.assertFalse((self.root / 'runtime/instance/secret.env').exists())
        self.assertTrue((self.root / 'gnss-caster.active').exists())

    def test_generated_shared_functions_have_valid_bash_syntax(self):
        names = ('sqlite_database_tool', 'acquire_maintenance_lock', 'ensure_admission_lock', 'acquire_admission_guard')
        definitions = '\n'.join(bash_function(name) for name in names)
        generated = subprocess.run([find_bash()], input=definitions + '\ndeclare -f ' + ' '.join(names) + '\n',
                                   encoding='utf-8', capture_output=True, timeout=10)
        self.assertEqual(generated.returncode, 0, generated.stderr)
        parsed = subprocess.run([find_bash(), '-n'], input=generated.stdout,
                                encoding='utf-8', capture_output=True, timeout=10)
        self.assertEqual(parsed.returncode, 0, parsed.stderr)


if __name__ == '__main__':
    unittest.main()
