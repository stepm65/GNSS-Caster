import ast
import os
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch
from test_security_regressions import SOURCE, load_function

MODELS = ast.parse(SOURCE.split("cat > $APP/db/models.py << 'EOF'\n", 1)[1].split('\nEOF', 1)[0])
def model_function(name, ns):
    node = next(n for n in ast.walk(MODELS) if isinstance(n, ast.FunctionDef) and n.name == name)
    exec(compile(ast.Module(body=[node], type_ignores=[]), '<models>', 'exec'), ns)
    return ns[name]

class PrivateFileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'password'
        self.path.write_text('old')
        self.write = model_function('write_private_text', {'os': os, 'tempfile': tempfile})

    def test_replace_existing_complete_file(self):
        self.write(str(self.path), 'new-password')
        self.assertEqual(self.path.read_text(), 'new-password')
        self.assertEqual(list(self.path.parent.glob('.gnss-secret-*')), [])

    def test_failed_replace_preserves_original_and_cleans_temporary(self):
        with patch.object(os, 'replace', side_effect=OSError('injected')):
            with self.assertRaises(OSError): self.write(str(self.path), 'new')
        self.assertEqual(self.path.read_text(), 'old')
        self.assertEqual(list(self.path.parent.glob('.gnss-secret-*')), [])

    def test_failed_flush_preserves_original_and_cleans_temporary(self):
        with patch.object(os, 'fsync', side_effect=OSError('injected')):
            with self.assertRaises(OSError): self.write(str(self.path), 'new')
        self.assertEqual(self.path.read_text(), 'old')
        self.assertEqual(list(self.path.parent.glob('.gnss-secret-*')), [])

class PasswordTests(unittest.TestCase):
    def setUp(self):
        self.user = NS(id=1, username='alice', password='old', session_version=5,
                       totp_pending_secret='pending', totp_pending_expires=999)
        self.user.set_password_hash = self.change_hash
        self.login = Mock()
        self.session = Mock()
        self.ns = {'request': NS(json={}), 'current_user': self.user,
                   'Admin': NS(query=NS(get=lambda ident:self.user, get_or_404=lambda ident:self.user)),
                   'bcrypt': NS(generate_password_hash=lambda p:p.encode(), check_password_hash=lambda p,v:p==v),
                   'db': NS(session=self.session), 'login_user':self.login, 'time':time,
                   'jsonify':lambda value:value, 'logger':Mock(), 'LogEntry':lambda **kw:kw,
                   '_require_admin_role':lambda:None, '_get_client_ip':lambda:'local',
                   '_validate_password_strength':lambda *args,**kw:None,
                   'ADMIN_PASSWORD_MIN_LENGTH':12, 'config':{},
                   '_remove_bootstrap_admin_password_file':Mock()}

    def change_hash(self, value):
        self.user.password = value
        self.user.session_version += 1

    def test_change_password_refreshes_only_current_login(self):
        self.ns['request'].json = {'current_password':'old','new_password':'new','confirm_password':'new'}
        result = load_function('api_change_password', self.ns)()
        self.assertEqual(result[1], 200)
        self.assertEqual(self.user.session_version, 6)
        self.login.assert_called_once_with(self.user, fresh=True)
        self.session.commit.assert_called_once()

    def test_wrong_current_password_does_not_revoke(self):
        self.ns['request'].json = {'current_password':'wrong','new_password':'new','confirm_password':'new'}
        self.assertEqual(load_function('api_change_password', self.ns)()[1], 400)
        self.assertEqual(self.user.session_version, 5)
        self.login.assert_not_called()
        self.session.commit.assert_not_called()

    def test_reset_other_admin_does_not_login_as_target(self):
        self.ns['current_user'] = NS(id=2, username='operator')
        self.ns['request'].json = {'password':'new','confirm_password':'new'}
        self.assertEqual(load_function('api_reset_admin_password', self.ns)(1)[1], 200)
        self.assertEqual(self.user.session_version, 6)
        self.login.assert_not_called()

    def test_self_reset_refreshes_current_session(self):
        self.ns['request'].json = {'password':'new','confirm_password':'new'}
        self.assertEqual(load_function('api_reset_admin_password', self.ns)(1)[1], 200)
        self.login.assert_called_once_with(self.user, fresh=True)

    def test_edit_password_revokes_and_refreshes(self):
        self.ns['request'].json = {'password':'new'}
        self.assertEqual(load_function('api_update_admin', self.ns)(1)[1], 200)
        self.assertEqual(self.user.session_version, 6)
        self.login.assert_called_once()

    def test_edit_email_does_not_revoke_or_refresh(self):
        self.ns['request'].json = {'email':'a@example.com'}
        self.assertEqual(load_function('api_update_admin', self.ns)(1)[1], 200)
        self.assertEqual(self.user.session_version, 5)
        self.login.assert_not_called()

    def test_failed_commit_does_not_refresh_login(self):
        self.ns['request'].json = {'password':'new','confirm_password':'new'}
        self.session.commit.side_effect = RuntimeError('injected')
        self.assertEqual(load_function('api_reset_admin_password', self.ns)(1)[1], 500)
        self.login.assert_not_called()
        self.session.rollback.assert_called_once()

    def test_model_uses_database_increment_and_clears_pending_setup(self):
        column = Mock()
        class Version:
            def __add__(self, value): return ('session_version +', value)
        fn = model_function('set_password_hash', {'Admin': NS(session_version=Version())})
        fn(self.user, 'hashed')
        self.assertEqual(self.user.session_version, ('session_version +', 1))
        self.assertEqual(self.user.password, 'hashed')
        self.assertEqual(self.user.totp_pending_secret, '')
        self.assertEqual(self.user.totp_pending_expires, 0)

if __name__ == '__main__': unittest.main()
