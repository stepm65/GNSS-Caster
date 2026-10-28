"""Real temporary archives/SQLite plus API and shell gates; no operational host."""
from contextlib import closing
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
import unittest
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch
from test_security_regressions import load_function, SOURCE
from test_rollback_regressions import find_bash

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('backup_format', ROOT/'runtime/backup_format.py')
backup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backup)


class CompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ROOT/'tests')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.payload = self.root/'backup_test'
        self.payload.mkdir()
        self.db = self.payload/'db.sqlite'
        with closing(sqlite3.connect(self.db)) as db, db:
            db.executescript('''CREATE TABLE admin(id INTEGER PRIMARY KEY, username TEXT);
                CREATE TABLE base_station(id INTEGER PRIMARY KEY, name TEXT);
                CREATE TABLE rover(id INTEGER PRIMARY KEY, name TEXT);
                CREATE TABLE system_setting(key TEXT PRIMARY KEY, value TEXT);
                CREATE TABLE schema_migration(version INTEGER PRIMARY KEY, name TEXT, applied_at INTEGER);
                INSERT INTO admin VALUES(1,'test'); INSERT INTO rover VALUES(1,'rover');''')
            db.executemany('INSERT INTO schema_migration VALUES(?,?,0)', [(i,str(i)) for i in range(1,9)])
        self.target = self.root/'current.sqlite'
        shutil.copyfile(self.db,self.target)
        (self.payload/'config.yaml').write_text('database:\n  path: /opt/gnss-caster/instance/db.sqlite\n',encoding='utf-8')
        (self.payload/'config.py').write_text("raise RuntimeError('Archived Python must not execute')\n")
        app = self.root/'app'
        app.mkdir()
        (app/'main.py').write_text("raise RuntimeError('Archived code must not execute')\n")
        with tarfile.open(self.payload/'app.tar.gz','w:gz') as tar:
            tar.add(app,arcname='app')
        self.manifest()

    def manifest(self, version='3.4.1'):
        (self.payload/'manifest.json').unlink(missing_ok=True)
        return backup.create_manifest(self.payload,version)

    def inspect(self):
        return backup.inspect_payload(self.payload,self.target,'3.4.1')

    def archive(self):
        path = self.root/'backup_test.tar.gz'
        with tarfile.open(path,'w:gz') as tar: tar.add(self.payload,arcname=self.payload.name)
        return path

    def edit_manifest(self, change):
        path = self.payload/'manifest.json'
        data=json.loads(path.read_text())
        change(data)
        path.write_text(json.dumps(data))

    def test_manifest_roundtrip_and_preview_do_not_execute_archived_code(self):
        path=self.archive()
        result=backup.preview_archive(path,self.target,'3.4.1')
        self.assertTrue(result['compatible'])
        self.assertFalse(result['legacy'])
        self.assertEqual(result['counts']['rover'],1)
        self.assertEqual(result['archive_sha256'],hashlib.sha256(path.read_bytes()).hexdigest())
        self.assertEqual([c['name'] for c in result['components'] if c['restored']],['config.yaml','db.sqlite'])

    def test_future_source_or_minimum_version_is_incompatible(self):
        self.manifest('3.5.0')
        self.assertFalse(self.inspect()['compatible'])
        self.manifest()
        self.edit_manifest(lambda d:d['restore'].update(minimum_version='3.4.2'))
        self.assertFalse(self.inspect()['compatible'])

    def test_unknown_contract_and_format_are_not_silently_applied(self):
        self.edit_manifest(lambda d:d['restore'].update(data_contract=2))
        self.assertFalse(self.inspect()['compatible'])
        self.edit_manifest(lambda d:d.update(format_version=3))
        with self.assertRaisesRegex(backup.BackupError,'format version'): self.inspect()

    def test_component_tampering_and_manifest_schema_mismatch_fail(self):
        (self.payload/'config.yaml').write_text('changed')
        with self.assertRaisesRegex(backup.BackupError,'checksums'): self.inspect()
        self.manifest()
        self.edit_manifest(lambda d:d['database'].update(migration=7))
        with self.assertRaisesRegex(backup.BackupError,'schema'): self.inspect()

    def test_matching_claim_does_not_hide_actual_schema_difference(self):
        with closing(sqlite3.connect(self.db)) as db, db: db.execute('ALTER TABLE rover ADD COLUMN unexpected TEXT')
        self.manifest()
        result=self.inspect()
        self.assertFalse(result['compatible'])
        self.assertIn('The backup database structure differs from this installation.',result['reasons'])

    def test_legacy_with_matching_schema_is_readable_with_explicit_limitations(self):
        (self.payload/'manifest.json').unlink()
        lines=[f'- {backup.LABELS[name]} SHA256: {backup.digest(self.payload/name)}' for name in ('db.sqlite','app.tar.gz')]
        (self.payload/'manifest.txt').write_text('\n'.join(lines)+'\n')
        result=self.inspect()
        self.assertTrue(result['compatible'])
        self.assertTrue(result['legacy'])
        self.assertIsNone(result['source_version'])
        self.assertEqual(len(result['warnings']),2)

    def test_removed_unique_constraint_is_not_schema_compatible(self):
        with closing(sqlite3.connect(self.db)) as db, db:
            db.executescript('DROP TABLE system_setting; CREATE TABLE system_setting(key TEXT, value TEXT);')
        self.manifest()
        self.assertFalse(self.inspect()['compatible'])

    def test_legacy_checksum_is_required_for_database(self):
        (self.payload/'manifest.json').unlink()
        (self.payload/'manifest.txt').write_text('no checksums')
        with self.assertRaisesRegex(backup.BackupError,'checksum'): self.inspect()

    def test_missing_or_future_migrations_are_not_assumed_compatible(self):
        with closing(sqlite3.connect(self.db)) as db, db: db.execute('DELETE FROM schema_migration WHERE version=8')
        with self.assertRaisesRegex(backup.BackupError,'schema'): self.manifest()
        with closing(sqlite3.connect(self.db)) as db, db: db.execute("INSERT INTO schema_migration VALUES(9223372036854775807,'unknown',0)")
        with self.assertRaisesRegex(backup.BackupError,'migration history'): backup.database_info(self.db)

    def test_views_and_triggers_in_database_are_rejected(self):
        with closing(sqlite3.connect(self.db)) as db, db: db.execute('CREATE VIEW leaked AS SELECT * FROM admin')
        with self.assertRaisesRegex(backup.BackupError,'schema objects'): backup.database_info(self.db)
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute('DROP VIEW leaked')
            db.execute('CREATE TRIGGER injected AFTER INSERT ON rover BEGIN DELETE FROM admin; END')
        with self.assertRaisesRegex(backup.BackupError,'schema objects'): backup.database_info(self.db)

    def test_duplicate_fields_missing_payload_and_custom_database_are_rejected(self):
        (self.payload/'manifest.json').write_text('{"format":1,"format":2}')
        with self.assertRaisesRegex(backup.BackupError,'duplicate'): self.inspect()
        self.manifest()
        (self.payload/'config.yaml').write_text('database:\n  path: /tmp/elsewhere.sqlite\n')
        self.manifest()
        self.assertFalse(self.inspect()['compatible'])
        (self.payload/'db.sqlite').unlink()
        with self.assertRaisesRegex(backup.BackupError,'missing'): self.inspect()

    def test_archive_change_produces_a_different_preview_hash(self):
        path=self.archive()
        before=backup.preview_archive(path,self.target,'3.4.1')['archive_sha256']
        with closing(sqlite3.connect(self.db)) as db, db: db.execute("INSERT INTO rover VALUES(2,'second')")
        self.manifest()
        after=backup.preview_archive(self.archive(),self.target,'3.4.1')['archive_sha256']
        self.assertNotEqual(before,after)

    def test_bounded_input_and_manifest_reject_before_unbounded_read(self):
        path=self.archive()
        with patch.object(backup,'MAX_ARCHIVE',16),self.assertRaisesRegex(backup.BackupError,'256 MiB'):
            backup.preview_archive(path,self.target,'3.4.1')
        (self.payload/'manifest.json').write_text(' '*65537)
        with self.assertRaisesRegex(backup.BackupError,'too large'):
            backup.preview_archive(self.archive(),self.target,'3.4.1')

    @unittest.skipUnless(shutil.which('openssl'),'OpenSSL required')
    def test_encrypted_archive_uses_supplied_passphrase_without_logging_it(self):
        path=self.archive()
        encrypted=self.root/'backup_test.tar.gz.enc'
        subprocess.run(['openssl','enc','-aes-256-cbc','-salt','-pbkdf2','-iter','200000','-in',str(path),'-out',str(encrypted),'-pass','stdin'],input='temporary-test-passphrase\n',text=True,capture_output=True,check=True)
        result=backup.preview_archive(encrypted,self.target,'3.4.1','temporary-test-passphrase')
        self.assertTrue(result['compatible'])
        self.assertNotIn('temporary-test-passphrase',json.dumps(result))
        with self.assertRaisesRegex(backup.BackupError,'could not be decrypted'):
            backup.preview_archive(encrypted,self.target,'3.4.1','incorrect')

    @unittest.skipUnless(find_bash(),'Bash required')
    def test_root_frozen_digest_gate_rejects_replaced_archive(self):
        gate=SOURCE.split('# Freeze the input before validation;',1)[1].split('# Decrypt first',1)[0]
        gate=('# Freeze the input before validation;'+gate).replace('/usr/bin/python3','"$TEST_PYTHON"')
        base=self.root/'format'
        base.mkdir()
        shutil.copyfile(ROOT/'runtime/backup_format.py',base/'backup-format.py')
        path=self.archive()
        checksum=backup.digest(path)
        for expected, accepted in [(checksum,True),('0'*64,False)]:
            with tempfile.TemporaryDirectory(dir=self.root) as stage:
                env=dict(os.environ,BASE_DIR=base.as_posix(),BACKUP_ARCHIVE=path.as_posix(),
                         TMP_DIR=Path(stage).as_posix(),EXPECTED_ARCHIVE_SHA256=expected,
                         TEST_PYTHON=Path(sys.executable).as_posix())
                result=subprocess.run([find_bash()],input='set -e\nerror() { printf "%s" "$*"; }\n'+gate+'\nprintf "validated"\n',text=True,capture_output=True,env=env,timeout=30)
                self.assertEqual(result.returncode==0,accepted,result.stdout+result.stderr)
                self.assertEqual('validated' in result.stdout,accepted)

    @unittest.skipUnless(find_bash(),'Bash required')
    def test_root_compatibility_gate_runs_before_service_stop(self):
        gate=SOURCE.split('# Recheck the frozen archive against the current installation',1)[1].split('\nacquire_admission_guard',1)[0]
        gate='# Recheck the frozen archive against the current installation'+gate
        gate=gate.replace('/usr/bin/python3','"$TEST_PYTHON"')
        base=self.root/'runtime'
        (base/'app').mkdir(parents=True)
        (base/'instance').mkdir()
        shutil.copyfile(self.target,base/'instance/db.sqlite')
        shutil.copyfile(ROOT/'runtime/backup_format.py',base/'backup-format.py')
        (base/'app/version.py').write_text('__version__ = "3.4.1"\n')
        original=(base/'instance/db.sqlite').read_bytes()
        for version, accepted in [('3.4.1',True),('3.5.0',False)]:
            self.manifest(version)
            env=dict(os.environ,BASE_DIR=base.as_posix(),INSTANCE_DIR=(base/'instance').as_posix(),RESTORE_DIR=self.payload.as_posix(),RESTORE_DATA_ONLY='1',TEST_PYTHON=Path(sys.executable).as_posix())
            result=subprocess.run([find_bash()],input='set -e\n'+gate+'\nprintf "service-stop-would-follow"\n',text=True,capture_output=True,env=env,timeout=30)
            self.assertEqual(result.returncode==0,accepted,result.stdout+result.stderr)
            self.assertEqual('service-stop-would-follow' in result.stdout,accepted)
            self.assertEqual((base/'instance/db.sqlite').read_bytes(),original)


class ApiTests(unittest.TestCase):
    def test_preview_requires_admin_before_reading_archive(self):
        denied=({'error':'denied'},403)
        fn=load_function('api_system_backup_preview',{'_require_admin_role':lambda:denied})
        self.assertEqual(fn(),denied)

    def namespace(self,data,compatible=True):
        return {'_require_admin_role':lambda:None,'request':NS(json=data),
                '_get_system_setting_value':lambda *args:'', 'jsonify':lambda x:x,
                '_preview_backup_archive':Mock(return_value={'compatible':compatible,'archive_sha256':'a'*64}),
                '_schedule_restore_script':Mock(), 'db':NS(session=NS(rollback=Mock())), 'logger':Mock()}

    def test_incompatible_archive_cannot_be_scheduled_by_direct_api(self):
        ns=self.namespace({'filename':'backup_test.tar.gz'},False)
        result,status=load_function('api_system_backup_restore',ns)()
        self.assertEqual(status,409)
        ns['_schedule_restore_script'].assert_not_called()

    def test_changed_archive_cannot_be_scheduled_after_preview(self):
        ns=self.namespace({'filename':'backup_test.tar.gz','archive_sha256':'b'*64})
        result,status=load_function('api_system_backup_restore',ns)()
        self.assertEqual(status,409)
        ns['_schedule_restore_script'].assert_not_called()

    def test_direct_api_without_client_digest_still_passes_verified_digest_to_root(self):
        import time
        ns=self.namespace({'filename':'backup_test.tar.gz'})
        ns.update(_get_client_ip=lambda:'127.0.0.1',time=time,LogEntry=lambda **kw:kw,
                  current_user=NS(username='test'),db=NS(session=Mock()))
        ns['_schedule_restore_script'].return_value={'filename':'backup_test.tar.gz','unit_name':'test'}
        result,status=load_function('api_system_backup_restore',ns)()
        self.assertEqual(status,202)
        ns['_schedule_restore_script'].assert_called_once_with('backup_test.tar.gz','','a'*64)

    def test_broker_accepts_one_digest_and_key_but_rejects_duplicates(self):
        from test_maintenance_broker import broker
        command=['systemd-job','restore','gnss-caster-restore-1.service','backup_test.tar.gz.enc']
        key='/run/gnss-caster/restore-'+'1'*16+'.key'
        sha='sha256:'+'a'*64
        args,_=broker.validate_request({'version':1,'args':command+[key,sha]})
        self.assertEqual(args,['systemd-data-restore',*command[2:],key,sha])
        for options in ([sha,sha],[key,key],['sha256:invalid']):
            with self.assertRaises(broker.Rejected): broker.validate_request({'version':1,'args':command+options})

    def test_packaging_keeps_inspector_and_root_gate_consistent(self):
        embedded=SOURCE.split("<< 'PY_BACKUP_FORMAT' || return 1\n",1)[1].split('\nPY_BACKUP_FORMAT',1)[0]
        self.assertEqual(embedded.rstrip(),(ROOT/'runtime/backup_format.py').read_text(encoding='utf-8').rstrip())
        restore=SOURCE.split('# GNSS Caster Restore Script',1)[1]
        self.assertLess(restore.index(' validate "$RESTORE_DIR"'),restore.index('systemctl stop "$SERVICE_NAME"',restore.index(' validate "$RESTORE_DIR"')))
        self.assertIn('"$BASE/backup-format.py"',SOURCE)


if __name__=='__main__': unittest.main()
