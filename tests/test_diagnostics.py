import sys
import threading
import time
import unittest
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch
from test_security_regressions import load_function
from test_ntrip_regressions import manager

class DiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.describe=load_function('_receiver_health',{})
        self.station=NS(id=1,name='Base')

    def test_disconnected_receiver_is_not_a_fresh_stream(self):
        row=self.describe(self.station,{}, {'last_frame_at':99},100)
        self.assertEqual(row['receiver'],'disconnected')
        self.assertEqual(row['rtcm'],'unavailable')

    def test_connected_without_valid_frames_is_waiting(self):
        row=self.describe(self.station,{'connected':True},{},100)
        self.assertEqual(row['rtcm'],'waiting')
        self.assertIsNone(row['last_frame_age_seconds'])

    def test_recent_valid_frame_is_healthy_without_rovers(self):
        row=self.describe(self.station,{'connected':True},{'last_frame_at':80,'clients':0},100)
        self.assertEqual(row['rtcm'],'ok')
        self.assertEqual(row['last_frame_age_seconds'],20)

    def test_old_frame_stays_stale_even_if_other_activity_is_recent(self):
        row=self.describe(self.station,{'connected':True},{'last_frame_at':60,'last_activity':99,'frames_parsed':900},100)
        self.assertEqual(row['rtcm'],'stale')

    def test_public_health_returns_503_for_database_failure(self):
        session=Mock()
        session.execute.side_effect=RuntimeError('private SQL details')
        ns={'db':NS(session=session),'text':lambda sql:sql,'time':time,'__version__':'test','jsonify':lambda x:x}
        load_function('_database_health',ns)
        payload,code=load_function('api_health',ns)()
        self.assertEqual(code,503)
        self.assertEqual(payload['components']['web']['status'],'ok')
        self.assertEqual(payload['components']['database']['status'],'error')
        self.assertNotIn('private',str(payload))

    def test_public_health_does_not_depend_on_receiver(self):
        ns={'_database_health':lambda:{'status':'ok'},'time':time,'__version__':'test','jsonify':lambda x:x}
        payload,code=load_function('api_health',ns)()
        self.assertEqual(code,200)
        self.assertEqual(payload['status'],'healthy')

    def test_valid_crc_updates_frame_clock_but_bad_crc_does_not(self):
        stream=manager()
        payload=bytes([0xD3,0,2,0x3E,0xD0])
        frame=payload+stream.compute_crc24q(payload).to_bytes(3,'big')
        with patch.object(time,'monotonic',return_value=100):
            stream.broadcast_stream(1,frame)
        self.assertEqual(stream.get_stats(1)['last_frame_at'],100)
        bad=frame[:-1]+bytes([frame[-1]^1])
        with patch.object(time,'monotonic',return_value=200):
            stream.broadcast_stream(1,bad)
        self.assertEqual(stream.get_stats(1)['last_frame_at'],100)
        self.assertEqual(stream.get_stats(1)['crc_failures'],1)

    def test_detailed_diagnostics_without_configured_stations(self):
        modules={'app.bluetooth.core':NS(bluetooth_manager=NS(lock=threading.Lock(),connections={})),
                 'app.ntrip.core':NS(ntrip_server=NS(running=True)),
                 'app.rtcm.stream':NS(stream_manager=NS(get_stats=lambda ident:{}))}
        ns={'_database_health':lambda:{'status':'ok'},'time':time,'__version__':'test','jsonify':lambda x:x,
            'BaseStation':NS(id=NS(asc=lambda:None),query=NS(order_by=lambda _:NS(all=lambda:[]))),
            '_receiver_health':self.describe}
        with patch.dict(sys.modules,modules):
            payload=load_function('api_diagnostics',ns)()
        self.assertEqual(payload['components']['receivers']['status'],'not_configured')
        self.assertEqual(payload['components']['rtcm']['status'],'not_configured')
        self.assertEqual(payload['status'],'healthy')

if __name__=='__main__': unittest.main()
