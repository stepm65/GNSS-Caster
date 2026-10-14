import ast
import threading
import time
import unittest
from unittest.mock import Mock, patch
from types import SimpleNamespace as NS
from test_security_regressions import SOURCE

class NotificationTests(unittest.TestCase):
    def setUp(self):
        source=SOURCE.split("cat > $APP/notify.py << 'EOF'\n",1)[1].split('\nEOF\n',1)[0]
        node=next(n for n in ast.walk(ast.parse(source)) if isinstance(n,ast.FunctionDef) and n.name=='send')
        self.thread=Mock()
        ns={'time':time,'threading':NS(Thread=self.thread),'_last_sent':{},
            '_last_sent_lock':threading.Lock(),'DEFAULT_COOLDOWN_SECONDS':60}
        exec(compile(ast.Module(body=[node],type_ignores=[]),'<notify>','exec'),ns)
        self.send=ns['send']

    def test_first_alert_works_soon_after_boot(self):
        with patch.object(time,'monotonic',return_value=1):
            self.send(True,'offline',event_key='base-1',cooldown=900)
        self.assertEqual(self.thread.call_count,1)

    def test_wall_clock_jump_does_not_resend_and_cooldown_expires(self):
        with patch.object(time,'monotonic',return_value=100):
            self.send(True,'offline',event_key='base-1',cooldown=900)
        with patch.object(time,'monotonic',return_value=101), patch.object(time,'time',return_value=9999999999):
            self.send(True,'retry error',event_key='base-1',cooldown=900)
        self.assertEqual(self.thread.call_count,1)
        with patch.object(time,'monotonic',return_value=1000):
            self.send(True,'still offline',event_key='base-1',cooldown=900)
        self.assertEqual(self.thread.call_count,2)

    def test_recovery_notice_uses_independent_key(self):
        with patch.object(time,'monotonic',return_value=100):
            self.send(True,'offline',event_key='base-1',cooldown=900)
            self.send(True,'online',event_key='base-1-up',cooldown=300)
        self.assertEqual(self.thread.call_count,2)
