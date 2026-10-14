import ast
import io
import os
import re
import sqlite3
import stat
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch
from contextlib import nullcontext
from test_security_regressions import SOURCE, load_function

class SessionTests(unittest.TestCase):
    def setUp(self):
        self.user = NS(id=1, session_version=0)
        self.ns = {'Admin': NS(query=NS(get=lambda ident: self.user if ident == 1 else None)), 'logger': Mock()}
        self.loader = load_function('load_user', self.ns)

    def test_current_version_accepted(self):
        self.assertIs(self.loader('1:0'), self.user)

    def test_old_cookie_rejected_after_revocation(self):
        self.user.session_version = 1
        self.assertIsNone(self.loader('1:0'))
        self.assertIs(self.loader('1:1'), self.user)

    def test_legacy_malformed_and_missing_accounts_rejected(self):
        for value in ('1', 'bad', '1:x', '2:0', None):
            self.assertIsNone(self.loader(value))

    def test_pending_two_factor_rejected_after_revocation(self):
        self.user.session_version = 2
        self.ns.update(session={'_pending_2fa_user_id': 1, '_pending_2fa_at': 100, '_pending_2fa_version': 1},
                       time=NS(time=lambda: 101), current_user=NS(is_authenticated=False),
                       redirect=lambda url: url, url_for=lambda name: name)
        self.assertEqual(load_function('login_2fa', self.ns)(), 'login')
        self.assertNotIn('_pending_2fa_user_id', self.ns['session'])

    def test_migration_preserves_account_and_is_idempotent(self):
        with sqlite3.connect(':memory:') as connection:
            connection.execute('CREATE TABLE admin (id INTEGER, password TEXT)')
            connection.execute("INSERT INTO admin VALUES (1, 'keep')")
            ns = {'db': NS(session=connection), 'text': lambda sql: sql,
                  '_get_table_columns': lambda table: {r[1] for r in connection.execute('PRAGMA table_info(admin)')}}
            migrate = load_function('_migration_008_session_version', ns)
            migrate(); migrate()
            self.assertEqual(connection.execute('SELECT * FROM admin').fetchone(), (1, 'keep', 0))

    def test_panic_revokes_accounts_without_two_factor_too(self):
        code = SOURCE.split("cat > \"$panic_script\" << 'EOF'\n", 1)[1].split('\nEOF', 1)[0]
        code = code[code.index('app = create_app()'):]
        users = [NS(session_version=0), NS(session_version=4)]
        tokens = [NS(is_active=True)]
        session = Mock()
        ns = {'create_app': lambda: NS(app_context=nullcontext), 'db': NS(session=session),
              'Admin': NS(query=NS(all=lambda: users)),
              'ApiToken': NS(query=NS(filter_by=lambda **kwargs: NS(all=lambda: tokens)))}
        exec(code, ns)
        self.assertEqual([u.session_version for u in users], [1, 5])
        self.assertTrue(all(not u.totp_enabled and not u.totp_pending_secret for u in users))
        self.assertFalse(tokens[0].is_active)
        session.commit.assert_called_once()

class RestoreKeyTests(unittest.TestCase):
    def setUp(self):
        code = SOURCE.split("<< 'PY_READ_RESTORE_KEY'\n", 1)[1].split('\nPY_READ_RESTORE_KEY', 1)[0]
        node = next(n for n in ast.parse(code).body if isinstance(n, ast.FunctionDef))
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'secret'
        self.path.write_text('private-password', encoding='utf-8')
        self.info = NS(st_mode=stat.S_IFREG | 0o600, st_uid=123, st_nlink=1)
        # Emulate POSIX unlink-while-open on Windows; retain real file contents.
        def open_key(path, flags):
            self.stream = io.StringIO(self.path.read_text(encoding='utf-8'))
            return 5
        self.os = NS(open=open_key,
                     fstat=lambda fd: self.info, unlink=lambda path: self.path.unlink(),
                     fdopen=lambda *args, **kwargs: self.stream,
                     close=lambda fd: self.stream.close(), O_RDONLY=os.O_RDONLY,
                     O_NOFOLLOW=0, O_NONBLOCK=0)
        ns = {'os': self.os, 're': re, 'stat': stat}
        exec(compile(ast.Module(body=[node], type_ignores=[]), '<restore key>', 'exec'), ns)
        self.consume = ns['consume_restore_key']
        self.valid = '/run/gnss-caster/restore-0123456789abcdef.key'

    def test_consumed_once_and_deleted(self):
        self.assertEqual(self.consume(self.valid, 123), 'private-password')
        self.assertFalse(self.path.exists())
        with self.assertRaises(FileNotFoundError): self.consume(self.valid, 123)

    def test_unsafe_paths_rejected_before_open(self):
        for path in ('/etc/shadow', '/run/gnss-caster/restore-../../secret.key', self.valid + '/extra'):
            with self.assertRaises(ValueError): self.consume(path, 123)
        self.assertTrue(self.path.exists())

    def test_wrong_owner_mode_type_and_hardlink_rejected(self):
        for field, value in [('st_uid', 0), ('st_mode', stat.S_IFREG | 0o644), ('st_mode', stat.S_IFIFO | 0o600), ('st_nlink', 2)]:
            old = getattr(self.info, field)
            setattr(self.info, field, value)
            with self.assertRaises(ValueError): self.consume(self.valid, 123)
            setattr(self.info, field, old)
            self.assertTrue(self.path.exists())

    def test_oversized_key_deleted(self):
        self.path.write_text('x' * 4097)
        with self.assertRaises(ValueError): self.consume(self.valid, 123)
        self.assertFalse(self.path.exists())

class ScheduleTests(unittest.TestCase):
    def test_failed_schedule_removes_created_key(self):
        import io
        fake_os = NS(path=NS(isfile=lambda path: True), open=Mock(return_value=5),
                     fdopen=lambda *args, **kwargs: io.StringIO(), unlink=Mock(),
                     O_WRONLY=1, O_CREAT=2, O_EXCL=4)
        ns = {'os': fake_os, 'secrets': NS(token_hex=lambda n: '0' * 16),
              '_resolve_backup_archive_path': lambda name: (name, None),
              '_schedule_system_job': Mock(side_effect=RuntimeError('failed'))}
        fn = load_function('_schedule_restore_script', ns)
        with self.assertRaises(RuntimeError): fn('backup_test.tar.gz.enc', 'secret')
        fake_os.unlink.assert_called_once_with('/run/gnss-caster/restore-' + '0' * 16 + '.key')
        fake_os.open.side_effect = FileExistsError()
        fake_os.unlink.reset_mock()
        with self.assertRaises(FileExistsError): fn('backup_test.tar.gz.enc', 'secret')
        fake_os.unlink.assert_not_called()

if __name__ == '__main__':
    unittest.main()
