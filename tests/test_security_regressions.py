"""Isolated tests of code embedded in the installer; never execute the installer.

Run with: python -m unittest discover -s tests -v
Only the standard library is needed. Web dependencies and ORM are test doubles;
archive extraction and schema migration use real tar files and SQLite.
"""
import ast
import io
import json
from pathlib import Path
import secrets
import sqlite3
import tarfile
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / 'gnss-caster-install.sh'
SOURCE = SCRIPT.read_text(encoding='utf-8')
FACTORY = SOURCE.split("cat > $APP/web/factory.py << 'EOF'\n", 1)[1].split('\nEOF\n', 1)[0]
TREE = ast.parse(FACTORY)
EXTRACTOR = (SCRIPT.parent / 'runtime/backup_format.py').read_text(encoding='utf-8')


def load_function(name, namespace):
    node = next(n for n in ast.walk(TREE) if isinstance(n, ast.FunctionDef) and n.name == name)
    node = ast.parse(ast.unparse(node)).body[0]
    node.decorator_list = []
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(SCRIPT), 'exec'), namespace)
    return namespace[name]


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        namespace = {'__name__': 'test_extractor'}
        exec(compile(EXTRACTOR, str(SCRIPT), 'exec'), namespace)
        self.extract = namespace['safe_extract']

    def archive(self, entries):
        path = self.root / 'input.tar.gz'
        with tarfile.open(path, 'w:gz') as archive:
            for name, kind, content in entries:
                info = tarfile.TarInfo(name)
                info.type = kind
                info.mode = 0o6777
                if kind == tarfile.REGTYPE:
                    info.size = len(content)
                if kind in (tarfile.SYMTYPE, tarfile.LNKTYPE):
                    info.linkname = '../outside'
                archive.addfile(info, io.BytesIO(content) if kind == tarfile.REGTYPE else None)
        return path

    def test_normal_app_with_implicit_directories(self):
        path = self.archive([('app/web/main.py', tarfile.REGTYPE, b'print(1)')])
        self.extract(path, self.root / 'out', 'app')
        self.assertEqual((self.root / 'out/app/web/main.py').read_bytes(), b'print(1)')

    def test_dot_prefix_and_directory_after_file(self):
        path = self.archive([
            ('./app/main.py', tarfile.REGTYPE, b'data'),
            ('./app/', tarfile.DIRTYPE, b''),
        ])
        self.extract(path, self.root / 'out', 'app')
        self.assertTrue((self.root / 'out/app/main.py').is_file())

    def test_reject_unsafe_app_members_before_any_extraction(self):
        cases = [
            ('restore.sh', tarfile.REGTYPE),
            ('app/../restore.sh', tarfile.REGTYPE),
            ('/app/main.py', tarfile.REGTYPE),
            ('app\\main.py', tarfile.REGTYPE),
            ('app/a\nfile', tarfile.REGTYPE),
            ('app/link', tarfile.SYMTYPE),
            ('app/link', tarfile.LNKTYPE),
            ('app/pipe', tarfile.FIFOTYPE),
            ('app/device', tarfile.CHRTYPE),
            ('app/device', tarfile.BLKTYPE),
            ('app', tarfile.REGTYPE),
        ]
        for name, kind in cases:
            with self.subTest(name=name, kind=kind):
                path = self.archive([
                    ('app/good.py', tarfile.REGTYPE, b'good'),
                    (name, kind, b''),
                ])
                with self.assertRaises(ValueError):
                    self.extract(path, self.root / 'out', 'app')
                self.assertFalse((self.root / 'out').exists())

    def test_duplicate_and_file_parent_are_rejected(self):
        for names in [('app/a', './app/a'), ('app/a', 'app/a/b')]:
            with self.subTest(names=names):
                path = self.archive([(n, tarfile.REGTYPE, b'x') for n in names])
                with self.assertRaises(ValueError):
                    self.extract(path, self.root / 'out', 'app')

    def test_normal_backup(self):
        path = self.archive([
            ('backup_20260908/app.tar.gz', tarfile.REGTYPE, b'archive'),
            ('backup_20260908/db.sqlite', tarfile.REGTYPE, b'database'),
            ('backup_20260908/manifest.txt', tarfile.REGTYPE, b'manifest'),
        ])
        self.extract(path, self.root / 'out', 'backup')
        self.assertEqual((self.root / 'out/backup_20260908/db.sqlite').read_bytes(), b'database')

    def test_backup_rejects_extra_root_component_or_missing_app(self):
        for extra in ['backup_other/db.sqlite', 'backup_1/restore.sh', 'backup_1/app/main.py']:
            with self.subTest(extra=extra):
                path = self.archive([
                    ('backup_1/app.tar.gz', tarfile.REGTYPE, b'x'),
                    (extra, tarfile.REGTYPE, b'x'),
                ])
                with self.assertRaises(ValueError):
                    self.extract(path, self.root / 'out', 'backup')
        path = self.archive([('backup_1/db.sqlite', tarfile.REGTYPE, b'x')])
        with self.assertRaises(ValueError):
            self.extract(path, self.root / 'out', 'backup')

    def test_existing_destination_is_never_overwritten(self):
        path = self.archive([('app/a', tarfile.REGTYPE, b'x')])
        dest = self.root / 'out'
        dest.mkdir()
        (dest / 'sentinel').write_text('unchanged')
        with self.assertRaises(ValueError):
            self.extract(path, dest, 'app')
        self.assertEqual((dest / 'sentinel').read_text(), 'unchanged')

    def test_invalid_and_empty_archives(self):
        path = self.archive([])
        with self.assertRaises(ValueError):
            self.extract(path, self.root / 'out', 'app')
        path.write_bytes(b'not gzip')
        with self.assertRaises(tarfile.TarError):
            self.extract(path, self.root / 'out', 'app')

    def test_oversized_member_is_rejected_before_writing(self):
        path = self.root / 'large.tar.gz'
        with tarfile.open(path, 'w:gz') as archive:
            info = tarfile.TarInfo('app/huge')
            info.size = 16 * 1024 ** 3 + 1
            archive.addfile(info)  # Header only; do not allocate the claimed payload.
        with self.assertRaisesRegex(ValueError, 'size or file-count'):
            self.extract(path, self.root / 'out', 'app')
        self.assertFalse((self.root / 'out').exists())


class EnrollmentTests(unittest.TestCase):
    def setUp(self):
        self.user = SimpleNamespace(
            id=1, username='admin', password='password', totp_enabled=False,
            totp_secret='', totp_backup_codes='[]', totp_pending_secret='',
            totp_pending_expires=0,
        )
        self.reject_update = False
        test = self

        class Query:
            def filter_by(self, **conditions):
                self.conditions = conditions
                return self

            def filter(self, condition):
                self.expiry = condition
                return self

            def update(self, values):
                if test.reject_update:
                    return 0
                if not all(getattr(test.user, k) == v for k, v in self.conditions.items()):
                    return 0
                if hasattr(self, 'expiry') and test.user.totp_pending_expires <= self.expiry:
                    return 0
                for key, value in values.items():
                    setattr(test.user, key, value)
                return 1

        class ExpiryColumn:
            def __gt__(self, other):
                return other

        class TOTP:
            def __init__(self, secret):
                self.secret = secret

            def provisioning_uri(self, **kwargs):
                return 'otpauth://test'

            def verify(self, code, **kwargs):
                return code == '123456'

        self.ns = {
            'current_user': self.user,
            'Admin': SimpleNamespace(query=Query(), totp_pending_expires=ExpiryColumn()),
            'db': SimpleNamespace(session=SimpleNamespace(commit=lambda: None, rollback=lambda: None)),
            'jsonify': lambda value: value,
            'request': SimpleNamespace(json={}),
            'time': time, 'json': json, 'secrets': secrets,
            'bcrypt': SimpleNamespace(
                generate_password_hash=lambda value: ('hash:' + value).encode(),
                check_password_hash=lambda hashed, value: hashed == value,
            ),
            'logger': SimpleNamespace(info=lambda *args: None, warning=lambda *args: None, error=lambda *args: None),
        }
        self.setup = load_function('api_2fa_setup', self.ns)
        self.enable = load_function('api_2fa_enable', self.ns)
        self.disable = load_function('api_2fa_disable', self.ns)
        modules = patch.dict('sys.modules', {
            'pyotp': SimpleNamespace(random_base32=lambda: secrets.token_hex(16), TOTP=TOTP),
            'qrcode': None,
        })
        modules.start()
        self.addCleanup(modules.stop)

    def test_existing_2fa_survives_setup(self):
        self.user.totp_enabled = True
        self.user.totp_secret = 'active'
        self.user.totp_backup_codes = '["keep"]'
        before = vars(self.user).copy()
        self.assertEqual(self.setup()[1], 409)
        self.assertEqual(vars(self.user), before)

    def test_setup_is_pending_until_valid_confirmation(self):
        result = self.setup()
        secret = result['secret']
        self.assertFalse(self.user.totp_enabled)
        self.assertEqual(self.user.totp_secret, '')
        self.assertEqual(self.user.totp_pending_secret, secret)
        self.ns['request'].json = {'code': 'wrong'}
        self.assertEqual(self.enable()[1], 400)
        self.assertFalse(self.user.totp_enabled)
        self.ns['request'].json = {'code': '123456'}
        codes = self.enable()['backup_codes']
        self.assertEqual(len(codes), 10)
        self.assertTrue(self.user.totp_enabled)
        self.assertEqual(self.user.totp_secret, secret)
        self.assertEqual(self.user.totp_pending_secret, '')
        self.assertEqual(self.user.totp_pending_expires, 0)
        stored = self.user.totp_backup_codes
        self.assertEqual(self.enable()[1], 409)
        self.assertEqual(self.user.totp_backup_codes, stored)

    def test_expired_or_missing_enrollment_cannot_enable(self):
        self.ns['request'].json = {'code': '123456'}
        self.assertEqual(self.enable()[1], 400)
        self.setup()
        self.user.totp_pending_expires = int(time.time()) - 1
        self.assertEqual(self.enable()[1], 400)
        self.assertFalse(self.user.totp_enabled)

    def test_lost_concurrent_update_does_not_report_success(self):
        self.setup()
        before = vars(self.user).copy()
        self.reject_update = True
        self.ns['request'].json = {'code': '123456'}
        self.assertEqual(self.enable()[1], 409)
        self.assertEqual(vars(self.user), before)

    def test_disable_requires_password_and_clears_pending(self):
        self.setup()
        self.user.totp_enabled = True
        before = vars(self.user).copy()
        self.ns['request'].json = {'password': 'wrong'}
        self.assertEqual(self.disable()[1], 403)
        self.assertEqual(vars(self.user), before)
        self.ns['request'].json = {'password': 'password'}
        self.assertIn('message', self.disable())
        self.assertFalse(self.user.totp_enabled)
        self.assertEqual(self.user.totp_pending_secret, '')
        self.assertEqual(self.user.totp_pending_expires, 0)


class MigrationTests(unittest.TestCase):
    def test_existing_credentials_survive_idempotent_migration(self):
        connection = sqlite3.connect(':memory:')
        self.addCleanup(connection.close)
        connection.execute('CREATE TABLE admin (id INTEGER PRIMARY KEY, totp_secret TEXT, totp_enabled INTEGER)')
        connection.execute("INSERT INTO admin VALUES (1, 'active-secret', 1)")
        namespace = {
            'db': SimpleNamespace(session=connection), 'text': lambda sql: sql,
            '_get_table_columns': lambda table: {r[1] for r in connection.execute('PRAGMA table_info(admin)')},
        }
        migrate = load_function('_migration_007_pending_totp', namespace)
        migrate()
        migrate()
        self.assertEqual(connection.execute('SELECT * FROM admin').fetchone(), (1, 'active-secret', 1, '', 0))


if __name__ == '__main__':
    unittest.main()
