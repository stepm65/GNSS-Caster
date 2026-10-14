import os
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace as NS
from unittest.mock import patch
from test_security_regressions import SOURCE

CODE = SOURCE.split("<< 'PY_SECRET_MIGRATION'\n", 1)[1].split('\nPY_SECRET_MIGRATION', 1)[0]

class SecretMigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.secure = self.root / 'root-only' / 'secrets'
        self.legacy = self.root / 'instance' / 'secret.env'
        self.legacy.parent.mkdir()
        self.legacy.write_bytes(b'SECRET_KEY=keep\nBT_DEFAULT_PIN=1234\n')
        self.ns = {'__name__':'test'}
        exec(CODE, self.ns)
        # Windows lacks O_NOFOLLOW; actual Linux no-follow behavior is not tested.
        proxy = NS(**{name:getattr(os,name) for name in ('open','fstat','fdopen','close','chmod','replace','unlink','fsync','path','O_RDONLY')})
        proxy.O_NOFOLLOW = getattr(os, 'O_NOFOLLOW', 0)
        proxy.O_NONBLOCK = getattr(os, 'O_NONBLOCK', 0)
        # Model root ownership only inside the fixture. CI runs unprivileged;
        # real file types, link counts, contents, and I/O errors remain intact.
        def root_owned(info):
            values = list(info)
            values[4] = 0  # st_uid
            return os.stat_result(values)

        class FixturePath(type(self.root)):
            def lstat(path, *args, **kwargs):
                return root_owned(super().lstat(*args, **kwargs))

        proxy.fstat = lambda fd: root_owned(os.fstat(fd))
        self.fixture_path = FixturePath
        self.ns['Path'] = FixturePath
        self.ns['os'] = proxy
        self.migrate = self.ns['migrate_secrets']

    def test_copy_preserves_key_and_legacy_until_cleanup(self):
        self.migrate('migrate', self.secure, self.legacy)
        self.assertEqual((self.secure/'secret.env').read_bytes(), self.legacy.read_bytes())
        self.assertTrue(self.legacy.exists())
        self.migrate('cleanup', self.secure, self.legacy)
        self.assertFalse(self.legacy.exists())
        self.assertTrue((self.secure/'legacy-secret.env').exists())

    def test_idempotent_migration_and_cleanup(self):
        for _ in range(2): self.migrate('migrate', self.secure, self.legacy)
        for _ in range(2): self.migrate('cleanup', self.secure, self.legacy)
        self.assertEqual((self.secure/'secret.env').read_bytes(), b'SECRET_KEY=keep\nBT_DEFAULT_PIN=1234\n')

    def test_new_key_not_overwritten_by_legacy(self):
        self.migrate('migrate', self.secure, self.legacy)
        (self.secure/'secret.env').write_bytes(b'rotated')
        self.migrate('migrate', self.secure, self.legacy)
        self.migrate('cleanup', self.secure, self.legacy)
        self.assertEqual((self.secure/'secret.env').read_bytes(), b'rotated')

    def test_old_backups_moved_after_copy(self):
        backup = self.legacy.with_name('secret.env.bak-old')
        backup.write_bytes(b'old-key')
        self.migrate('migrate', self.secure, self.legacy)
        self.assertTrue(backup.exists())
        self.migrate('cleanup', self.secure, self.legacy)
        self.assertFalse(backup.exists())
        self.assertEqual((self.secure/backup.name).read_bytes(), b'old-key')

    def test_conflict_keeps_original(self):
        self.migrate('migrate', self.secure, self.legacy)
        self.legacy.write_bytes(b'changed')
        for mode in ('migrate','cleanup'):
            with self.assertRaises(ValueError): self.migrate(mode, self.secure, self.legacy)
        self.assertEqual(self.legacy.read_bytes(), b'changed')

    def test_failed_publish_keeps_original_and_cleans_temp(self):
        with patch.object(self.ns['os'], 'replace', side_effect=OSError('injected')):
            with self.assertRaises(OSError): self.migrate('migrate', self.secure, self.legacy)
        self.assertTrue(self.legacy.exists())
        self.assertEqual(list(self.secure.glob('.secret-*')), [])

    def test_wrong_file_owner_is_rejected(self):
        with patch.object(self.ns['os'], 'fstat', return_value=NS(st_mode=0o100600, st_uid=123, st_nlink=1)):
            with self.assertRaisesRegex(ValueError, 'Unsafe secret file'):
                self.migrate('migrate', self.secure, self.legacy)
        self.assertTrue(self.legacy.exists())

    def test_wrong_directory_owner_is_rejected(self):
        with patch.object(self.fixture_path, 'lstat', return_value=NS(st_mode=0o40700, st_uid=123)):
            with self.assertRaisesRegex(ValueError, 'Unsafe secret directory'):
                self.migrate('migrate', self.secure, self.legacy)
        self.assertTrue(self.legacy.exists())

    def test_clean_install_creates_directory_without_fabricating_key(self):
        self.legacy.unlink()
        self.migrate('migrate', self.secure, self.legacy)
        self.assertTrue(self.secure.is_dir())
        self.assertFalse((self.secure/'secret.env').exists())

if __name__ == '__main__': unittest.main()
