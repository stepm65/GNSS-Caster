"""Release updater checks: private fixtures, no system service or internet access."""
import contextlib
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import sqlite3
import tempfile
import time
import unittest
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch
from test_security_regressions import SOURCE, load_function, TREE

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('release_update', ROOT / 'runtime/release_update.py')
updater = importlib.util.module_from_spec(spec)
spec.loader.exec_module(updater)
CONTENT = b'#!/bin/bash\nCASTER_VERSION="3.4.0"\nexit 0\n'
DIGEST = hashlib.sha256(CONTENT).hexdigest()


def release():
    return {'tag_name': 'v3.4.0', 'draft': False, 'prerelease': False, 'body': '<script>notes</script>',
            'assets': [{'name': 'gnss-caster-install.sh', 'digest': 'sha256:' + DIGEST,
                        'browser_download_url': 'https://github.com/stepm65/GNSS-Caster/releases/download/v3.4.0/gnss-caster-install.sh',
                        'state': 'uploaded', 'size': len(CONTENT)}]}


class ReleaseMetadataTests(unittest.TestCase):
    def test_semantic_comparison_and_no_downgrade(self):
        self.assertGreater(updater.version('v3.10.0'), updater.version('3.9.0'))
        self.assertTrue(updater.release_candidate(release(), '3.3.0')['available'])
        self.assertFalse(updater.release_candidate(release(), '3.4.0')['available'])
        self.assertFalse(updater.release_candidate(release(), '4.0.0')['available'])
        self.assertIsNone(updater.release_candidate(None, '3.3.0'))

    def test_rejects_non_stable_and_malformed_versions(self):
        for value in ('main', 'v3.4.0-rc1', '3.4', '03.4.0', '../../x', 'v3.4.0;id', 'v99999.0.0'):
            with self.subTest(value=value), self.assertRaises(updater.UpdateError):
                updater.version(value)
        for field in ('draft', 'prerelease'):
            data = release(); data[field] = True
            with self.assertRaises(updater.UpdateError):
                updater.release_candidate(data, '3.3.0')

    def test_rejects_missing_digest_wrong_origin_bad_size_and_duplicate_asset(self):
        for field, value in [('digest', None), ('digest', 'sha256:' + 'x' * 64),
                             ('browser_download_url', 'https://evil.example/installer.sh'),
                             ('state', 'new'), ('size', updater.MAX_ASSET + 1), ('size', 0), ('size', '1')]:
            data = release(); data['assets'][0][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(updater.UpdateError):
                updater.release_candidate(data, '3.3.0')
        data = release(); data['assets'] *= 2
        with self.assertRaises(updater.UpdateError):
            updater.release_candidate(data, '3.3.0')

    def test_redirect_allowlist_rejects_local_urls_and_credentials(self):
        for url in ('http://github.com/file', 'file:///etc/passwd', 'https://127.0.0.1/x',
                    'https://github.com.evil.example/x', 'https://x@github.com/file', 'https://github.com:444/x'):
            self.assertFalse(updater.allowed_url(url), url)
        self.assertTrue(updater.allowed_url('https://release-assets.githubusercontent.com/file?token=public'))
        with self.assertRaises(updater.UpdateError):
            updater.GitHubRedirect().redirect_request(None, None, 302, '', {}, 'http://localhost/')

    def test_download_limit_is_enforced_without_trusting_length_header(self):
        response = Mock(headers={})
        response.read.side_effect = [b'123456']
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        with patch.object(updater.urllib.request, 'build_opener', return_value=NS(open=lambda *a, **kw: response)):
            with self.assertRaisesRegex(updater.UpdateError, 'size limit'):
                updater.fetch(updater.API + '/latest', 5)


class ReleaseWorkerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Path(self.temp.name)
        for name, value in [('STORE', self.store), ('current_version', Mock(return_value='3.3.0')),
                            ('write_json', Mock()), ('preflight_space', Mock()), ('active_rovers', Mock(return_value=0)),
                            ('boot_id', Mock(return_value='boot'))]:
            p = patch.object(updater, name, value); p.start(); self.addCleanup(p.stop)
        self.state = {'status': 'queued', 'tag': 'v3.4.0', 'sha256': DIGEST,
                      'started_at': int(time.time()), 'boot_id': 'boot', 'previous_version': '3.3.0'}

    def test_verified_asset_written_only_after_digest_size_and_version_match(self):
        candidate = updater.release_candidate(release(), '3.3.0')
        for bad in (CONTENT + b'corrupt', b'bad'):
            with self.assertRaises(updater.UpdateError):
                updater.install_asset(candidate, bad)
            self.assertFalse((self.store / 'installer.sh').exists())
        wrong = CONTENT.replace(b'3.4.0', b'3.5.0')
        wrong_candidate = dict(candidate, sha256=hashlib.sha256(wrong).hexdigest())
        with self.assertRaisesRegex(updater.UpdateError, 'version'):
            updater.install_asset(wrong_candidate, wrong)
        self.assertEqual(updater.install_asset(candidate, CONTENT).read_bytes(), CONTENT)

    def test_start_rejects_unchecked_stale_modified_and_older_release(self):
        candidate = updater.release_candidate(release(), '3.3.0')
        for saved in ({}, {'checked_at': time.time() - 700, 'candidate': candidate},
                      {'checked_at': time.time(), 'candidate': dict(candidate, sha256='0' * 64)}):
            with patch.object(updater, 'lock', return_value=contextlib.nullcontext()), \
                 patch.object(updater, 'status', return_value={'job': {'status': 'idle'}}), \
                 patch.object(updater, 'read_json', return_value=saved), \
                 patch.object(updater, 'run') as run:
                with self.assertRaises(updater.UpdateError):
                    updater.start('v3.4.0', DIGEST)
                run.assert_not_called()

    def test_double_start_is_rejected_before_launch(self):
        with patch.object(updater, 'lock', return_value=contextlib.nullcontext()), \
             patch.object(updater, 'status', return_value={'job': {'status': 'installing'}}), \
             patch.object(updater, 'run') as run:
            with self.assertRaisesRegex(updater.UpdateError, 'already running'):
                updater.start('v3.4.0', DIGEST)
            run.assert_not_called()

    def test_start_blocks_connected_rovers_and_low_disk(self):
        candidate = updater.release_candidate(release(), '3.3.0')
        for connected in (True, False):
            with patch.object(updater, 'lock', return_value=contextlib.nullcontext()), \
                 patch.object(updater, 'status', return_value={'job': {'status': 'idle'}}), \
                 patch.object(updater, 'read_json', return_value={'checked_at': time.time(), 'candidate': candidate}), \
                 patch.object(updater, 'active_rovers', return_value=int(connected)), \
                 patch.object(updater, 'preflight_space', side_effect=updater.UpdateError('disk full')), \
                 patch.object(updater, 'run') as run:
                with self.assertRaises(updater.UpdateError):
                    updater.start('v3.4.0', DIGEST)
                run.assert_not_called()

    def test_schedule_uses_fixed_isolated_unit_and_persists_before_start(self):
        candidate = updater.release_candidate(release(), '3.3.0')
        def execute(args, **kw):
            if args[0].endswith('systemd-run'):
                self.assertEqual(updater.write_json.call_args.args[1]['status'], 'queued')
                self.assertIn('/usr/bin/python3', args)
                self.assertIn('-I', args)
                self.assertEqual(args[-3:], ['worker', 'v3.4.0', DIGEST])
            return NS(returncode=0)
        with patch.object(updater, 'lock', side_effect=lambda path: contextlib.nullcontext()), \
             patch.object(updater, 'status', return_value={'job': {'status': 'idle'}}), \
             patch.object(updater, 'read_json', return_value={'checked_at': time.time(), 'candidate': candidate}), \
             patch.object(updater, 'run', side_effect=execute) as run:
            self.assertEqual(updater.start('v3.4.0', DIGEST)['status'], 'queued')
            self.assertEqual(len([c for c in run.call_args_list if c.args[0][0].endswith('systemd-run')]), 1)

    def run_worker(self, *, exit_code=0, output='', fetch_error=None, connected=0):
        def execute(args, **kwargs):
            if args[0] == '/bin/bash' and args[-1] == '--repair':
                kwargs['stdout'].write(output)
                kwargs['stdout'].flush()
                if not exit_code:
                    updater.current_version.return_value = '3.4.0'
                return NS(returncode=exit_code)
            return NS(returncode=0)
        with patch.object(updater, 'read_json', return_value=copy.deepcopy(self.state)), \
             patch.object(updater, 'lock', return_value=contextlib.nullcontext(8)), \
             patch.object(updater.os, 'dup2'), \
             patch.object(updater, 'fetch', side_effect=fetch_error or [json.dumps(release()).encode(), CONTENT]), \
             patch.object(updater, 'active_rovers', return_value=connected), \
             patch.object(updater, 'run', side_effect=execute) as run:
            result = updater.worker('v3.4.0', DIGEST)
            return result, run

    def test_success_retains_snapshot_path_and_inherited_lock(self):
        result, run = self.run_worker(output='Rollback snapshot created: /var/backups/gnss-caster/rollback-test\n')
        self.assertEqual(result['status'], 'succeeded')
        self.assertEqual(result['snapshot'], '/var/backups/gnss-caster/rollback-test')
        self.assertEqual(run.call_args.kwargs['pass_fds'], (8,))
        self.assertIn('--repair', run.call_args.args[0])

    def test_failure_never_claims_unconfirmed_rollback(self):
        for output, expected in [('', 'failed'), ('Rollback completed; previous service state restored.', 'rolled_back')]:
            result, _ = self.run_worker(exit_code=1, output=output)
            self.assertEqual(result['status'], expected)
            self.assertIn('finished_at', result)

    def test_network_failure_and_active_rovers_never_execute_installer(self):
        result, run = self.run_worker(fetch_error=updater.UpdateError('offline'))
        self.assertEqual(result['status'], 'failed'); run.assert_not_called()
        result, run = self.run_worker(connected=1)
        self.assertEqual(result['status'], 'failed'); run.assert_not_called()

    def test_reboot_is_reported_as_interruption(self):
        self.state['boot_id'] = 'old-boot'
        with patch.object(updater, 'read_json', side_effect=[self.state, None]), \
             patch.object(updater, 'run', return_value=NS(stdout='inactive')):
            self.assertEqual(updater.status()['job']['status'], 'interrupted')


class ReleaseStorageTests(unittest.TestCase):
    def test_database_check_reads_real_sqlite_without_importing_application(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory).resolve(); instance = base / 'instance'; instance.mkdir()
            dbpath = instance / 'db.sqlite'
            config = instance / 'config.yaml'
            config.write_text(f'database:\n  path: "{dbpath}"\n', encoding='utf-8')
            with contextlib.closing(sqlite3.connect(dbpath)) as db:
                db.execute('CREATE TABLE rover (active_conn INTEGER)')
                db.executemany('INSERT INTO rover VALUES (?)', [(0,), (2,)])
                db.commit()
            # Normalize Windows paths: the supported deployment is Linux; the
            # reader must nevertheless refuse any non-standard configured path.
            with patch.object(updater, 'BASE', base):
                self.assertEqual(updater.active_rovers(), 2)
                config.write_text('database:\n  path: /elsewhere.sqlite\n')
                with self.assertRaisesRegex(updater.UpdateError, 'standard database'):
                    updater.active_rovers()
            dbpath.unlink()

    def test_disk_check_rejects_insufficient_space(self):
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(updater, 'BASE', Path(directory)), \
             patch.object(updater.shutil, 'disk_usage', return_value=NS(free=1)):
            with self.assertRaisesRegex(updater.UpdateError, 'free space'):
                updater.preflight_space()

    @unittest.skipUnless(os.name == 'posix', 'Linux flock and inherited descriptors')
    def test_actual_lock_excludes_second_owner_and_rejects_symlink(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'lock'
            real_fstat = os.fstat
            def owned_stat(fd):
                info = real_fstat(fd)
                return NS(st_mode=info.st_mode, st_uid=0, st_nlink=info.st_nlink)
            with patch.object(updater.os, 'fstat', side_effect=owned_stat):
                with updater.lock(path) as fd:
                    with self.assertRaisesRegex(updater.UpdateError, 'maintenance'):
                        with updater.lock(path):
                            self.fail('second owner acquired the lock')
                    # The same open file description can be inherited by Bash.
                    result = updater.run(['/bin/bash', '-c', f'flock -n {fd}'], pass_fds=(fd,))
                    self.assertEqual(result.returncode, 0)
                with updater.lock(path):
                    pass
                link = Path(directory) / 'symlink'; link.symlink_to(path)
                with self.assertRaises(OSError):
                    with updater.lock(link):
                        self.fail('followed symlink')

    def test_release_packaging_rejects_mismatched_version_and_produces_hash(self):
        spec = importlib.util.spec_from_file_location('prepare_release', ROOT / 'tools/prepare_release.py')
        packager = importlib.util.module_from_spec(spec); spec.loader.exec_module(packager)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'gnss-caster-install.sh').write_bytes(CONTENT)
            (root / 'CHANGES.md').write_text('## 3.4.0 — Test\n\nChanges\n\n## 3.3.0\nOld\n', encoding='utf-8')
            for version in ('3.3.0', '3.4.0;id', '3.4.0-rc1'):
                with self.assertRaises(ValueError):
                    packager.prepare(version, root)
            packager.prepare('3.4.0', root)
            self.assertEqual((root / 'SHA256SUMS').read_text().split()[0], DIGEST)
            self.assertNotIn('Old', (root / 'release-notes.md').read_text(encoding='utf-8'))


class ReleaseRouteTests(unittest.TestCase):
    def namespace(self, data=None):
        return {'request': NS(get_json=lambda **kw: data), '_require_admin_role': lambda: None,
                'jsonify': lambda obj: obj, 're': re, 'current_user': NS(password='hashed'),
                'bcrypt': NS(check_password_hash=Mock(return_value=True)),
                '_get_client_ip': lambda: '127.0.0.1', '_get_login_ip_block_seconds': lambda ip: 0,
                '_record_login_ip_failure': Mock(), 'Rover': NS(query=NS(all=lambda: [])),
                '_release_update_response': Mock(return_value=({'status':'queued'}, 202))}

    def test_all_routes_require_session_and_admin(self):
        for name in ('api_release_update_status', 'api_release_update_check', 'api_release_update_install'):
            namespace = self.namespace()
            namespace['_require_admin_role'] = lambda: ({'error':'denied'},403)
            self.assertEqual(load_function(name, namespace)()[1],403)
            namespace['_release_update_response'].assert_not_called()
            node = next(n for n in __import__('ast').walk(TREE) if isinstance(n, __import__('ast').FunctionDef) and n.name == name)
            self.assertIn('login_required', [__import__('ast').unparse(d) for d in node.decorator_list])

    def test_confirmation_payload_and_release_are_validated(self):
        for data in (None, [], {}, {'confirm':'ОБНОВИТЬ'}, {'confirm':'UPDATE','tag':'../x','sha256':DIGEST}):
            ns=self.namespace(data)
            self.assertEqual(load_function('api_release_update_install',ns)()[1],400)
            ns['_release_update_response'].assert_not_called()

    def test_wrong_password_and_rovers_block_scheduling(self):
        data={'confirm':'UPDATE','tag':'v3.4.0','sha256':DIGEST,'password':'test-only'}
        ns=self.namespace(data); ns['bcrypt'].check_password_hash.return_value=False
        self.assertEqual(load_function('api_release_update_install',ns)()[1],403)
        ns['_record_login_ip_failure'].assert_called_once()
        ns['_release_update_response'].assert_not_called()
        ns=self.namespace(data); ns['Rover'].query.all=lambda:[NS(active_conn=1)]
        self.assertEqual(load_function('api_release_update_install',ns)()[1],409)
        ns['_release_update_response'].assert_not_called()

    def test_password_rate_limit_and_valid_request(self):
        data={'confirm':'UPDATE','tag':'v3.4.0','sha256':DIGEST,'password':'test-only'}
        ns=self.namespace(data); ns['_get_login_ip_block_seconds']=lambda ip:100
        self.assertEqual(load_function('api_release_update_install',ns)()[1],429)
        ns['_release_update_response'].assert_not_called()
        ns=self.namespace(data)
        self.assertEqual(load_function('api_release_update_install',ns)()[1],202)
        ns['_release_update_response'].assert_called_once_with('release-install',('v3.4.0',DIGEST),timeout=40,status_code=202)

    def test_embedded_source_matches_reviewed_module_and_snapshot_includes_it(self):
        embedded=SOURCE.split("<< 'PYTHON_RELEASE_UPDATER'\n",1)[1].split('\nPYTHON_RELEASE_UPDATER',1)[0]
        self.assertEqual(embedded.rstrip(),(ROOT/'runtime/release_update.py').read_text(encoding='utf-8').rstrip())
        self.assertTrue('"$BASE/release-update.py" \\' in SOURCE)
        helper = SOURCE.split('write_privileged_helper() {', 1)[1].split("cat >", 1)[0]
        self.assertLess(helper.index('mkdir -p "$BASE"'), helper.index('write_release_updater'))


if __name__ == '__main__':
    unittest.main()
