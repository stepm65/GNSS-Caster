"""Broker policy, protected audit and local IPC. No real privileged helper calls."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import socket
import stat
import struct
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch
from test_rollback_regressions import SOURCE, ROOT, find_bash, bash_function


def module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'runtime' / (name + '.py'))
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


broker = module('maintenance_broker')
client = module('maintenance_client')


class PolicyTests(unittest.TestCase):
    def test_allowlist_covers_current_callers(self):
        for args in [
            ['ping'], ['release-check'], ['release-status'], ['release-install', 'v3.4.0', 'a'*64],
            ['rfkill-unblock-bluetooth'], ['systemctl-is-active', 'bluetooth'], ['systemctl-start','bluetooth'],
            ['rfcomm-bind','1','AA:BB:CC:DD:EE:FF','30'], ['rfcomm-release','1'],
            ['read-rssi','AA:BB:CC:DD:EE:FF'], ['recover-bluetooth'], ['recover-bluetooth-deep'],
            ['recover-bluetooth-deep','AA:BB:CC:DD:EE:FF'], ['set-system-clock','2026-10-22 12:30:00'],
            ['systemd-job','backup','gnss-caster-backup-1792000000.service'],
            ['systemd-job','restore','gnss-caster-restore-1792000000-a1b2.service','backup_20261021_123000.tar.gz'],
            ['systemd-job','restore','gnss-caster-restore-1792000000-a1b2.service','backup_uploaded-test.tar.gz.enc','/run/gnss-caster/restore-'+'a'*16+'.key'],
            ['restart-service'], ['reboot-host'], ['write-logrotate','30'], ['write-backup-cron','0','86400'],
            ['certificate-info','/etc/letsencrypt/live/test.example/fullchain.pem'],
            ['certificate-info','/etc/ssl/certs/gnss-caster.crt'], ['certbot-renew','1'],
            ['power','shutdown','gnss-caster-power-shutdown-1792000000-1abc.service','5'],
        ]:
            with self.subTest(args=args):
                accepted, timeout = broker.validate_request({'version':1,'args':args})
                self.assertTrue(accepted)
                self.assertLessEqual(timeout, 1800)

    def test_unknown_commands_extra_arguments_paths_and_injection_rejected(self):
        for args in [
            [], ['bash','-c','id'], ['guarded-service-action','reboot'], ['systemd-data-restore','x','y'],
            ['ping','extra'], ['rfkill-unblock-bluetooth','wifi'], ['systemctl-start','nginx'],
            ['systemctl-is-active','../../ssh'], ['recover-bluetooth','extra'],
            ['rfcomm-bind','1','AA:BB:CC:DD:EE:FF;reboot','1'], ['rfcomm-release','31'],
            ['set-system-clock','2026-02-30 12:30:00'], ['write-logrotate','1\n/etc/passwd'],
            ['write-backup-cron','1','* * * * *'], ['certificate-info','/etc/shadow'],
            ['certificate-info','/etc/letsencrypt/live/../fullchain.pem'],
            ['systemd-job','restore','gnss-caster-restore-1.service','backup_../secret.tar.gz'],
            ['systemd-job','restore','gnss-caster-backup-1.service','backup_a.tar.gz'],
            ['systemd-job','backup','gnss-caster-maintenance.service'],
            ['power','reboot','gnss-caster.service','1'], ['certbot-renew','1','--config=/tmp/evil'],
            ['release-install','v3.4.0','a'*64,'extra'], ['ping',None], ['x'*256],
        ]:
            with self.subTest(args=args), self.assertRaises(broker.Rejected):
                broker.validate_request({'version':1,'args':args})
        for request in ([], {}, {'version':True,'args':['ping']}, {'version':1,'args':['ping'],'env':{'PATH':'evil'}}):
            with self.assertRaises(broker.Rejected): broker.validate_request(request)

    def test_web_restore_is_always_rewritten_to_data_only_action(self):
        args, _ = broker.validate_request({'version':1,'args':['systemd-job','restore','gnss-caster-restore-1.service','backup_a.tar.gz']})
        self.assertEqual(args, ['systemd-data-restore','gnss-caster-restore-1.service','backup_a.tar.gz'])

    def test_helper_trust_rejects_wrong_owner_writable_files_and_links(self):
        path = Mock()
        for owner, mode, links in ((1001, stat.S_IFREG|0o700, 1), (0, stat.S_IFREG|0o720, 1),
                                   (0, stat.S_IFLNK|0o777, 1), (0, stat.S_IFREG|0o700, 2)):
            path.lstat.return_value = Mock(st_uid=owner, st_mode=mode, st_nlink=links)
            with self.assertRaises(broker.Rejected): broker.trusted(path)
        path.lstat.return_value = Mock(st_uid=0, st_mode=stat.S_IFREG|0o700, st_nlink=1)
        broker.trusted(path)

    def test_duplicate_fields_and_oversize_requests_rejected(self):
        for raw in (b'{"version":1,"version":1,"args":["ping"]}', b'x'*8193):
            conn = Mock()
            conn.recv.side_effect = [raw, b'']
            with self.assertRaises(broker.Rejected): broker.read_request(conn)

    def test_audit_failure_blocks_execution(self):
        conn = Mock()
        conn.getsockopt.return_value = struct.pack('3i', 123, 1001, 1001)
        with patch.object(socket, 'SO_PEERCRED', 17, create=True), \
             patch.object(broker, 'read_request', return_value={'version':1,'args':['restart-service']}), \
             patch.object(broker, 'audit', side_effect=OSError('disk full')), patch.object(broker, 'execute') as execute:
            broker.handle(conn, 1001)
            execute.assert_not_called()
        self.assertEqual(json.loads(conn.sendall.call_args.args[0])['returncode'], 1)

    def test_foreign_peer_cannot_execute_or_read_request(self):
        conn = Mock()
        conn.getsockopt.return_value = struct.pack('3i', 123, 1002, 1001)
        with patch.object(socket, 'SO_PEERCRED', 17, create=True), patch.object(broker, 'audit'), \
             patch.object(broker, 'read_request') as read, patch.object(broker, 'execute') as execute:
            broker.handle(conn, 1001)
            execute.assert_not_called(); read.assert_not_called()

    def test_mutation_records_verified_peer_and_outcome(self):
        conn = Mock()
        conn.getsockopt.return_value = struct.pack('3i', 123, 1001, 1001)
        with patch.object(socket, 'SO_PEERCRED', 17, create=True), \
             patch.object(broker, 'read_request', return_value={'version':1,'args':['restart-service']}), \
             patch.object(broker, 'audit') as audit, \
             patch.object(broker, 'execute', return_value={'returncode':7,'stdout':'','stderr':'busy'}):
            broker.handle(conn, 1001)
        records = [call.args[0] for call in audit.call_args_list]
        self.assertEqual([r['phase'] for r in records], ['accepted','finished'])
        self.assertEqual(records[0]['id'], records[1]['id'])
        self.assertEqual(records[1]['uid'], 1001)
        self.assertEqual(records[1]['returncode'], 7)


@unittest.skipUnless(os.name == 'posix', 'Linux credentials and process groups')
class PosixTests(unittest.TestCase):
    def test_config_publication_replaces_links_without_writing_their_targets(self):
        import grp
        ns = {'__name__': 'restore_config_test'}
        code = SOURCE.split("<< 'PY_RESTORE_CONFIG'\n", 1)[1].split('\nPY_RESTORE_CONFIG', 1)[0]
        exec(compile(code, '<restore-config>', 'exec'), ns)
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            instance = base / 'instance'
            instance.mkdir(mode=0o770)
            source, victim = base/'source', base/'outside'
            source.write_text('new settings')
            victim.write_text('original code')
            for link in ('symlink', 'hardlink'):
                target = instance/'config.yaml'
                if link == 'symlink': target.symlink_to(victim)
                else: os.link(victim, target)
                ns['publish_config'](source, instance, 'config.yaml', grp.getgrgid(os.getgid()).gr_name)
                self.assertEqual(victim.read_text(), 'original code')
                self.assertFalse(target.is_symlink())
                self.assertEqual(target.read_text(), 'new settings')
                self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o640)
                self.assertEqual(list(instance.glob('.restore-config-*')), [])
                target.unlink()
            (base/'redirect').symlink_to(instance, target_is_directory=True)
            with self.assertRaises(OSError):
                ns['publish_config'](source, base/'redirect', 'config.yaml', grp.getgrgid(os.getgid()).gr_name)
            (base/'source-link').symlink_to(victim)
            with self.assertRaises(OSError):
                ns['publish_config'](base/'source-link', instance, 'config.yaml', grp.getgrgid(os.getgid()).gr_name)
            self.assertFalse((instance/'config.yaml').exists())
            self.assertEqual(victim.read_text(), 'original code')
            self.assertEqual(list(instance.glob('.restore-config-*')), [])

    def test_socketpair_uses_real_peer_credentials(self):
        left, right = socket.socketpair()
        with left, right, patch.object(broker, 'execute') as execute:
            thread = threading.Thread(target=broker.handle, args=(right, os.getuid()))
            thread.start()
            left.sendall(b'{"version":1,"args":["ping"]}')
            left.shutdown(socket.SHUT_WR)
            self.assertEqual(json.loads(left.recv(4096))['stdout'], 'maintenance protocol 1')
            thread.join(timeout=5)
            self.assertFalse(thread.is_alive())
            execute.assert_not_called()

    def test_protected_journal_rotates_without_storing_helper_output(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp) / 'audit'
            # Simulate ownership for an unprivileged CI account. Real files,
            # locks, rotation, permissions and durable writes are exercised.
            with patch.object(broker, 'AUDIT', directory), patch.object(broker, 'trusted'):
                broker.audit({'id':'one','phase':'accepted'})
                path = directory / 'actions.jsonl'
                path.write_bytes(b'x'*(1024*1024))
                broker.audit({'id':'two','phase':'finished','returncode':0})
                self.assertEqual(json.loads(path.read_text())['id'], 'two')
                self.assertEqual((directory/'actions.jsonl.1').stat().st_size, 1024*1024)
                self.assertEqual(stat.S_IMODE(directory.stat().st_mode), 0o700)
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def test_helper_timeout_and_output_limit_are_bounded(self):
        with tempfile.TemporaryDirectory() as temp:
            helper = Path(temp) / 'helper'
            helper.write_text('#!/bin/sh\nsleep 5\n')
            helper.chmod(0o700)
            with patch.object(broker, 'HELPER', helper), patch.object(broker, 'trusted'):
                response = broker.execute(['ping'], 0.1, 'test')
                self.assertIn('timed out', response['stderr'])
                helper.write_text('#!/bin/sh\nhead -c 200000 /dev/zero\n')
                response = broker.execute(['ping'], 5, 'test')
                self.assertIn('output limit', response['stderr'])

    def test_no_client_environment_reaches_helper(self):
        with tempfile.TemporaryDirectory() as temp:
            helper = Path(temp) / 'helper'
            helper.write_text('#!/bin/sh\nprintf "%s" "${EVIL-missing}:$GNSS_BROKER_REQUEST"\n')
            helper.chmod(0o700)
            with patch.object(broker, 'HELPER', helper), patch.object(broker, 'trusted'), patch.dict(os.environ, EVIL='bad'):
                response = broker.execute([], 5, 'abc')
            self.assertEqual(response['stdout'], 'missing:abc')


class ClientTests(unittest.TestCase):
    def test_untrusted_peer_is_rejected_before_request_is_sent(self):
        info = Mock(st_mode=stat.S_IFSOCK|0o660, st_uid=0)
        sock = Mock()
        sock.__enter__ = Mock(return_value=sock); sock.__exit__ = Mock(return_value=False)
        sock.getsockopt.return_value = struct.pack('3i', 1, 1001, 1001)
        with patch.object(client.socket, 'AF_UNIX', 1, create=True), \
             patch.object(client.socket, 'SO_PEERCRED', 17, create=True), \
             patch.object(client.os, 'lstat', return_value=info), patch.object(client.socket, 'socket', return_value=sock):
            with self.assertRaisesRegex(RuntimeError, 'Untrusted maintenance'): client.run(['restart-service'])
        sock.sendall.assert_not_called()

    def test_connection_failure_is_not_retried_or_fallback_to_sudo(self):
        info = Mock(st_mode=stat.S_IFSOCK|0o660, st_uid=0)
        sock = Mock()
        sock.__enter__ = Mock(return_value=sock); sock.__exit__ = Mock(return_value=False)
        sock.connect.side_effect = ConnectionRefusedError()
        with patch.object(client.socket, 'AF_UNIX', 1, create=True), \
             patch.object(client.os, 'lstat', return_value=info), patch.object(client.socket, 'socket', return_value=sock), \
             patch.object(subprocess, 'run') as run:
            with self.assertRaisesRegex(RuntimeError, 'check operation status'): client.run(['restart-service'])
            sock.connect.assert_called_once(); run.assert_not_called()


class PackagingTests(unittest.TestCase):
    def test_embedded_modules_match_and_sudo_not_used(self):
        for name, delimiter in [('maintenance_broker','PY_MAINTENANCE_BROKER'), ('maintenance_client','PY_MAINTENANCE_CLIENT')]:
            code = SOURCE.split("<< '"+delimiter+"' || return 1\n",1)[1].split('\n'+delimiter,1)[0]
            self.assertEqual(code.rstrip(), (ROOT/'runtime'/f'{name}.py').read_text(encoding='utf-8').rstrip())
        self.assertNotIn("['sudo', '-n', PRIVILEGED_HELPER_PATH", SOURCE)
        self.assertNotIn('NoNewPrivileges=no', SOURCE)
        self.assertNotIn('NOPASSWD:', SOURCE)
        self.assertIn('"$BASE/maintenance-broker.py" \\', bash_function('print_install_rollback_paths'))
        self.assertIn('gnss-caster-maintenance.socket', bash_function('restore_install_rollback_snapshot'))
        self.assertIn('chmod 750 "$LOG_DIR"', bash_function('set_runtime_permissions'))
        self.assertNotIn('chmod 770 "$BACKUP_DIR" "$LOG_DIR"', SOURCE)

    @unittest.skipUnless(shutil.which('systemd-analyze'), 'systemd unit validator')
    def test_systemd_socket_and_template_validate_without_starting_services(self):
        with tempfile.TemporaryDirectory() as temp:
            for name, delimiter in [('gnss-caster-maintenance.socket','BROKER_SOCKET'), ('gnss-caster-maintenance@.service','BROKER_SERVICE')]:
                body = SOURCE.split("<< '"+delimiter+"'\n",1)[1].split('\n'+delimiter,1)[0]
                (Path(temp)/name).write_text(body)
            result = subprocess.run(['systemd-analyze','verify',str(Path(temp)/'gnss-caster-maintenance.socket'),str(Path(temp)/'gnss-caster-maintenance@.service')],capture_output=True,text=True,timeout=30)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)


@unittest.skipUnless(find_bash(), 'Bash required')
class RestoreBoundaryTests(unittest.TestCase):
    def test_data_restore_keeps_code_but_local_full_restore_can_replace_it(self):
        body = SOURCE.split('if [ "$RESTORE_DATA_ONLY" -eq 0 ] && [ -f "$RESTORE_DIR/config.py" ]; then\n',1)[1].split('\nchown -R root:root "$BASE_DIR/app"',1)[0]
        body = 'if [ "$RESTORE_DATA_ONLY" -eq 0 ] && [ -f "$RESTORE_DIR/config.py" ]; then\n' + body
        for mode in ('0','1'):
            with tempfile.TemporaryDirectory(dir=ROOT/'tests') as temp:
                harness = '''set -e
export PATH="/usr/bin:/bin:$PATH"
TEST_ROOT=$(cd "$TEST_ROOT" && pwd)
BASE_DIR="$TEST_ROOT/runtime"
INSTANCE_DIR="$BASE_DIR/instance"
RESTORE_DIR="$TEST_ROOT/archive"
TMP_DIR="$TEST_ROOT/stage"
mkdir -p "$INSTANCE_DIR" "$BASE_DIR/app" "$RESTORE_DIR" "$TMP_DIR/staged-app/app"
printf old > "$BASE_DIR/app/code.py"
printf old > "$INSTANCE_DIR/config.py"
printf archive > "$TMP_DIR/staged-app/app/code.py"
printf archive > "$RESTORE_DIR/config.py"
log() { :; }
error() { echo "$*" >&2; }
publish_restore_config() { cp "$1" "$INSTANCE_DIR/$2"; }
rm() {
  for arg in "$@"; do case "$arg" in -*) ;; "$TEST_ROOT"/*) ;; *) exit 99;; esac; done
  command rm "$@"
}
'''
                result = subprocess.run([find_bash()], input=harness+body, env=dict(os.environ, TEST_ROOT=temp, RESTORE_DATA_ONLY=mode), text=True,capture_output=True,timeout=10)
                self.assertEqual(result.returncode,0,result.stderr)
                expected = 'old' if mode == '1' else 'archive'
                self.assertEqual((Path(temp)/'runtime/app/code.py').read_text(), expected)
                self.assertEqual((Path(temp)/'runtime/instance/config.py').read_text(), expected)

    def test_broker_restore_helper_passes_data_only(self):
        body = SOURCE.split('    systemd-job|systemd-data-restore)\n',1)[1].split('\n    write-logrotate)',1)[0].rsplit(';;',1)[0]
        body = body.replace('exec systemd-run', 'systemd_run')
        harness = '''set -eu
action=systemd-data-restore
validate_unit_name() { :; }
validate_backup_name() { :; }
die() { echo "$*" >&2; exit 1; }
systemd_run() { printf '%s\\n' "$@"; }
'''
        result = subprocess.run([find_bash(),'-s','--','systemd-data-restore','gnss-caster-restore-1.service','backup_a.tar.gz'], input=harness+body,text=True,capture_output=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('/opt/gnss-caster/restore.sh\n--data-only\nbackup_a.tar.gz',result.stdout)

    def test_restore_rollback_code_is_outside_web_writable_backups(self):
        self.assertNotIn('ROLLBACK_DIR="$BACKUP_DIR/rollback_before_restore_',SOURCE)
        self.assertIn('RESTORE_ROLLBACK_ROOT=/var/backups/gnss-caster',SOURCE)
        self.assertIn('mktemp -d "$RESTORE_ROLLBACK_ROOT/restore-$TIMESTAMP-XXXXXX"',SOURCE)
