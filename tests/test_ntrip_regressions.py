"""NTRIP regression tests using embedded classes, sockets, threads and SQLite.

No installer, Linux service or physical receiver is started. Flask and ORM
imports are replaced; counter SQL executes against a real SQLite database.
"""
import ast
import base64
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import logging
from pathlib import Path
from queue import Queue, Empty, Full
import socket
import sqlite3
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import uuid


SOURCE = (Path(__file__).resolve().parents[1] / 'gnss-caster-install.sh').read_text(encoding='utf-8')


def embedded_class(module, name, namespace):
    body = SOURCE.split(f"cat > $APP/{module} << 'EOF'\n", 1)[1].split('\nEOF\n', 1)[0]
    node = next(n for n in ast.parse(body).body if isinstance(n, ast.ClassDef) and n.name == name)
    exec(compile(ast.Module(body=[node], type_ignores=[]), module, 'exec'), namespace)
    return namespace[name]


def server_type(namespace=None):
    ns = dict(socket=socket, threading=threading, time=time, uuid=uuid,
              logger=logging.getLogger('test.ntrip'), text=lambda value: value)
    ns.update(namespace or {})
    return embedded_class('ntrip/core.py', 'NTRIPServer', ns), ns


def manager():
    ns = dict(socket=socket, Lock=threading.Lock, Thread=threading.Thread,
              Event=threading.Event, Queue=Queue, Empty=Empty, Full=Full,
              defaultdict=defaultdict, time=time, logger=logging.getLogger('test.rtcm'))
    result = embedded_class('rtcm/stream.py', 'RTCMStreamManager', ns)()
    result.is_message_allowed = lambda *args: True
    result.parse_message_type = lambda data: 1005
    return result


class HeaderTests(unittest.TestCase):
    def setUp(self):
        cls, _ = server_type()
        self.server = cls()
        self.reader, self.writer = socket.socketpair()
        self.addCleanup(self.reader.close)
        self.addCleanup(self.writer.close)
        self.reader.settimeout(1)

    def test_fragmented_header_and_first_gga_are_preserved(self):
        result = []
        thread = threading.Thread(target=lambda: result.append(self.server._read_request_headers(self.reader)))
        thread.start()
        self.writer.sendall(b'GET /BASE HTTP/1.0\r\nAuth')
        self.writer.sendall(b'orization: Basic dTpw\r\n\r')
        self.writer.sendall(b'\n$GPGGA,test\r\n')
        thread.join(2)
        self.assertFalse(thread.is_alive())
        self.assertEqual(result[0][0], b'GET /BASE HTTP/1.0\r\nAuthorization: Basic dTpw')
        tail = result[0][1]
        if len(tail) < len(b'$GPGGA,test\r\n'):
            tail += self.reader.recv(100)
        self.assertEqual(tail, b'$GPGGA,test\r\n')
        self.assertEqual(self.reader.gettimeout(), 1)

    def test_header_larger_than_old_1024_limit_is_accepted(self):
        request = b'GET /BASE HTTP/1.0\r\nUser-Agent: ' + b'x' * 2000 + b'\r\n\r\n'
        self.writer.sendall(request)
        self.assertEqual(self.server._read_request_headers(self.reader)[0], request[:-4])

    def test_oversized_incomplete_header_is_rejected(self):
        self.server.header_max_bytes = 64
        self.writer.sendall(b'x' * 64)
        with self.assertRaises(ValueError):
            self.server._read_request_headers(self.reader)
        self.assertEqual(self.reader.gettimeout(), 1)

    def test_complete_header_at_limit_is_accepted(self):
        header = b'GET / HTTP/1.0\r\n\r\n'
        self.server.header_max_bytes = len(header)
        self.writer.sendall(header)
        self.assertEqual(self.server._read_request_headers(self.reader), (header[:-4], b''))

    def test_eof_before_header_terminator(self):
        self.writer.sendall(b'GET / HTTP/1.0\r\n')
        self.writer.shutdown(socket.SHUT_WR)
        with self.assertRaises(EOFError):
            self.server._read_request_headers(self.reader)

    def test_deadline_is_total_not_per_packet(self):
        clock = SimpleNamespace(monotonic=lambda: fake.now)

        class DripSocket:
            now = 0
            def gettimeout(self):
                return 30
            def settimeout(self, value):
                self.timeout = value
            def recv(self, size):
                self.now += 0.6
                return b'x'

        fake = DripSocket()
        cls, ns = server_type({'time': clock})
        server = cls()
        server.header_timeout = 1
        with self.assertRaises(socket.timeout):
            server._read_request_headers(fake)
        self.assertEqual(fake.now, 1.2)
        self.assertEqual(fake.timeout, 30)


class RegistryTests(unittest.TestCase):
    def setUp(self):
        cls, self.ns = server_type()
        self.server = cls()
        self.server.running = True

    def test_immediate_handler_sees_registration_and_leaves_no_ghost(self):
        done = threading.Event()
        observed = []
        left, right = socket.socketpair()
        self.addCleanup(left.close)
        self.addCleanup(right.close)

        def handle(sock, address, cid):
            observed.append(self.server.connections[cid]['socket'] is sock)
            self.server._forget_connection(cid)
            sock.close()
            done.set()

        self.server._handle_client = handle
        self.assertTrue(self.server._start_client(left, ('127.0.0.1', 1), 1))
        self.assertTrue(done.wait(2))
        self.assertEqual(observed, [True])
        self.assertEqual(self.server.connections, {})
        self.assertEqual(self.server.stats['current_connections'], 0)

    def test_global_slot_is_reserved_before_second_client(self):
        finish = threading.Event()
        done = threading.Event()
        sockets = [socket.socketpair() for _ in range(2)]
        for pair in sockets:
            for sock in pair:
                self.addCleanup(sock.close)

        def handle(sock, address, cid):
            finish.wait(2)
            self.server._forget_connection(cid)
            done.set()

        self.server._handle_client = handle
        try:
            self.assertTrue(self.server._start_client(sockets[0][0], ('local', 1), 1))
            self.assertFalse(self.server._start_client(sockets[1][0], ('local', 2), 1))
            self.assertEqual(len(self.server.connections), 1)
        finally:
            finish.set()
            self.assertTrue(done.wait(2))

    def test_thread_start_failure_releases_registration_and_socket(self):
        class BrokenThread:
            def __init__(self, **kwargs):
                pass
            def start(self):
                raise RuntimeError('cannot allocate thread')

        self.ns['threading'] = SimpleNamespace(Thread=BrokenThread)
        left, right = socket.socketpair()
        self.addCleanup(left.close)
        self.addCleanup(right.close)
        with self.assertRaises(RuntimeError):
            self.server._start_client(left, ('local', 1), 1)
        self.assertEqual(self.server.connections, {})
        self.assertEqual(left.fileno(), -1)

    def test_restart_waits_for_old_handlers(self):
        self.server.running = False
        self.server.app = object()
        self.server.connections['old'] = {}
        with self.assertRaisesRegex(RuntimeError, 'still shutting down'):
            self.server.start()

    def test_previous_listener_cannot_register_after_restart(self):
        left, right = socket.socketpair()
        self.addCleanup(left.close)
        self.addCleanup(right.close)
        old_event = threading.Event()
        self.assertFalse(self.server._start_client(left, ('local', 1), 1, old_event))
        self.assertEqual(self.server.connections, {})

    def test_stop_wakes_blocked_reader_and_drains_registration(self):
        left, right = socket.socketpair()
        self.addCleanup(left.close)
        self.addCleanup(right.close)
        entered = threading.Event()
        self.ns['stream_manager'] = SimpleNamespace(unregister_client_socket=lambda sock: None)

        def handle(sock, address, cid):
            entered.set()
            try:
                sock.recv(1)
            except OSError:
                pass
            finally:
                self.server._forget_connection(cid)

        self.server._handle_client = handle
        self.server._start_client(left, ('local', 1), 1)
        self.assertTrue(entered.wait(2))
        self.server.stop()
        self.assertEqual(self.server.connections, {})
        self.assertEqual(self.server.stats['current_connections'], 0)


class SQLiteSession:
    def __init__(self, path):
        self.path = path
        self.local = threading.local()

    def connection(self):
        if not hasattr(self.local, 'conn'):
            self.local.conn = sqlite3.connect(self.path, timeout=10)
        return self.local.conn

    def execute(self, sql, values=None):
        return self.connection().execute(sql, values or {})

    def commit(self):
        self.connection().commit()

    def rollback(self):
        self.connection().rollback()

    def remove(self):
        if hasattr(self.local, 'conn'):
            self.local.conn.close()
            del self.local.conn


class RoverSlotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.session = SQLiteSession(str(Path(self.temp.name) / 'db.sqlite'))
        self.addCleanup(self.session.remove)
        self.session.execute('PRAGMA journal_mode=WAL')
        self.session.execute('''CREATE TABLE rover (
            id INTEGER PRIMARY KEY, password TEXT, is_active INTEGER, expires INTEGER,
            active_conn INTEGER, max_conn INTEGER, total_connections INTEGER, last_connection INTEGER
        )''')
        self.session.execute("INSERT INTO rover VALUES (1, 'hash', 1, 0, 0, 1, 0, 0)")
        self.session.commit()
        cls, self.ns = server_type({'db': SimpleNamespace(session=self.session)})
        self.server = cls()

    def test_simultaneous_reservations_respect_single_slot(self):
        barrier = threading.Barrier(8)
        def reserve(_):
            try:
                barrier.wait(timeout=5)
                return self.server._reserve_rover_slot(1, 'hash')
            finally:
                self.session.remove()
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(reserve, range(8)))
        self.assertEqual(sum(results), 1)
        self.assertEqual(self.session.execute('SELECT active_conn, total_connections FROM rover').fetchone(), (1, 1))

    def test_simultaneous_releases_do_not_lose_decrements(self):
        self.session.execute('UPDATE rover SET active_conn=8')
        self.session.commit()
        def release(_):
            try:
                self.server._release_rover_slot(1)
            finally:
                self.session.remove()
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(release, range(8)))
        self.server._release_rover_slot(1)
        self.assertEqual(self.session.execute('SELECT active_conn FROM rover').fetchone()[0], 0)

    def test_expired_disabled_or_changed_password_cannot_reserve(self):
        for assignment in ["expires=1", 'is_active=0', "password='new'"]:
            with self.subTest(assignment=assignment):
                self.session.execute("UPDATE rover SET expires=0, is_active=1, password='hash'")
                self.session.execute('UPDATE rover SET ' + assignment)
                self.session.commit()
                self.assertFalse(self.server._reserve_rover_slot(1, 'hash'))
                self.assertEqual(self.session.execute('SELECT active_conn FROM rover').fetchone()[0], 0)


class HandlerTests(unittest.TestCase):
    setUp = RoverSlotTests.setUp

    def prepare_handler(self):
        self.session.execute("UPDATE rover SET password='$2test'")
        self.session.commit()
        self.session.add = lambda value: None
        rover = SimpleNamespace(id=1, username='user', password='$2test', is_active=True,
                                expires=0, mountpoints='', max_conn=1)
        mountpoint = SimpleNamespace(id=1, base_id=1, name='BASE', is_active=True)
        def query(record):
            return SimpleNamespace(filter_by=lambda **kwargs: SimpleNamespace(first=lambda: record))
        self.manager = manager()
        self.ns.update({
            'Rover': SimpleNamespace(query=query(rover)),
            'MountPoint': SimpleNamespace(query=query(mountpoint)),
            'notify': SimpleNamespace(send=lambda *args, **kwargs: None),
            'stream_manager': self.manager,
            'LogEntry': lambda **kwargs: kwargs,
            'base64': base64,
        })
        @contextmanager
        def app_context():
            try:
                yield
            finally:
                self.session.remove()
        self.server.app = SimpleNamespace(app_context=app_context)
        self.server.running = True
        self.server._verify_rover_password = lambda *args: True
        client, peer = socket.socketpair()
        client.settimeout(1)
        peer.settimeout(2)
        self.addCleanup(client.close)
        self.addCleanup(peer.close)
        return client, peer

    def launch(self, client):
        self.server._start_client(client, ('127.0.0.1', 1234), 10)
        with self.server.connection_lock:
            thread = next(iter(self.server.connections.values()))['thread']
        return thread

    def test_first_gga_survives_header_read_and_disconnect_releases_slot(self):
        client, peer = self.prepare_handler()
        forwarded = []
        got_gga = threading.Event()
        def forward(station_id, sentence):
            forwarded.append((station_id, sentence))
            got_gga.set()
        module = SimpleNamespace(bluetooth_manager=SimpleNamespace(forward_gga_to_station=forward))
        with patch.dict('sys.modules', {'app.bluetooth.core': module}):
            thread = self.launch(client)
            try:
                peer.sendall(b'GET /BASE HTTP/1.0\r\nAuthorization: Basic dXNlcjpwYXNz\r\n\r\n$GPGGA,test\r\n')
                self.assertTrue(peer.recv(100).startswith(b'ICY 200 OK'))
                self.assertTrue(got_gga.wait(2))
                self.assertEqual(forwarded, [(1, '$GPGGA,test')])
            finally:
                peer.close()
                thread.join(3)
        self.assertFalse(thread.is_alive())
        self.assertEqual(self.server.connections, {})
        self.assertEqual(self.session.execute('SELECT active_conn FROM rover').fetchone()[0], 0)

    def test_send_failure_after_reservation_releases_slot(self):
        client, peer = self.prepare_handler()
        class FailSending:
            def __getattr__(self, name):
                return getattr(client, name)
            def sendall(self, data):
                raise OSError('injected send failure')
        thread = self.launch(FailSending())
        peer.sendall(b'GET /BASE HTTP/1.0\r\nAuthorization: Basic dXNlcjpwYXNz\r\n\r\n')
        thread.join(3)
        self.assertFalse(thread.is_alive())
        self.assertEqual(self.server.connections, {})
        self.assertEqual(self.session.execute('SELECT active_conn, total_connections FROM rover').fetchone(), (0, 1))

    def test_rejected_client_does_not_release_another_clients_slot(self):
        client, peer = self.prepare_handler()
        self.session.execute('UPDATE rover SET active_conn=1')
        self.session.commit()
        thread = self.launch(client)
        peer.sendall(b'GET /BASE HTTP/1.0\r\nAuthorization: Basic dXNlcjpwYXNz\r\n\r\n')
        thread.join(3)
        self.assertFalse(thread.is_alive())
        self.assertEqual(self.server.connections, {})
        self.assertEqual(self.session.execute('SELECT active_conn FROM rover').fetchone()[0], 1)


class HeldSocket:
    """Hold sendall until released or shut down, without filling OS buffers."""
    def __init__(self):
        self.entered = threading.Event()
        self.release = threading.Event()
        self.closed = threading.Event()
        self.sent = []

    def fileno(self):
        return 123

    def sendall(self, data):
        self.entered.set()
        if not self.release.wait(3):
            raise socket.timeout()
        if self.closed.is_set():
            raise OSError('closed')
        self.sent.append(data)

    def shutdown(self, how):
        self.closed.set()
        self.release.set()

    def close(self):
        self.shutdown(socket.SHUT_RDWR)


class SenderTests(unittest.TestCase):
    def setUp(self):
        self.manager = manager()
        self.senders = []
        self.addCleanup(self.cleanup_senders)

    def register(self, sock):
        self.manager.register_client(1, 1, sock)
        self.senders.append((sock, self.manager.client_senders[sock]['thread']))

    def cleanup_senders(self):
        for sock, thread in self.senders:
            self.manager.unregister_client(1, 1, sock)
            thread.join(2)
            self.assertFalse(thread.is_alive())

    def test_slow_client_does_not_delay_healthy_socket(self):
        slow = HeldSocket()
        self.register(slow)
        self.manager.broadcast(1, b'first')
        self.assertTrue(slow.entered.wait(2))
        healthy, peer = socket.socketpair()
        peer.settimeout(1)
        self.addCleanup(peer.close)
        self.register(healthy)
        self.manager.broadcast(1, b'next')
        self.assertEqual(peer.recv(4), b'next')
        self.assertFalse(slow.release.is_set())

    def test_queue_overflow_disconnects_and_cleans_up(self):
        self.manager.client_queue_frames = 2
        slow = HeldSocket()
        self.register(slow)
        self.manager.broadcast(1, b'first')
        self.assertTrue(slow.entered.wait(2))
        self.manager.broadcast(1, b'second')
        self.manager.broadcast(1, b'third')
        self.manager.broadcast(1, b'overflow')
        self.assertTrue(slow.closed.wait(2))
        self.assertEqual(self.manager.get_client_count(1), 0)
        self.assertNotIn(slow, self.manager.client_senders)
        self.assertEqual(self.manager.get_stats(1)['bytes_sent'], 0)

    def test_stale_queued_frames_are_not_sent(self):
        slow = HeldSocket()
        self.register(slow)
        self.manager.broadcast(1, b'first')
        self.assertTrue(slow.entered.wait(2))
        sender = self.manager.client_senders[slow]
        sender['queue'].put_nowait((time.monotonic() - 10, b'stale', 1005))
        slow.release.set()
        self.assertTrue(slow.closed.wait(2))
        self.assertEqual(slow.sent, [b'first'])

    def test_send_counters_count_completion_and_drain_once(self):
        slow = HeldSocket()
        self.register(slow)
        self.manager.broadcast(1, b'frame')
        self.assertTrue(slow.entered.wait(2))
        self.assertEqual(self.manager.get_stats(1)['bytes_sent'], 0)
        slow.release.set()
        # A stale following frame makes the writer finish after updating stats.
        self.manager.client_senders[slow]['queue'].put_nowait((0, b'expired', 1005))
        self.assertTrue(slow.closed.wait(2))
        self.assertEqual(self.manager.get_stats(1)['bytes_sent'], 5)
        self.assertEqual(self.manager.take_sent_bytes(1), 5)
        self.assertEqual(self.manager.take_sent_bytes(1), 0)

    def test_frames_keep_order_on_real_socket(self):
        outbound, peer = socket.socketpair()
        peer.settimeout(1)
        self.addCleanup(peer.close)
        self.register(outbound)
        for frame in [b'aaa', b'bbb', b'ccc']:
            self.manager.broadcast(1, frame)
        result = b''
        while len(result) < 9:
            result += peer.recv(9 - len(result))
        self.assertEqual(result, b'aaabbbccc')

    def test_unregister_wakes_held_writer_and_is_idempotent(self):
        slow = HeldSocket()
        self.register(slow)
        self.manager.broadcast(1, b'frame')
        self.assertTrue(slow.entered.wait(2))
        self.manager.unregister_client_socket(slow)
        self.manager.unregister_client_socket(slow)
        self.assertTrue(slow.closed.wait(2))
        self.assertEqual(self.manager.get_client_count(1), 0)

    def test_last_rover_disconnect_preserves_receiver_frames_and_next_rover(self):
        payload = bytes([0xD3, 0, 2, 0x3E, 0xD0])
        frame = payload + self.manager.compute_crc24q(payload).to_bytes(3, 'big')

        def rover():
            outbound, peer = socket.socketpair()
            peer.settimeout(2)
            self.addCleanup(peer.close)
            self.register(outbound)
            return outbound, peer

        def receive(peer):
            result = b''
            while len(result) < len(frame):
                chunk = peer.recv(len(frame) - len(result))
                self.assertTrue(chunk)
                result += chunk
            return result

        first, peer = rover()
        self.manager.broadcast_stream(1, frame)
        self.assertEqual(receive(peer), frame)
        self.manager.broadcast_stream(1, frame[:4])
        self.manager.unregister_client_socket(first)
        self.assertEqual(self.manager.get_client_count(1), 0)
        self.manager.broadcast_stream(1, frame[4:])
        self.assertEqual(self.manager.get_stats(1)['frames_parsed'], 2)

        _, next_peer = rover()
        self.manager.broadcast_stream(1, frame)
        self.assertEqual(receive(next_peer), frame)
        stats = self.manager.get_stats(1)
        self.assertEqual(stats['frames_parsed'], 3)
        self.assertEqual(stats['crc_failures'], 0)


if __name__ == '__main__':
    unittest.main()
