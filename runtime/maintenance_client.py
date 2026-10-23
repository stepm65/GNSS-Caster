"""Unprivileged maintenance transport; never retries a possibly executed action."""
import json
import math
import socket
import stat
import os
import struct
import subprocess
import time

SOCKET = '/run/gnss-caster-maintenance/control.sock'
MAX_REPLY = 1024 * 1024


def run(args, timeout=30):
    timeout = float(timeout)
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError('Invalid maintenance timeout')
    payload = json.dumps({'version': 1, 'args': [str(arg) for arg in args]}).encode()
    if len(payload) > 8192:
        raise ValueError('Maintenance request too large')
    try:
        info = os.lstat(SOCKET)
        if not stat.S_ISSOCK(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o007:
            raise RuntimeError('Unsafe maintenance socket')
        deadline = time.monotonic() + min(timeout, 1810)
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
            conn.settimeout(min(timeout, 1810))
            conn.connect(SOCKET)
            _, uid, _ = struct.unpack('3i', conn.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
            if uid != 0:
                raise RuntimeError('Untrusted maintenance service')
            conn.sendall(payload)
            conn.shutdown(socket.SHUT_WR)
            data = bytearray()
            while True:
                left = deadline - time.monotonic()
                if left <= 0:
                    raise TimeoutError()
                conn.settimeout(left)
                part = conn.recv(min(65536, MAX_REPLY + 1 - len(data)))
                if not part:
                    break
                data.extend(part)
                if len(data) > MAX_REPLY:
                    raise RuntimeError('Maintenance response too large')
        result = json.loads(data)
        if not isinstance(result, dict) or result.get('version') != 1 or type(result.get('returncode')) is not int or not all(isinstance(result.get(key), str) for key in ('stdout','stderr','request_id')):
            raise ValueError('Invalid maintenance response')
        return subprocess.CompletedProcess(args, result['returncode'], result['stdout'], result['stderr'])
    except (OSError, ValueError) as exc:
        raise RuntimeError('Maintenance connection failed; check operation status before retrying') from exc
