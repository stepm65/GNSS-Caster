import ast
from contextlib import nullcontext
from pathlib import Path
import sys
import tempfile
import time
import unittest
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch
from test_security_regressions import SOURCE, load_function

NOTIFY = SOURCE.split("cat > $APP/notify.py << 'EOF'\n", 1)[1].split('\nEOF', 1)[0]


class TelegramLanguageTests(unittest.TestCase):
    def setUp(self):
        self.ns = {'__name__': 'notify_test'}
        exec(compile(NOTIFY, 'notify.py', 'exec'), self.ns)

    def test_settings_default_and_supported_languages(self):
        query = Mock()
        models = NS(SystemSetting=NS(query=query, key=Mock()), db=NS(session=Mock()))
        app = NS(app_context=nullcontext)
        for stored, expected in [(None, 'en'), ('ru', 'ru'), ('en', 'en'), ('invalid', 'en')]:
            query.filter.return_value.all.return_value = [] if stored is None else [NS(key='telegram_language', value=stored)]
            with patch.dict(sys.modules, {'app.db.models': models}):
                self.assertEqual(self.ns['load_settings'](app)['language'], expected)
        self.assertIn('telegram_language', self.ns['SETTING_KEYS'])

    def test_help_and_confirmation_keep_command_identifiers(self):
        handle = self.ns['_handle_command']
        english = handle(None, {'language': 'en'}, '/help')
        russian = handle(None, {'language': 'ru'}, '/help')
        self.assertIn('Tap a button', english)
        self.assertIn('Нажмите кнопку', russian)
        self.assertIn('/restart', russian)
        for command in ('restart', 'reboot'):
            message, keyboard = handle(None, {'language': 'ru'}, '/' + command)
            self.assertNotIn('Rovers will lose', message)
            buttons = keyboard['inline_keyboard'][0]
            self.assertEqual(buttons[0]['callback_data'], command + '_confirm')
            self.assertEqual(buttons[1], {'text': 'Отмена', 'callback_data': 'help'})

    def test_keyboard_translation_does_not_mutate_shared_english_keyboard(self):
        original = self.ns['MAIN_KEYBOARD']
        russian = self.ns['localize_keyboard'](original, 'ru')
        self.assertEqual(original['inline_keyboard'][0][0]['text'], '✅ Ready?')
        self.assertEqual(russian['inline_keyboard'][0][0]['text'], '✅ Готовность')
        self.assertEqual(russian['inline_keyboard'][0][0]['callback_data'], 'ready')

    def test_event_notifications_preserve_names_and_fall_back(self):
        tr = self.ns['translate_bot']
        name = 'Base <b>1</b> {name}'
        english = f'🔴 Base "{name}" went offline. Trying to reconnect...'
        self.assertEqual(tr(english, 'en'), english)
        self.assertIn(name, tr(english, 'ru'))
        self.assertIn('отключилась', tr(english, 'ru'))
        self.assertEqual(tr('Unknown driver diagnostic', 'ru'), 'Unknown driver diagnostic')
        self.assertIn('не отвечает', tr(f'⚠️ Base "{name}": The receiver is not responding. Check it is powered on and in range.', 'ru'))

    def test_worker_reads_latest_language_and_test_message_uses_it(self):
        settings = dict(enabled=True, token='test-only', chat_id='42', language='ru', events={})
        post = Mock(return_value=(True, ''))
        call = Mock(return_value={'ok': True})
        self.ns.update(load_settings=lambda app: settings, _post_message=post, _call=call)
        with tempfile.TemporaryDirectory() as directory:
            box = self.ns['NotificationOutbox'](NS(config={'INSTANCE_DIR': directory}))
            box.enqueue('✅ GNSS Caster started (version 3.2.0).', None, None, 0)
            settings['language'] = 'en'
            box.process_one()
            self.assertIn('started', call.call_args.args[2]['text'])
            settings['language'] = 'ru'
            box.SEND_INTERVAL = 0
            with box.database() as conn: box.put_meta(conn, 'pace', 0)
            box.enqueue('✅ GNSS Caster started (version 3.2.0).', None, None, 0)
            box.process_one()
            self.assertIn('запущен', call.call_args.args[2]['text'])
        settings['language'] = 'ru'
        self.assertEqual(self.ns['send_test'](True), (True, ''))
        self.assertIn('проверочное уведомление', post.call_args.args[2])

    def test_invalid_language_rejected_before_persistence(self):
        db = NS(session=Mock())
        ns = dict(request=NS(json={'telegram_language':'invalid'}), _require_admin_role=lambda: None,
                  jsonify=lambda value: value, db=db, logger=Mock())
        function = load_function('api_update_system_settings', ns)
        response, status = function()
        self.assertEqual(status, 400)
        self.assertIn('en or ru', response['error'])
        db.session.commit.assert_not_called()

    def test_supported_language_persists_without_restart_or_other_setting_changes(self):
        for value, expected in [('ru', 'ru'), ('en', 'en'), (' RU ', 'ru')]:
            with self.subTest(value=value):
                setting = NS(value='en')
                model = Mock()
                model.query.filter_by.return_value.first.return_value = setting
                db = NS(session=Mock())
                thread = Mock()
                function = load_function('api_update_system_settings', dict(
                    request=NS(json={'telegram_language': value}),
                    _require_admin_role=lambda: None, jsonify=lambda result: result,
                    db=db, SystemSetting=model, time=time, logger=Mock(),
                    _get_system_setting_value=lambda key, default: default,
                    threading=NS(Thread=thread),
                ))
                response, status = function()
                self.assertEqual(status, 200)
                self.assertEqual(setting.value, expected)
                self.assertEqual(response['warnings'], [])
                self.assertEqual(response['applied'], {})
                model.query.filter_by.assert_called_once_with(key='telegram_language')
                db.session.commit.assert_called_once()
                thread.assert_not_called()

    def test_settings_language_is_admin_only(self):
        denied = ({'error':'Forbidden'},403)
        function = load_function('api_update_system_settings', {'_require_admin_role':lambda:denied})
        self.assertEqual(function(), denied)

    def test_defaults_cover_install_and_existing_database(self):
        self.assertEqual(SOURCE.count("('telegram_language', 'en', 'Telegram language: en or ru'),"), 2)
        self.assertIn('message="${2:-$1}"', SOURCE)
        self.assertIn('Затем: tar -xzf backup.tar.gz', SOURCE)


if __name__ == '__main__':
    unittest.main()
