"""Tag-driven release publishing and the one-command bootstrap (install.sh).

No GitHub access: gh is replaced by an in-memory release store, and the
bootstrap's download function is replaced by copies from a temporary folder.
"""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('publish_release', ROOT / 'tools/publish_release.py')
publisher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(publisher)
REPO = 'stepm65/GNSS-Caster'
BASH = shutil.which('bash')


class FakeGitHub:
    """Enough of `gh api` / `gh release` for publish(): one repository's releases."""

    def __init__(self, releases=()):
        self.releases = [dict(item) for item in releases]
        self.calls = []

    def __call__(self, arguments):
        self.calls.append(arguments)
        if arguments[0] == 'api':
            tag = arguments[-1].split('"')[1]
            return ''.join(json.dumps(item) + '\n' for item in self.releases if item['tag_name'] == tag)
        command, tag = arguments[1], arguments[2]
        if command == 'create':
            files = [Path(item) for item in arguments[3:arguments.index('--repo')]]
            self.releases.append({'tag_name': tag, 'draft': False, 'prerelease': False,
                                  'name': arguments[arguments.index('--title') + 1], 'body': 'notes',
                                  'assets': [self.asset(path) for path in files]})
            return ''
        release = next(item for item in self.releases if item['tag_name'] == tag)
        if command == 'upload':
            path = Path(arguments[3])
            if any(item['name'] == path.name for item in release['assets']) and '--clobber' not in arguments:
                raise publisher.PublishError('asset exists')
            release['assets'] = [item for item in release['assets'] if item['name'] != path.name] + [self.asset(path)]
        elif command == 'edit':
            if '--draft=false' in arguments:
                release['draft'] = False
            if '--prerelease=false' in arguments:
                release['prerelease'] = False
            if '--title' in arguments:
                release['name'] = arguments[arguments.index('--title') + 1]
            if '--notes-file' in arguments:
                release['body'] = 'notes'
        return ''

    @staticmethod
    def asset(path):
        return {'name': path.name, 'digest': 'sha256:' + hashlib.sha256(path.read_bytes()).hexdigest()}

    def mutations(self):
        return [call for call in self.calls if call[0] == 'release']


class PublishReleaseTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        (self.root / 'gnss-caster-install.sh').write_bytes(b'#!/bin/bash\nCASTER_VERSION="3.5.0"\n')
        (self.root / 'SHA256SUMS').write_text('x  gnss-caster-install.sh\n')
        (self.root / 'release-notes.md').write_text('## 3.5.0\n')

    def publish(self, gh, tag='v3.5.0'):
        return publisher.publish(tag, REPO, self.root, gh=gh, wait=lambda seconds: None, attempts=2)

    def test_pushed_tag_creates_a_published_release_with_both_files(self):
        gh = FakeGitHub()
        release = self.publish(gh)
        self.assertFalse(release['draft'])
        self.assertEqual(release['name'], 'GNSS Caster 3.5.0')
        self.assertEqual({item['name'] for item in release['assets']}, {'gnss-caster-install.sh', 'SHA256SUMS'})
        create = gh.mutations()[0]
        self.assertEqual(create[:3], ['release', 'create', 'v3.5.0'])
        self.assertIn('--verify-tag', create)

    def test_release_published_on_github_gets_files_and_keeps_author_text(self):
        gh = FakeGitHub([{'tag_name': 'v3.5.0', 'draft': False, 'prerelease': False,
                          'name': 'Field release', 'body': 'Written by the author', 'assets': []}])
        release = self.publish(gh)
        self.assertEqual(release['name'], 'Field release')
        self.assertEqual(release['body'], 'Written by the author')
        self.assertEqual(len(release['assets']), 2)
        self.assertFalse(any(call[1] == 'edit' for call in gh.mutations()))

    def test_draft_is_completed_and_published(self):
        gh = FakeGitHub([{'tag_name': 'v3.5.0', 'draft': True, 'prerelease': True, 'name': '', 'body': '',
                          'assets': [{'name': 'gnss-caster-install.sh', 'digest': 'sha256:' + '0' * 64}]}])
        release = self.publish(gh)
        self.assertFalse(release['draft'])
        self.assertFalse(release['prerelease'])
        self.assertEqual(release['name'], 'GNSS Caster 3.5.0')
        self.assertIn('--clobber', next(call for call in gh.mutations() if call[1] == 'upload'))

    def test_rerun_for_the_same_commit_changes_nothing(self):
        gh = FakeGitHub()
        self.publish(gh)
        before = len(gh.mutations())
        self.publish(gh)
        self.assertEqual(len(gh.mutations()), before)

    def test_published_file_is_never_replaced(self):
        gh = FakeGitHub()
        self.publish(gh)
        (self.root / 'gnss-caster-install.sh').write_bytes(b'#!/bin/bash\nCASTER_VERSION="3.5.0"\n# changed\n')
        with self.assertRaisesRegex(publisher.PublishError, 'never replaced'):
            self.publish(gh)
        self.assertFalse(any('--clobber' in call for call in gh.mutations()))

    def test_invalid_tag_and_missing_files_are_refused(self):
        for tag in ('3.5.0', 'v3.5', 'v3.5.0-rc1', 'v3.5.0;id', 'v03.5.0'):
            with self.assertRaises(publisher.PublishError):
                self.publish(FakeGitHub(), tag)
        (self.root / 'SHA256SUMS').unlink()
        with self.assertRaisesRegex(publisher.PublishError, 'prepare_release'):
            self.publish(FakeGitHub())

    def test_release_that_never_reaches_published_state_fails(self):
        gh = FakeGitHub()
        original = gh.__call__

        def keep_draft(arguments):
            result = original(arguments)
            for item in gh.releases:
                item['draft'] = True
            return result
        with self.assertRaisesRegex(publisher.PublishError, 'not published'):
            publisher.publish('v3.5.0', REPO, self.root, gh=keep_draft, wait=lambda seconds: None, attempts=2)


class ReleaseWorkflowTests(unittest.TestCase):
    def test_workflow_publishes_from_tags_after_checks(self):
        text = (ROOT / '.github/workflows/release.yml').read_text(encoding='utf-8')
        self.assertIn("- 'v[0-9]+.[0-9]+.[0-9]+'", text)
        self.assertIn('types: [published]', text)
        self.assertIn('merge-base --is-ancestor "$GITHUB_SHA" origin/main', text)
        self.assertIn('uses: ./.github/workflows/checks.yml', text)
        self.assertIn('needs: checks', text)
        self.assertIn('tools/publish_release.py', text)
        self.assertNotIn('--draft', text)


@unittest.skipUnless(BASH and os.name == 'posix', 'bootstrap tests need bash')
class BootstrapTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.temp = Path(temp.name)
        self.server = self.temp / 'server'
        self.server.mkdir()
        self.work = self.temp / 'work'
        self.work.mkdir()

    def serve(self, version='3.5.0', sums=None):
        installer = self.server / 'gnss-caster-install.sh'
        installer.write_text(f'#!/bin/bash\n[ "$1" = --version ] && echo "gnss-caster {version}"\nexit 0\n')
        digest = hashlib.sha256(installer.read_bytes()).hexdigest()
        (self.server / 'SHA256SUMS').write_text(sums if sums is not None else f'{digest}  gnss-caster-install.sh\n')

    def bash(self, script, **env):
        prelude = (f'GNSS_CASTER_BOOTSTRAP_LIBRARY=1; source {ROOT / "install.sh"}\n'
                   f'fetch(){{ cp "{self.server}/${{1##*/}}" "$2"; }}\n')
        return subprocess.run([BASH, '-c', prelude + script], capture_output=True, text=True,
                              env=dict(os.environ, **env))

    def download(self, tag='v3.5.0'):
        return self.bash(f'download_release {tag} {self.work}')

    def test_verified_release_downloads(self):
        self.serve()
        result = self.download()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('SHA256 verified', result.stdout)

    def test_replaced_installer_is_refused(self):
        self.serve()
        with open(self.server / 'gnss-caster-install.sh', 'a') as handle:
            handle.write('# replaced\n')
        result = self.download()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('SHA256 mismatch', result.stderr)

    def test_malformed_checksum_file_is_refused(self):
        digest = '0' * 64
        for sums in ('', f'{digest}  other.sh\n', f'{digest}  gnss-caster-install.sh\n{digest}  x\n',
                     f'{digest} gnss-caster-install.sh\n'):
            self.serve(sums=sums)
            result = self.download()
            self.assertNotEqual(result.returncode, 0, sums)
            self.assertIn('SHA256SUMS', result.stderr)

    def test_tag_must_match_installer_version(self):
        self.serve(version='3.4.1')
        result = self.download('v3.5.0')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('contains installer version 3.4.1', result.stderr)

    def test_version_helpers(self):
        result = self.bash('valid_tag v3.10.0 && ! valid_tag v3.5 && ! valid_tag "v3.5.0;id" && ! valid_tag v3.5.0-rc1 '
                           '&& version_older 3.9.0 3.10.0 && ! version_older 3.10.0 3.9.0 && ! version_older 3.5.0 3.5.0 '
                           '&& echo ok')
        self.assertEqual(result.stdout.strip(), 'ok', result.stderr)

    def test_installed_version_is_read_from_the_generated_module(self):
        module = self.temp / 'version.py'
        module.write_text('"""GNSS Caster application version (generated by the installer)."""\n__version__ = "3.4.1"\n')
        result = self.bash(f'INSTALLED_VERSION_FILE={module}; installed_version')
        self.assertEqual(result.stdout.strip(), '3.4.1')
        result = self.bash(f'INSTALLED_VERSION_FILE={self.temp / "missing.py"}; installed_version')
        self.assertEqual((result.returncode, result.stdout), (0, ''))

    def test_bootstrap_syntax(self):
        subprocess.run([BASH, '-n', str(ROOT / 'install.sh')], check=True)


if __name__ == '__main__':
    unittest.main()
