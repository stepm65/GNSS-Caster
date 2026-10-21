"""Real journal files and hashes; all services, ownership and locks are isolated."""
import contextlib
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import stat
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('recovery', ROOT / 'runtime/recovery.py')
recovery = importlib.util.module_from_spec(spec)
spec.loader.exec_module(recovery)


class JournalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.snapshots = root / 'snapshots'
        self.snapshots.mkdir()
        self.path = self.snapshots / 'rollback-fixture'
        self.path.mkdir()
        self.base = root / 'runtime'
        (self.base / 'app').mkdir(parents=True)
        (self.base / 'app/version.py').write_text('__version__ = "3.3.2"\n')
        for name, content in [('recover.sh', '#!/bin/bash\nexit 0\n'), ('service-state.json', '{"caster_active": "1"}'),
                              ('paths.list', '/opt/gnss-caster/app\n'), ('existed.list', '/opt/gnss-caster/app\n'),
                              ('missing.list', '')]:
            (self.path / name).write_text(content)
        (self.path / 'files').mkdir()
        (self.path / 'files/app.py').write_text('original')
        patches = [
            patch.object(recovery, 'ROOT', self.snapshots),
            patch.object(recovery, 'BASE', self.base),
            patch.object(recovery, 'trusted_directory'), patch.object(recovery, 'trusted_file'),
            patch.object(recovery, 'boot_id', return_value='boot-fixture'),
            patch.object(recovery, 'process_identity', side_effect=lambda pid: 'start-' + str(pid)),
        ]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)
        recovery.begin(self.path, 'repair', '3.3.3', 123)

    def test_service_state_and_program_are_durable_before_snapshot_completion(self):
        state = recovery.read_state(self.path)
        self.assertEqual(state['phase'], 'snapshotting')
        self.assertEqual(state['previous_version'], '3.3.2')
        self.assertEqual(state['services']['caster_active'], '1')
        self.assertFalse(state['snapshot_ready'])
        recovery.verify(self.path, state)
        self.assertEqual(list(self.path.glob('.journal-*')), [])

    def test_complete_snapshot_detects_file_tampering_and_missing_members(self):
        recovery.ready(self.path)
        state = recovery.read_state(self.path)
        recovery.verify(self.path, state)
        (self.path / 'files/app.py').write_text('modified')
        with self.assertRaisesRegex(recovery.RecoveryError, 'manifest'):
            recovery.verify(self.path, state)
        (self.path / 'files/app.py').write_text('original')
        (self.path / 'existed.list').unlink()
        with self.assertRaises(OSError):
            recovery.verify(self.path, state)

    def test_failed_ready_write_never_claims_snapshot_is_complete(self):
        with patch.object(recovery, 'inventory', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                recovery.ready(self.path)
        self.assertFalse(recovery.read_state(self.path)['snapshot_ready'])

    def test_pending_operation_blocks_new_maintenance_and_wrong_boot(self):
        with self.assertRaisesRegex(recovery.RecoveryError, 'rollback-fixture'):
            recovery.preflight()
        recovery.mark(self.path, 'health')
        with patch.object(recovery, 'boot_id', return_value='different-boot'):
            with self.assertRaisesRegex(recovery.RecoveryError, 'startup blocked'):
                recovery.boot_check()

    def test_boot_gate_requires_health_stage_matching_process_and_held_lock(self):
        @contextlib.contextmanager
        def busy(*args, **kwargs):
            raise recovery.RecoveryError('Another maintenance operation or rover admission is running')
            yield
        with patch.object(recovery, 'exclusive', busy):
            with self.assertRaises(recovery.RecoveryError):
                recovery.boot_check()  # Copying a snapshot is never a start gate.
            recovery.mark(self.path, 'health')
            recovery.boot_check()
            with patch.object(recovery, 'process_identity', return_value='reused-pid'):
                with self.assertRaises(recovery.RecoveryError):
                    recovery.boot_check()
        with patch.object(recovery, 'exclusive', return_value=contextlib.nullcontext()):
            with self.assertRaises(recovery.RecoveryError):
                recovery.boot_check()

    def test_completed_transaction_does_not_block_boot_or_new_maintenance(self):
        recovery.ready(self.path)
        recovery.mark(self.path, 'committed')
        recovery.preflight()
        recovery.boot_check()
        self.assertNotIn('inventory', recovery.summary(self.path, recovery.read_state(self.path)))

    def test_recovery_verifies_before_any_service_action_and_retains_locks_for_child(self):
        recovery.ready(self.path)
        events = []
        @contextlib.contextmanager
        def locked(path, **kwargs):
            events.append('lock')
            yield 7
            events.append('unlock')
        def run(args, **kwargs):
            self.assertEqual(events, ['lock', 'lock', 'work_checked'])
            self.assertEqual(args[-1], '--restore')
            self.assertEqual(kwargs['pass_fds'], (7, 7))
            return NS(returncode=0)
        with patch.object(recovery, 'exclusive', locked), \
             patch.object(recovery, 'check_live_work', side_effect=lambda: events.append('work_checked')), \
             patch.object(recovery, 'run', side_effect=run):
            result = recovery.recover(self.path)
        self.assertEqual(result['phase'], 'rolled_back')
        self.assertEqual(events[-2:], ['unlock', 'unlock'])

    def test_partial_snapshot_only_resumes_services_without_replacing_files(self):
        with patch.object(recovery, 'exclusive', side_effect=lambda *a, **k: contextlib.nullcontext(7)), \
             patch.object(recovery, 'check_live_work'), \
             patch.object(recovery, 'run', return_value=NS(returncode=0)) as run:
            result = recovery.recover(self.path)
        self.assertEqual(run.call_args.args[0][-1], '--services-only')
        self.assertEqual(result['phase'], 'snapshot_failed')

    def test_recovery_failure_is_persisted_and_can_be_retried(self):
        recovery.ready(self.path)
        with patch.object(recovery, 'exclusive', side_effect=lambda *a, **k: contextlib.nullcontext(7)), \
             patch.object(recovery, 'check_live_work'), \
             patch.object(recovery, 'run', return_value=NS(returncode=1)):
            with self.assertRaises(recovery.RecoveryError):
                recovery.recover(self.path)
        state = recovery.read_state(self.path)
        self.assertEqual(state['phase'], 'rollback_failed')
        recovery.verify(self.path, state)
        with self.assertRaises(recovery.RecoveryError):
            recovery.boot_check()

    def test_corrupted_snapshot_never_reaches_service_manager(self):
        recovery.ready(self.path)
        (self.path / 'recover.sh').write_text('changed')
        with patch.object(recovery, 'exclusive', side_effect=lambda *a, **k: contextlib.nullcontext(7)), \
             patch.object(recovery, 'check_live_work') as live, patch.object(recovery, 'run') as run:
            with self.assertRaises(recovery.RecoveryError):
                recovery.recover(self.path)
        live.assert_not_called()
        run.assert_not_called()

    def test_failed_atomic_replace_keeps_previous_journal(self):
        before = (self.path / 'transaction.json').read_bytes()
        with patch.object(recovery.os, 'replace', side_effect=OSError('injected interruption')):
            with self.assertRaises(OSError):
                recovery.mark(self.path, 'health')
        self.assertEqual((self.path / 'transaction.json').read_bytes(), before)
        self.assertEqual(list(self.path.glob('.journal-*')), [])

    def test_no_path_traversal_or_foreign_root_is_accepted(self):
        for value in ('../rollback-other', '/tmp/rollback-fixture', 'rollback-a/../rollback-fixture'):
            with self.subTest(value=value), self.assertRaises(recovery.RecoveryError):
                recovery.snapshot_path(value)

    def test_running_field_work_and_connected_rovers_block_recovery(self):
        instance = self.base / 'instance'
        instance.mkdir()
        database = instance / 'db.sqlite'
        (instance / 'config.yaml').write_text(f'database:\n  path: "{database}"\n')
        with contextlib.closing(sqlite3.connect(database)) as db:
            db.execute('CREATE TABLE rover(active_conn INTEGER)')
            db.execute('INSERT INTO rover VALUES (1)')
            db.execute('CREATE TABLE system_setting(key TEXT, value TEXT)')
            db.execute("INSERT INTO system_setting VALUES ('field_work_active', 'false')")
            db.commit()
            with patch.object(recovery, 'run', return_value=NS(returncode=0, stdout='active\n')):
                with self.assertRaisesRegex(recovery.RecoveryError, 'Disconnect'):
                    recovery.check_live_work()
                db.execute('UPDATE rover SET active_conn=0')
                db.execute("UPDATE system_setting SET value='true'")
                db.commit()
                with self.assertRaisesRegex(recovery.RecoveryError, 'field work'):
                    recovery.check_live_work()
                db.execute("UPDATE system_setting SET value='false'")
                db.commit()
                recovery.check_live_work()

    def test_stopped_service_can_recover_broken_database_but_unknown_state_cannot(self):
        for state in ('inactive', 'failed'):
            with patch.object(recovery, 'run', return_value=NS(returncode=0, stdout=state)):
                recovery.check_live_work()
        for state in ('activating', 'deactivating', ''):
            with patch.object(recovery, 'run', return_value=NS(returncode=0, stdout=state)), \
                 self.assertRaises(recovery.RecoveryError):
                recovery.check_live_work()


class MetadataProtectionTests(unittest.TestCase):
    def test_unsafe_metadata_ownership_links_and_permissions_are_rejected(self):
        for mode, owner, links in [(stat.S_IFREG | 0o600, 123, 1),
                                   (stat.S_IFREG | 0o660, 0, 1),
                                   (stat.S_IFLNK | 0o600, 0, 1),
                                   (stat.S_IFREG | 0o600, 0, 2)]:
            with self.subTest(mode=mode, owner=owner, links=links), \
                 patch.object(Path, 'lstat', return_value=NS(st_mode=mode, st_uid=owner, st_nlink=links)), \
                 self.assertRaises(recovery.RecoveryError):
                recovery.trusted_file(Path('fixture'))
