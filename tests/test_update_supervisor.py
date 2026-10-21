"""Supervisor tests use isolated subprocesses, never systemd or a live caster."""
import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('supervised_update', ROOT / 'runtime/release_update.py')
updater = importlib.util.module_from_spec(spec)
spec.loader.exec_module(updater)


class SupervisorTests(unittest.TestCase):
    def test_install_timeout_sends_term_once_and_retains_stop_reason(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Path(directory)
            state = {}
            process = Mock(pid=123, poll=Mock(side_effect=[None, 143, 143]))
            with (store / 'maintenance.log').open('w') as log, \
                 patch.object(updater, 'STORE', store), \
                 patch.object(updater, 'INSTALL_TIMEOUT', 1), \
                 patch.object(updater.time, 'monotonic', side_effect=[0, 2, 3]), \
                 patch.object(updater.signal, 'signal'), \
                 patch.object(updater.subprocess, 'Popen', return_value=process) as launch, \
                 patch.object(updater.os, 'killpg', create=True) as kill:
                result = updater.run_installation(['/bin/bash', 'fixture'], stdout=log, pass_fds=(8,), state=state)
            self.assertEqual(result.returncode, 143)
            self.assertEqual(state['stop_reason'], 'timeout')
            kill.assert_called_once_with(123, signal.SIGTERM)
            self.assertTrue(launch.call_args.kwargs['start_new_session'])
            self.assertEqual(launch.call_args.kwargs['pass_fds'], (8,))

    def test_failed_stop_is_never_treated_as_confirmed_rollback(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Path(directory)
            state = {}
            process = Mock(pid=123, poll=Mock(side_effect=[None, None, -9]))
            with (store / 'maintenance.log').open('w') as log, \
                 patch.object(updater, 'STORE', store), \
                 patch.object(updater, 'INSTALL_TIMEOUT', 1), \
                 patch.object(updater, 'ROLLBACK_TIMEOUT', 1), \
                 patch.object(updater.signal, 'SIGKILL', 9, create=True), \
                 patch.object(updater.time, 'monotonic', side_effect=[0, 2, 4]), \
                 patch.object(updater.signal, 'signal'), \
                 patch.object(updater.subprocess, 'Popen', return_value=process), \
                 patch.object(updater.os, 'killpg', create=True) as kill:
                with self.assertRaisesRegex(updater.UpdateError, 'could not stop safely'):
                    updater.run_installation(['/bin/bash', 'fixture'], stdout=log, pass_fds=(), state=state)
            self.assertTrue(state['termination_escalated'])
            self.assertFalse(state.get('rollback_confirmed'))
            self.assertEqual([call.args[1] for call in kill.call_args_list],
                             [signal.SIGTERM, getattr(signal, 'SIGKILL', 9)])

    def test_only_known_stage_and_snapshot_coordinates_are_accepted(self):
        state = {}
        updater.record_installer_progress('GNSS maintenance stage: migration', state)
        self.assertEqual(state['phase'], 'migration')
        updater.record_installer_progress('GNSS maintenance stage: nonsense', state)
        self.assertEqual(state['phase'], 'migration')
        updater.record_installer_progress('Rollback snapshot created: /tmp/not-a-snapshot', state)
        self.assertNotIn('snapshot', state)
        updater.record_installer_progress('Rollback snapshot created: /var/backups/gnss-caster/rollback-fixture', state)
        self.assertEqual(state['snapshot'], '/var/backups/gnss-caster/rollback-fixture')

    @unittest.skipUnless(os.name == 'posix', 'Real POSIX process groups and signals')
    def test_real_term_waits_for_child_rollback_and_records_snapshot_before_exit(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Path(directory)
            child = store / 'child.sh'
            child.write_text(
                "trap 'echo \"GNSS maintenance stage: rollback\"; sleep 0.2; "
                "echo \"Rollback completed; previous service state restored.\"; exit 143' TERM\n"
                "echo 'Rollback snapshot created: /var/backups/gnss-caster/rollback-fixture'\n"
                "while true; do sleep 1; done\n", encoding='utf-8')
            harness = store / 'harness.py'
            harness.write_text(
                "import importlib.util, pathlib, sys\n"
                f"spec=importlib.util.spec_from_file_location('updater', {str(ROOT / 'runtime/release_update.py')!r})\n"
                "u=importlib.util.module_from_spec(spec); spec.loader.exec_module(u)\n"
                "u.STORE=pathlib.Path(sys.argv[1]); state={}\n"
                "with (u.STORE/'maintenance.log').open('w') as log:\n"
                " result=u.run_installation(['/bin/bash', str(u.STORE/'child.sh')], stdout=log, pass_fds=(), state=state)\n"
                "u.write_json('result.json', state)\n"
                "sys.exit(result.returncode)\n", encoding='utf-8')
            process = subprocess.Popen([sys.executable, str(harness), str(store)], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            try:
                deadline = time.monotonic() + 8
                while time.monotonic() < deadline and not (store / 'state.json').exists() and process.poll() is None:
                    time.sleep(0.02)
                self.assertTrue((store / 'state.json').exists(), 'snapshot was not persisted while installer was alive')
                self.assertIn('snapshot', json.loads((store / 'state.json').read_text()))
                self.assertIsNone(process.poll())
                process.send_signal(signal.SIGTERM)
                _, errors = process.communicate(timeout=12)
                self.assertEqual(process.returncode, 143, errors.decode())
                state = json.loads((store / 'result.json').read_text())
                self.assertEqual(state['stop_reason'], 'signal')
                self.assertTrue(state['rollback_confirmed'])
            finally:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.communicate(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.communicate(timeout=5)
