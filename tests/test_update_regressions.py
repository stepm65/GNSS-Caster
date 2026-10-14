"""Test the generated updater transaction with isolated files and mocked services."""
import os
from pathlib import Path
import subprocess
import sqlite3
import sys
from contextlib import closing
import tempfile
import unittest
from test_rollback_regressions import ROOT, SOURCE, bash_function, find_bash

UPDATE = SOURCE.split("cat > $BASE/update.sh << 'EOF'\n", 1)[1].split('\nEOF', 1)[0]

@unittest.skipUnless(find_bash(), 'Bash required')
class UpdateRollbackTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ROOT / 'tests')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.functions = '\n'.join(bash_function(name) for name in (
            'sqlite_database_tool',
            'update_snapshot_paths', 'create_update_runtime_snapshot',
            'validate_update_runtime_snapshot', 'restore_update_runtime_snapshot',
            'restore_update_service_state', 'handle_update_exit'))

    def run_case(self, ending='exit 7', active=True, prefix=''):
        env = os.environ.copy()
        env['TEST_ROOT'] = self.root.as_posix()
        env['TEST_PYTHON'] = Path(sys.executable).as_posix()
        setup = r'''
set -eE
export PATH="/usr/bin:/bin:$PATH"
TEST_ROOT=$(cd "$TEST_ROOT" && pwd -P)
BASE_DIR="$TEST_ROOT/runtime"
UPDATE_SNAPSHOT_ROOT="$TEST_ROOT/snapshots"
UPDATE_RUNTIME_ROLLBACK_DIR=""
UPDATE_SNAPSHOT_READY=0
UPDATE_MUTATIONS_STARTED=0
UPDATE_COMMITTED=0
UPDATE_FAILED_LINE=unknown
UPDATE_HEALTH_WAS_OK=1
UPDATE_ORIGINAL_HEALTH_URL=http://test/health
UPDATE_SYSTEM_PATH="$PATH"
PRE_UPDATE_BACKUP_FILE=""
TIMESTAMP=test
SERVICE_WAS_ACTIVE=0
mkdir -p "$BASE_DIR/app" "$BASE_DIR/venv" "$BASE_DIR/instance"
printf old > "$BASE_DIR/app/code.py"
printf old-venv > "$BASE_DIR/venv/package"
printf old-config > "$BASE_DIR/instance/config.yaml"
log() { printf '%s\n' "$*"; }
error() { printf '%s\n' "$*" >&2; }
chown() { :; }
chmod() { :; }
python3() { "$TEST_PYTHON" "$@"; }
sleep() { :; }
curl() { [ "${FAIL_HEALTH:-0}" != 1 ]; }
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
    local last arg
    for arg in "$@"; do last="$arg"; done
    if [ "${FAIL_SNAPSHOT:-0}" = 1 ] && [[ "$last" == "$UPDATE_SNAPSHOT_ROOT"/* ]]; then return 19; fi
    if [ "${FAIL_RESTORE:-0}" = 1 ] && [ "$last" = "$BASE_DIR/venv" ]; then return 20; fi
    command cp "$@"
}
systemctl() {
    echo "$*" >> "$TEST_ROOT/services.log"
    case "$1" in
        stop) [ "${FAIL_STOP:-0}" != 1 ] || return 1; rm -f "$TEST_ROOT/active" ;;
        start) [ "${FAIL_START:-0}" != 1 ] || return 1; touch "$TEST_ROOT/active" ;;
        is-active) [ -f "$TEST_ROOT/active" ] ;;
        *) return 90 ;;
    esac
}
'''
        if active:
            setup += '\nSERVICE_WAS_ACTIVE=1\ntouch "$TEST_ROOT/active"\n'
        # Use the production trap declarations, not a reimplementation.
        traps = UPDATE[UPDATE.index('UPDATE_OWNER_BASHPID=$BASHPID'):UPDATE.index('# Quiesce writers')]
        script = setup + '\n' + self.functions + '\n' + traps + '\n' + prefix + r'''
systemctl stop gnss-caster
create_update_runtime_snapshot
UPDATE_MUTATIONS_STARTED=1
printf new > "$BASE_DIR/app/code.py"
printf new-venv > "$BASE_DIR/venv/package"
printf newly-created > "$BASE_DIR/main.py"
systemctl start gnss-caster
''' + ending
        result = subprocess.run([find_bash()], input=script, env=env,
                                encoding='utf-8', capture_output=True, timeout=20)
        self.assertNotIn('UNSAFE TEST DELETE', result.stderr)
        return result

    def assert_restored(self, result, code=7, active=True):
        self.assertEqual(result.returncode, code, result.stdout + result.stderr)
        self.assertEqual((self.root / 'runtime/app/code.py').read_text(), 'old')
        self.assertEqual((self.root / 'runtime/venv/package').read_text(), 'old-venv')
        self.assertFalse((self.root / 'runtime/main.py').exists())
        self.assertEqual((self.root / 'active').exists(), active)
        self.assertEqual(result.stdout.count('Update rollback completed'), 1)

    def test_explicit_exit(self):
        self.assert_restored(self.run_case())

    def test_command_failure(self):
        self.assert_restored(self.run_case('false'), 1)

    def test_term(self):
        self.assert_restored(self.run_case('kill -TERM "$$"'), 143)

    def test_int(self):
        self.assert_restored(self.run_case('kill -INT "$$"'), 130)

    def test_hup(self):
        self.assert_restored(self.run_case('kill -HUP "$$"'), 129)

    def test_subshell_failure_only_rolls_back_once(self):
        self.assert_restored(self.run_case('result=$(false)'), 1)

    def test_inactive_service_stays_inactive(self):
        self.assert_restored(self.run_case(active=False), active=False)

    def test_success_keeps_new_files(self):
        result = self.run_case('UPDATE_COMMITTED=1\nexit 0')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.root / 'runtime/app/code.py').read_text(), 'new')
        self.assertNotIn('Update rollback completed', result.stdout)

    def test_success_restores_inactive_state_using_production_branch(self):
        branch = UPDATE[UPDATE.index('# Check service status'):UPDATE.rindex('trap - ERR')]
        result = self.run_case('run_post_update_checks() { :; }\nsuccess() { :; }\n' + branch, active=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse((self.root / 'active').exists())
        self.assertEqual((self.root / 'runtime/app/code.py').read_text(), 'new')

    def test_uncommitted_zero_exit_is_a_failure(self):
        self.assert_restored(self.run_case('exit 0'), 1)

    def test_database_restored_and_stale_wal_removed(self):
        db = self.root / 'runtime/instance/db.sqlite'
        db.parent.mkdir(parents=True)
        with closing(sqlite3.connect(db)) as connection:
            connection.execute('CREATE TABLE data(value TEXT)')
            connection.execute("INSERT INTO data VALUES ('old')")
            connection.commit()
        result = self.run_case('''python3 -c "import sqlite3,sys; c=sqlite3.connect(sys.argv[1]); c.execute('DELETE FROM data'); c.commit(); c.close()" "$BASE_DIR/instance/db.sqlite"
printf stale > "$BASE_DIR/instance/db.sqlite-wal"
exit 7''')
        self.assert_restored(result)
        with closing(sqlite3.connect(db)) as connection:
            self.assertEqual(connection.execute('SELECT value FROM data').fetchone()[0], 'old')
        self.assertFalse(Path(str(db) + '-wal').exists())

    def test_snapshot_failure_does_not_replace_live_files(self):
        result = self.run_case(prefix='FAIL_SNAPSHOT=1')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((self.root / 'runtime/app/code.py').read_text(), 'old')
        self.assertTrue((self.root / 'active').exists())

    def test_missing_snapshot_leaves_service_stopped(self):
        result = self.run_case('rm -rf "$UPDATE_RUNTIME_ROLLBACK_DIR/files/app"\nexit 7')
        self.assertEqual(result.returncode, 7)
        self.assertEqual((self.root / 'runtime/app/code.py').read_text(), 'new')
        self.assertFalse((self.root / 'active').exists())
        self.assertIn('snapshot is incomplete', result.stderr)

    def test_copy_failure_never_restarts_partial_runtime(self):
        result = self.run_case('FAIL_RESTORE=1\nexit 7')
        self.assertEqual(result.returncode, 7)
        self.assertFalse((self.root / 'active').exists())
        self.assertIn('rollback incomplete', result.stderr)

    def test_cannot_stop_means_no_file_replacement(self):
        result = self.run_case('FAIL_STOP=1\nexit 7')
        self.assertEqual(result.returncode, 7)
        self.assertEqual((self.root / 'runtime/app/code.py').read_text(), 'new')
        self.assertIn('Cannot stop caster', result.stderr)

    def test_health_failure_is_reported(self):
        result = self.run_case('FAIL_HEALTH=1\nexit 7')
        self.assertEqual(result.returncode, 7)
        self.assertIn('previous web health', result.stderr)
        self.assertNotIn('Update rollback completed', result.stdout)

    def test_start_failure_is_reported(self):
        result = self.run_case('FAIL_START=1\nexit 7')
        self.assertEqual(result.returncode, 7)
        self.assertIn('rollback incomplete', result.stderr)
        self.assertFalse((self.root / 'active').exists())

if __name__ == '__main__':
    unittest.main()
