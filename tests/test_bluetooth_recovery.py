import ast
import threading
import time
import unittest
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch
from test_security_regressions import SOURCE

BODY = SOURCE.split("cat > $APP/bluetooth/core.py << 'EOF'\n", 1)[1].split('\nEOF\n', 1)[0]
NODE = next(n for n in ast.walk(ast.parse(BODY)) if isinstance(n, ast.FunctionDef) and n.name == '_maybe_recover_bluetooth')

class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.helper = Mock(return_value=NS(returncode=0))
        ns = {'time': time, 'logger': Mock(), '_run_privileged_helper': self.helper}
        exec(compile(ast.Module(body=[NODE], type_ignores=[]), '<bluetooth>', 'exec'), ns)
        self.run_recovery = ns['_maybe_recover_bluetooth']
        self.m = NS(lock=threading.Lock(), connections={}, _connect_failure_streak={},
                    _last_adapter_recovery_at=0, _adapter_recovery_attempts=0,
                    _adapter_recovery_running=False, _adapter_recovery_state={},
                    adapter_recovery_after_failures=1, adapter_recovery_cooldown=240)

    def test_connected_station_prevents_shared_adapter_reset(self):
        self.m.connections['other'] = {'connected': True}
        self.run_recovery(self.m, '1', 'Host is down')
        self.helper.assert_not_called()

    def test_success_waits_for_real_connection(self):
        self.run_recovery(self.m, '1', 'Host is down')
        self.assertEqual(self.m._adapter_recovery_state['status'], 'waiting_for_connection')
        self.assertFalse(self.m._adapter_recovery_running)

    def test_clock_change_does_not_bypass_cooldown(self):
        with patch.object(time, 'monotonic', return_value=1000):
            self.run_recovery(self.m, '1', 'Host is down')
        with patch.object(time, 'monotonic', return_value=1001), patch.object(time, 'time', return_value=9999999999):
            self.run_recovery(self.m, '2', 'Host is down')
        self.assertEqual(self.helper.call_count, 1)

    def test_simultaneous_failure_cannot_start_second_reset(self):
        entered, release = threading.Event(), threading.Event()
        def helper(*args, **kwargs):
            entered.set()
            self.assertTrue(release.wait(3))
            return NS(returncode=0)
        self.helper.side_effect = helper
        t = threading.Thread(target=self.run_recovery, args=(self.m, '1', 'Host is down'))
        t.start()
        try:
            self.assertTrue(entered.wait(3))
            self.run_recovery(self.m, '2', 'Host is down')
            self.assertEqual(self.helper.call_count, 1)
        finally:
            release.set(); t.join(3)

    def test_failure_releases_reservation(self):
        self.helper.side_effect = TimeoutError('timeout')
        self.run_recovery(self.m, '1', 'Host is down')
        self.assertFalse(self.m._adapter_recovery_running)
        self.assertEqual(self.m._adapter_recovery_state['status'], 'failed')

    def test_deep_recovery_preserves_pairing(self):
        self.m._adapter_recovery_attempts = 1
        self.run_recovery(self.m, '1', 'Host is down')
        self.helper.assert_called_once_with(['recover-bluetooth-deep'], timeout=60)
        helper = SOURCE.split('    recover-bluetooth-deep)', 1)[1].split('    recover-bluetooth)', 1)[0]
        self.assertNotIn('bluetoothctl remove', helper)

    def test_unrelated_error_does_not_reset(self):
        self.run_recovery(self.m, '1', 'Permission denied')
        self.helper.assert_not_called()

if __name__ == '__main__':
    unittest.main()
