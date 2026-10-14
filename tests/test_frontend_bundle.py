"""Verify the actual embedded application, not only frontend source files."""
import ast
import base64
import gzip
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import sys
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / 'gnss-caster-install-3.0.1.sh').read_text(encoding='utf-8')
FACTORY = SOURCE.split("cat > $APP/web/factory.py << 'EOF'\n", 1)[1].split('\nEOF', 1)[0]
TEMPLATES = dict(re.findall(r"cat > \$APP/web/templates/([^\n]+) << 'EOF'\n(.*?)\nEOF\n", SOURCE, re.S))
EMBEDDED = SOURCE.split("<< 'PYTHON_REACT_ASSETS'\n", 1)[1].split('\nPYTHON_REACT_ASSETS', 1)[0]


class ScriptParser(HTMLParser):
    def __init__(self):
        super().__init__(); self.scripts = []; self.current = None
    def handle_starttag(self, tag, attrs):
        if tag == 'script':
            self.current = {'attrs': dict(attrs), 'text': ''}; self.scripts.append(self.current)
    def handle_data(self, data):
        if self.current is not None: self.current['text'] += data
    def handle_endtag(self, tag):
        if tag == 'script': self.current = None


class FrontendBundleTests(unittest.TestCase):
    def test_install_assets_and_verify_hashes(self):
        # Execute the same Python block used by install and --repair in isolation.
        with tempfile.TemporaryDirectory(dir=ROOT / 'validation/ui') as temp:
            with patch.object(sys, 'argv', ['install-ui', temp]):
                exec(compile(EMBEDDED, '<embedded React installer>', 'exec'), {})
            root = Path(temp)
            manifest = json.loads((root / 'manifest.json').read_text())
            self.assertTrue((root / manifest['entry']).is_file())
            for name, digest in manifest['sha256'].items():
                self.assertEqual(hashlib.sha256((root / name).read_bytes()).hexdigest(), digest)
            self.assertIn('/static/ui/' + manifest['entry'], TEMPLATES['base.html'])

    def test_install_and_repair_both_install_assets(self):
        self.assertEqual(len(re.findall(r'^    install_react_ui$', SOURCE, re.M)), 1)
        self.assertEqual(len(re.findall(r'^install_react_ui$', SOURCE, re.M)), 1)
        repair = SOURCE.split('run_repair() {', 1)[1].split('\n}\n', 1)[0]
        self.assertIn('diagnostics.html', repair)
        self.assertIn('backups.html', repair)

    def test_all_templates_render_safe_bootstrap_and_same_application(self):
        from jinja2 import Environment, DictLoader, select_autoescape
        environment = Environment(loader=DictLoader(TEMPLATES), autoescape=select_autoescape(['html']))
        for authenticated in (True, False):
            user = NS(is_authenticated=authenticated, id=1, username='</script><img src=x onerror=alert(1)>', role='admin', must_change_password=False)
            for name in TEMPLATES:
                html = environment.get_template(name).render(current_user=user, csrf_token=lambda: 'test-csrf', csp_nonce=lambda: 'test-nonce', caster_version='test', get_flashed_messages=lambda **_: [])
                parser = ScriptParser(); parser.feed(html)
                bootstrap = next(s for s in parser.scripts if s['attrs'].get('id') == 'gnss-bootstrap')
                data = json.loads(bootstrap['text'])
                self.assertEqual(data['username'], user.username if authenticated else '')
                self.assertNotIn('<img src=x', html)
                self.assertTrue(all(s['attrs'].get('nonce') == 'test-nonce' for s in parser.scripts))
                self.assertEqual(sum(s['attrs'].get('type') == 'module' for s in parser.scripts), 1)

    def test_new_pages_require_login(self):
        tree = ast.parse(FACTORY)
        for name in ('page_diagnostics', 'page_backups'):
            function = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == name)
            self.assertTrue(any(isinstance(d, ast.Name) and d.id == 'login_required' for d in function.decorator_list))

    def test_frontend_assets_have_no_remote_cdn_imports(self):
        tree = ast.parse(EMBEDDED)
        payload = next(ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'payload' for t in n.targets))
        files = json.loads(gzip.decompress(base64.b64decode(payload)))
        for source in files.values():
            self.assertNotRegex(source, r'(?:import\s*\(|from\s*)["\']https?://')
        self.assertNotRegex(TEMPLATES['base.html'], r'(?:src|href)="https?://')


if __name__ == '__main__': unittest.main()
