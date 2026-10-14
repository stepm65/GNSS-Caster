"""Manual Connect uses the existing station worker, not a second BlueZ link."""
import ast
import sys
import threading
import time
import unittest
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch

from test_security_regressions import SOURCE, load_function

BODY = SOURCE.split("cat > $APP/bluetooth/core.py << 'EOF'\n", 1)[1].split('\nEOF\n', 1)[0]
TREE = ast.parse(BODY)
MAC = '98:DA:10:08:81:9A'


def manager_method(name):
    node = next(n for n in ast.walk(TREE) if isinstance(n, ast.FunctionDef) and n.name == name)
    namespace = {'time': time}
    exec(compile(ast.Module(body=[node], type_ignores=[]), '<bluetooth>', 'exec'), namespace)
    return namespace[name]


class ManualRetryTests(unittest.TestCase):
    def setUp(self):
        self.signal = threading.Event()
        self.manager = NS(lock=threading.Lock(), running=True,
                          connections={'1': {'connected': False, 'retry_event': self.signal}},
                          _start_station_connection=Mock(), dbus_client=Mock())
        self.request = manager_method('request_station_connection')
        self.wait = manager_method('_wait_for_station_retry')

    def test_manual_request_wakes_backoff_without_starting_another_connection(self):
        entered, completed = threading.Event(), threading.Event()

        def worker():
            entered.set()
            self.wait(self.manager, 1, 30)
            completed.set()

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        try:
            self.assertTrue(entered.wait(1))
            success, _, state = self.request(self.manager, 1)
            self.assertTrue(success)
            self.assertEqual(state, 'connecting')
            self.assertTrue(completed.wait(1), 'Manual retry did not wake the backoff')
            self.assertFalse(self.signal.is_set())
            self.manager._start_station_connection.assert_not_called()
            self.assertEqual(self.manager.dbus_client.mock_calls, [])
        finally:
            self.signal.set()
            thread.join(2)
        self.assertFalse(thread.is_alive())

    def test_connected_station_is_preserved(self):
        self.manager.connections['1']['connected'] = True
        success, _, state = self.request(self.manager, 1)
        self.assertTrue(success)
        self.assertEqual(state, 'connected')
        self.assertFalse(self.signal.is_set())
        self.assertEqual(self.manager.dbus_client.mock_calls, [])

    def test_stopped_manager_does_not_claim_to_schedule_connection(self):
        self.manager.running = False
        success, _, state = self.request(self.manager, 1)
        self.assertFalse(success)
        self.assertEqual(state, 'stopped')
        self.assertFalse(self.signal.is_set())

    def test_missing_worker_is_left_to_the_main_loop(self):
        self.manager.connections.clear()
        success, _, state = self.request(self.manager, 1)
        self.assertTrue(success)
        self.assertEqual(state, 'connecting')
        self.manager._start_station_connection.assert_not_called()
        self.assertEqual(self.manager.connections, {})


class ConnectRouteTests(unittest.TestCase):
    def setUp(self):
        self.manager = NS(request_station_connection=Mock(return_value=(True, 'Requested', 'connecting')),
                          dbus_client=NS(connect_device=Mock(return_value=(True, 'Connected'))))
        self.query = Mock()
        self.query.all.return_value = [NS(id=7, bt_mac=MAC.lower(), connection_type='bluetooth')]
        self.namespace = {'request': NS(json={'mac': MAC}), 'jsonify': lambda data: data,
                          '_require_operator_role': lambda: None, 'BaseStation': NS(query=self.query),
                          'logger': Mock()}
        self.route = load_function('api_bluetooth_connect', self.namespace)

    def call(self):
        with patch.dict(sys.modules, {'app.bluetooth.core': NS(bluetooth_manager=self.manager)}):
            return self.route()

    def test_known_receiver_bypasses_pairing_and_reports_pending_state(self):
        result, code = self.call()
        self.assertEqual(code, 200)
        self.assertTrue(result['managed_station'])
        self.assertEqual(result['connection_state'], 'connecting')
        self.manager.request_station_connection.assert_called_once_with(7)
        self.manager.dbus_client.connect_device.assert_not_called()

    def test_ble_station_also_uses_its_own_transport_worker(self):
        self.query.all.return_value[0].connection_type = 'ble'
        result, code = self.call()
        self.assertEqual(code, 200)
        self.assertTrue(result['managed_station'])
        self.manager.dbus_client.connect_device.assert_not_called()

    def test_unconfigured_device_keeps_generic_connect(self):
        self.query.all.return_value = []
        result = self.call()
        self.assertTrue(result['success'])
        self.manager.dbus_client.connect_device.assert_called_once_with(MAC, timeout=20, scan_timeout=20, pin_code=None)
        self.manager.request_station_connection.assert_not_called()

    def test_duplicate_mac_is_rejected_without_opening_connections(self):
        self.query.all.return_value.append(NS(id=8, bt_mac=MAC, connection_type='bluetooth'))
        result, code = self.call()
        self.assertEqual(code, 409)
        self.assertIn('error', result)
        self.manager.request_station_connection.assert_not_called()
        self.manager.dbus_client.connect_device.assert_not_called()

    def test_stopped_manager_is_reported_as_unavailable(self):
        self.manager.request_station_connection.return_value = (False, 'Stopped', 'stopped')
        result, code = self.call()
        self.assertEqual(code, 503)
        self.assertFalse(result['success'])
        self.manager.dbus_client.connect_device.assert_not_called()

    def test_role_check_still_prevents_connection_changes(self):
        self.namespace['_require_operator_role'] = lambda: ({'error': 'Forbidden'}, 403)
        _, code = self.call()
        self.assertEqual(code, 403)
        self.query.all.assert_not_called()
        self.manager.request_station_connection.assert_not_called()


if __name__ == '__main__':
    unittest.main()
