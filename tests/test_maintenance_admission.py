"""Real lock/SQLite coordination in private fixtures; no host service changes."""
import ast
from contextlib import contextmanager, closing
import os
from pathlib import Path
import sqlite3
import stat
import subprocess
import sys
import tempfile
import threading
import time
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock, patch
from test_security_regressions import SOURCE, load_function
import test_ntrip_regressions as ntrip_tests
import test_rollback_regressions as rollback_tests

CORE = SOURCE.split("cat > $APP/ntrip/core.py << 'EOF'\n", 1)[1].split('\nEOF\n', 1)[0]
CHECK = SOURCE.split("<< 'PY_ADMISSION_CHECK'\n", 1)[1].split('\nPY_ADMISSION_CHECK\n', 1)[0]


class MaintenanceReadinessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        (self.base / 'instance').mkdir()
        self.database = self.base / 'instance/db.sqlite'
        (self.base / 'instance/config.yaml').write_text(f'database:\n  path: "{self.database}"\n')
        self.code = CHECK.replace("base = Path('/opt/gnss-caster')", f"base = Path({str(self.base)!r})")

    def execute(self):
        return subprocess.run([sys.executable, '-I', '-'], input=self.code, text=True, capture_output=True, timeout=10)

    def prepare_database(self, count=0, field='false'):
        with closing(sqlite3.connect(self.database)) as db:
            db.execute('CREATE TABLE rover(active_conn INTEGER)')
            db.execute('INSERT INTO rover VALUES (?)', (count,))
            db.execute('CREATE TABLE system_setting(key TEXT, value TEXT)')
            db.execute("INSERT INTO system_setting VALUES ('field_work_active', ?)", (field,))
            db.commit()

    def test_fresh_install_can_proceed_but_missing_live_database_cannot(self):
        self.assertEqual(self.execute().returncode, 0)
        (self.base / 'main.py').write_text('# installed')
        result = self.execute()
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.database.exists())

    def test_active_rovers_and_field_mode_block_maintenance(self):
        self.prepare_database(count=1)
        result = self.execute()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Disconnect all rovers', result.stderr)
        with closing(sqlite3.connect(self.database)) as db:
            db.execute('UPDATE rover SET active_conn=0')
            db.execute("UPDATE system_setting SET value='true'")
            db.commit()
        result = self.execute()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('field work', result.stderr)
        with closing(sqlite3.connect(self.database)) as db:
            db.execute("UPDATE system_setting SET value='false'")
            db.commit()
        self.assertEqual(self.execute().returncode, 0)

    def test_custom_database_is_rejected_instead_of_checking_wrong_counters(self):
        self.prepare_database()
        (self.base / 'instance/config.yaml').write_text('database:\n  path: /elsewhere.sqlite\n')
        self.assertIn('standard database', self.execute().stderr)


@unittest.skipUnless(os.name == 'posix', 'Real POSIX flock coordination')
class AdmissionLockTests(unittest.TestCase):
    def setUp(self):
        ntrip_tests.RoverSlotTests.setUp(self)
        self.lock_path = Path(self.temp.name) / 'admission.lock'
        self.lock_path.touch(mode=0o640)
        node = next(n for n in ast.parse(CORE).body if isinstance(n, ast.FunctionDef) and n.name == 'admission_guard')
        ns = dict(os=os, stat=stat, contextmanager=contextmanager, ADMISSION_LOCK=str(self.lock_path))
        exec(compile(ast.Module(body=[node], type_ignores=[]), '<admission>', 'exec'), ns)
        self.guard = ns['admission_guard']
        self.ns['admission_guard'] = self.guard
        real_fstat = os.fstat
        self.owner = patch.object(os, 'fstat', side_effect=lambda fd: NS(
            st_mode=real_fstat(fd).st_mode, st_nlink=real_fstat(fd).st_nlink, st_uid=0))
        self.owner.start()
        self.addCleanup(self.owner.stop)

    def test_exclusive_maintenance_prevents_any_new_counter_reservation(self):
        import fcntl
        with self.lock_path.open('rb') as maintenance:
            fcntl.flock(maintenance, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaises(BlockingIOError):
                self.server._reserve_rover_slot(1, 'hash')
            self.assertEqual(self.session.execute('SELECT active_conn FROM rover').fetchone()[0], 0)
        self.assertTrue(self.server._reserve_rover_slot(1, 'hash'))

    def test_pending_admission_blocks_maintenance_until_commit_is_visible(self):
        import fcntl
        acquired, finish = threading.Event(), threading.Event()
        errors = []
        def reserve():
            try:
                with self.guard():
                    acquired.set()
                    if not finish.wait(5):
                        raise TimeoutError('test handshake')
                    self.assertTrue(self.server._reserve_rover_slot_locked(1, 'hash'))
            except Exception as error:
                errors.append(error)
            finally:
                self.session.remove()
        reader = threading.Thread(target=reserve)
        reader.start()
        try:
            self.assertTrue(acquired.wait(5))
            with self.lock_path.open('rb') as maintenance:
                with self.assertRaises(BlockingIOError):
                    fcntl.flock(maintenance, fcntl.LOCK_EX | fcntl.LOCK_NB)
                finish.set()
                reader.join(5)
                self.assertFalse(reader.is_alive())
                self.assertEqual(errors, [])
                fcntl.flock(maintenance, fcntl.LOCK_EX | fcntl.LOCK_NB)
                self.assertEqual(self.session.execute('SELECT active_conn FROM rover').fetchone()[0], 1)
        finally:
            finish.set()
            reader.join(5)

    def test_missing_symlink_and_group_writable_locks_fail_closed(self):
        self.lock_path.chmod(0o660)
        with self.assertRaises(OSError), self.guard():
            self.fail('unsafe file accepted')
        self.lock_path.unlink()
        with self.assertRaises(OSError), self.guard():
            self.fail('missing file accepted')
        self.lock_path.symlink_to(Path(self.temp.name) / 'db.sqlite')
        with self.assertRaises(OSError), self.guard():
            self.fail('symlink accepted')


class FieldWorkSettingsTests(unittest.TestCase):
    def namespace(self, value):
        self.order = []
        self.setting = NS(value='false')
        model = Mock()
        model.query.filter_by.return_value.first.return_value = self.setting
        return dict(request=NS(json={'field_work_active': value}), _require_admin_role=lambda: None,
                    jsonify=lambda value: value, db=NS(session=NS(commit=lambda:self.order.append('commit'), rollback=Mock())),
                    SystemSetting=model, time=time, logger=Mock(),
                    _get_system_setting_value=lambda key, default='': default)

    def test_flag_commit_is_inside_admission_guard(self):
        ns = self.namespace(True)
        @contextmanager
        def guard():
            self.order.append('enter')
            yield
            self.order.append('exit')
        with patch.dict(sys.modules, {'app.ntrip.core': NS(admission_guard=guard)}):
            result, status = load_function('api_update_system_settings', ns)()
        self.assertEqual(status, 200, result)
        self.assertEqual(self.setting.value, 'true')
        self.assertEqual(self.order, ['enter', 'commit', 'exit'])

    def test_busy_maintenance_rejects_flag_change_without_commit(self):
        ns = self.namespace(True)
        @contextmanager
        def guard():
            raise BlockingIOError()
            yield
        with patch.dict(sys.modules, {'app.ntrip.core': NS(admission_guard=guard)}):
            _, status = load_function('api_update_system_settings', ns)()
        self.assertEqual(status, 409)
        self.assertEqual(self.setting.value, 'false')
        self.assertEqual(self.order, [])

    def test_flag_rejects_malformed_value_before_database_write(self):
        ns = self.namespace('maybe')
        _, status = load_function('api_update_system_settings', ns)()
        self.assertEqual(status, 400)
        self.assertEqual(self.order, [])


@unittest.skipUnless(rollback_tests.find_bash(), 'Bash required')
class GuardedServiceTests(unittest.TestCase):
    def execute(self, action='reboot', active=True, busy=False):
        body = SOURCE.split('    guarded-service-action)\n', 1)[1].split('\n    reboot-host)', 1)[0].rsplit(';;', 1)[0]
        body = body.replace('source /opt/gnss-caster/sqlite-functions.sh', ':')
        harness = """
set -e
die() { echo "error: $*" >&2; exit 1; }
acquire_maintenance_lock() { :; }
acquire_admission_guard() { GUARD; }
systemctl() {
    echo "systemctl $*"
    case "$1" in
        is-active) ACTIVE;;
        reboot|poweroff) return 1;;
        *) return 0;;
    esac
}
""".replace('GUARD', 'return 1' if busy else ':').replace('ACTIVE', 'return 0' if active else 'return 3')
        return subprocess.run([rollback_tests.find_bash(), '-s', '--', 'guarded-service-action', action],
                              input=harness + body, text=True, capture_output=True, timeout=10)

    def test_busy_gate_never_calls_service_manager(self):
        for action in ('reboot', 'shutdown'):
            result = self.execute(action=action, busy=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(result.stdout, '')

    def test_rejected_reboot_restores_only_previously_active_service(self):
        for action, command in (('reboot', 'reboot'), ('shutdown', 'poweroff')):
            for active in (True, False):
                with self.subTest(action=action, active=active):
                    result = self.execute(action=action, active=active)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn('systemctl stop gnss-caster', result.stdout)
                    self.assertIn('systemctl '+command, result.stdout)
                    self.assertEqual('systemctl start gnss-caster' in result.stdout, active)
