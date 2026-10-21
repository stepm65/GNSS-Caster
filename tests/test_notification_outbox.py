"""Real temporary SQLite files; no live Telegram, caster, or clocks."""
import io
import json
import sqlite3
import tempfile
import unittest
import urllib.error
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch
from test_security_regressions import SOURCE, load_function

NOTIFY = SOURCE.split("cat > $APP/notify.py << 'EOF'\n", 1)[1].split('\nEOF\n', 1)[0]

class NotificationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.wall, self.mono = 1800000000, 1
        self.app = NS(config={'INSTANCE_DIR': self.temp.name}, extensions={})
        self.settings = dict(enabled=True, token='test-secret', chat_id='private-chat', events={}, language='en', available=True)
        self.call = Mock(return_value={'ok': True})
        self.ns = {'__name__': 'notify_test'}
        exec(compile(NOTIFY, '<notify>', 'exec'), self.ns)
        self.ns.update(time=NS(time=lambda: self.wall, monotonic=lambda: self.mono),
                       load_settings=lambda app: self.settings, _call=self.call)
        self.restart()

    def restart(self):
        self.box = self.ns['NotificationOutbox'](self.app)
        self.app.extensions['telegram_outbox'] = self.box

    def enqueue(self, key='base-down', text='offline', event='notify_station_down', cooldown=900):
        return self.box.enqueue(text, event, key, cooldown)

    def advance(self, seconds):
        self.mono += seconds
        self.wall += seconds

    def rows(self):
        with self.box.database() as conn:
            return [dict(row) for row in conn.execute('SELECT * FROM outbox ORDER BY id')]

    def test_first_alert_soon_after_boot_and_pending_deduplication(self):
        self.assertTrue(self.enqueue())
        self.assertFalse(self.enqueue())
        self.assertTrue(self.box.process_one())
        self.assertEqual(self.box.status()['counts']['delivered'], 1)
        self.assertFalse(self.enqueue())

    def test_idle_poll_does_not_rewrite_persistent_clock_or_counters(self):
        with patch.object(self.box, 'put_meta', wraps=self.box.put_meta) as write:
            self.assertFalse(self.box.process_one())
            self.advance(20)
            self.assertFalse(self.box.process_one())
            write.assert_not_called()

    def test_cooldown_starts_after_success_and_ignores_wall_clock_jump(self):
        self.call.side_effect = OSError('network error containing test-secret')
        self.enqueue(); self.box.process_one(); self.advance(5)
        self.call.side_effect = None
        self.box.process_one()
        self.wall += 10000000
        self.assertFalse(self.enqueue())
        self.advance(900)
        self.assertTrue(self.enqueue())

    def test_offline_retry_cannot_follow_its_newer_recovery_notice(self):
        self.enqueue(); self.enqueue('up', 'online', 'notify_station_up', 300)
        self.call.return_value = {'ok': False, 'error_code': 503}
        self.box.process_one(); self.advance(4)
        self.assertFalse(self.box.process_one())
        self.call.return_value = {'ok': True}
        self.advance(1); self.box.process_one(); self.advance(4); self.box.process_one()
        self.assertEqual([c.args[2]['text'] for c in self.call.call_args_list], ['offline', 'offline', 'online'])

    def test_restart_keeps_pending_and_successful_cooldown(self):
        self.enqueue(); self.restart()
        self.assertFalse(self.enqueue())
        self.box.process_one(); self.restart()
        self.assertFalse(self.enqueue())
        self.assertEqual(self.box.status()['counts']['delivered'], 1)

    def test_restart_with_backward_clock_does_not_stall(self):
        self.enqueue(); self.box.process_one()
        self.wall -= 10000000
        self.restart()
        self.assertFalse(self.enqueue())
        self.advance(900)
        self.assertTrue(self.enqueue())

    def test_429_waits_retry_after_across_restart_and_paces_next_event(self):
        self.call.return_value = {'ok': False, 'error_code': 429, 'parameters': {'retry_after': 120}}
        self.enqueue(); self.box.process_one(); self.enqueue('up', 'online', 'notify_station_up')
        self.restart(); self.advance(119)
        self.assertFalse(self.box.process_one())
        self.call.return_value = {'ok': True}
        self.advance(1); self.box.process_one()
        self.assertIn('Event recorded at', self.call.call_args.args[2]['text'])
        self.assertFalse(self.box.process_one())
        self.advance(4); self.box.process_one()
        self.assertEqual(self.box.status()['counts']['delivered'], 2)

    def test_crash_during_delivery_retains_attempt_and_lease(self):
        self.enqueue()
        self.box.deliver = Mock(side_effect=SystemExit)
        with self.assertRaises(SystemExit): self.box.process_one()
        self.restart()
        self.assertFalse(self.box.process_one())
        self.assertEqual(self.rows()[0]['attempts'], 1)
        self.advance(90); self.box.process_one()
        self.assertEqual(self.rows()[0]['attempts'], 2)
        self.assertEqual(self.rows()[0]['state'], 'delivered')

    def test_permanent_errors_do_not_retry_or_consume_cooldown(self):
        for code in (400, 401, 403):
            self.call.return_value = {'ok': False, 'error_code': code, 'description': 'PRIVATE DATA'}
            self.enqueue(str(code)); self.box.process_one()
            self.assertEqual(self.rows()[-1]['state'], 'failed')
            self.advance(4)
        self.assertTrue(self.enqueue('400'))
        self.assertNotIn('PRIVATE DATA', json.dumps(self.box.status()))

    def test_retry_count_is_bounded(self):
        self.enqueue()
        self.call.side_effect = TimeoutError('offline')
        for index in range(8):
            self.box.process_one()
            if index < 7: self.advance(min(300, 5*2**index))
        self.assertEqual(self.call.call_count, 8)
        self.assertEqual(self.rows()[0]['state'], 'failed')
        self.assertFalse(self.box.process_one())

    def test_expiry_releases_key_and_never_sends_stale_event(self):
        self.enqueue(); self.advance(1800); self.box.process_one()
        self.call.assert_not_called()
        self.assertEqual(self.box.status()['counts']['expired'], 1)
        self.assertTrue(self.enqueue())

    def test_retry_after_cannot_be_bypassed_by_expiry(self):
        self.call.return_value = {'ok': False, 'error_code': 429, 'parameters': {'retry_after': 3600}}
        self.enqueue(); self.box.process_one(); self.advance(1800); self.enqueue('new'); self.box.process_one()
        self.assertEqual(self.call.call_count, 1)
        self.assertEqual(self.box.status()['counts']['expired'], 1)

    def test_settings_change_cancels_pending_without_new_recipient(self):
        for mode in ('disabled', 'category', 'token', 'chat'):
            self.settings.update(enabled=True, token='test-secret', chat_id='private-chat', events={})
            self.enqueue(mode)
            if mode == 'disabled': self.settings['enabled'] = False
            if mode == 'category': self.settings['events']['notify_station_down'] = False
            if mode == 'token': self.settings['token'] = 'other-token'
            if mode == 'chat': self.settings['chat_id'] = 'other-chat'
            self.box.process_one()
        self.call.assert_not_called()
        self.assertEqual(self.box.status()['counts']['cancelled'], 4)

    def test_disabled_producer_does_not_consume_cooldown(self):
        self.settings['enabled'] = False
        self.assertFalse(self.enqueue())
        self.settings['enabled'] = True
        self.assertTrue(self.enqueue())

    def test_settings_read_failure_retains_pending(self):
        self.enqueue(); self.settings['available'] = False
        with self.assertRaises(RuntimeError): self.box.process_one()
        self.assertEqual(self.rows()[0]['state'], 'pending')
        self.call.assert_not_called()

    def test_capacity_and_terminal_history_are_bounded(self):
        self.box.CAPACITY, self.box.HISTORY = 3, 2
        for index in range(3): self.assertTrue(self.enqueue(str(index)))
        self.assertFalse(self.enqueue('overflow'))
        self.assertEqual(self.box.status()['counts']['overflow'], 1)
        for _ in range(3): self.box.process_one(); self.advance(4)
        self.assertEqual(len(self.rows()), 2)
        self.assertEqual(self.box.status()['counts']['delivered'], 3)
        self.assertTrue(all(not row['text'] for row in self.rows()))

    def test_concurrent_producers_reserve_one_key(self):
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda _: self.enqueue(), range(32)))
        self.assertEqual(sum(results), 1)
        self.assertEqual(self.box.status()['pending'], 1)

    def test_network_call_holds_no_database_transaction(self):
        def call(*args, **kwargs):
            other = self.ns['NotificationOutbox'](self.app)
            self.assertTrue(other.enqueue('online', 'notify_station_up', 'up', 60))
            self.assertFalse(other.process_one())
            return {'ok': True}
        self.call.side_effect = call
        self.enqueue(); self.box.process_one()
        self.assertEqual(self.box.status()['pending'], 1)

    def test_storage_error_does_not_escape_into_caster_and_is_counted(self):
        self.ns['_get_outbox'] = lambda app: self.box
        with closing(sqlite3.connect(self.box.path)) as locked:
            locked.execute('BEGIN EXCLUSIVE')
            self.ns['send'](self.app, 'offline', event_key='down')
        self.assertEqual(self.box.status()['write_failures'], 1)
        self.assertEqual(self.box.status()['pending'], 0)

    def test_status_does_not_send_or_disclose_messages_and_credentials(self):
        self.enqueue(text='private field name')
        status = json.dumps(self.box.status())
        self.call.assert_not_called()
        for secret in ('private field name', self.settings['token'], self.settings['chat_id']):
            self.assertNotIn(secret, status)
        raw = Path(self.box.path).read_bytes()
        self.assertNotIn(self.settings['token'].encode(), raw)
        self.assertNotIn(self.settings['chat_id'].encode(), raw)

    def test_only_one_worker_starts_for_repeated_requests(self):
        fake_thread = Mock()
        fake_thread.return_value.is_alive.return_value = True
        with patch.object(self.ns['threading'], 'Thread', fake_thread):
            for _ in range(10): self.ns['start_outbox'](self.app)
        self.assertEqual(fake_thread.call_count, 1)

    def test_worker_start_failure_can_be_retried(self):
        fake_thread = Mock()
        fake_thread.return_value.is_alive.return_value = False
        fake_thread.return_value.start.side_effect = RuntimeError('no thread')
        with patch.object(self.ns['threading'], 'Thread', fake_thread):
            self.ns['send'](self.app, 'offline'); self.ns['send'](self.app, 'offline')
        self.assertEqual(fake_thread.call_count, 2)
        self.assertEqual(self.box.write_failures, 0)
        self.assertEqual(self.box.status()['pending'], 2)
        self.assertTrue(self.box.worker_error)

    def test_notification_endpoints_require_admin(self):
        denied = ({'error': 'Forbidden'}, 403)
        for name in ('api_notify_status', 'api_notify_test'):
            self.assertEqual(load_function(name, {'_require_admin_role': lambda: denied})(), denied)

class TelegramResponseTests(unittest.TestCase):
    def setUp(self):
        self.ns = {'__name__': 'notify_response_test'}
        exec(compile(NOTIFY, '<notify>', 'exec'), self.ns)

    def test_http_error_preserves_status_with_non_json_body(self):
        error = urllib.error.HTTPError('https://example.test', 429, 'limited', {}, io.BytesIO(b'<html>error</html>'))
        with patch('urllib.request.urlopen', side_effect=error):
            self.assertEqual(self.ns['_call']('test', 'sendMessage', {})['error_code'], 429)

    def test_invalid_response_shape_is_failure(self):
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        for value in ([], None, {'ok': 'true'}):
            response.read.return_value = json.dumps(value).encode()
            with patch('urllib.request.urlopen', return_value=response):
                self.assertFalse(self.ns['_call']('test', 'sendMessage', {})['ok'])
