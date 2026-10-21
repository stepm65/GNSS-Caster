"""Release checks must inspect committed content without repairing it first."""
import base64
import gzip
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('embed_frontend', ROOT / 'tools/embed_frontend.py')
embed = importlib.util.module_from_spec(spec)
spec.loader.exec_module(embed)


class PackagingConsistencyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'assets').mkdir()
        (self.root / '.vite').mkdir()
        (self.root / '.vite/manifest.json').write_text(json.dumps({'src/main.jsx': {'file': 'assets/main.js'}}))
        (self.root / 'assets/main.js').write_text('console.log("current");')
        (self.root / 'base.html').write_text('<script src="__ENTRY__"></script>')
        self.source = "repair_installed_template_from_installer() {\n}\ncat > $APP/web/templates/base.html << 'EOF'\nold\nEOF\n"

    def test_stale_asset_and_stale_template_are_both_detected(self):
        source, _ = embed.render(self.source, self.root, self.root)
        self.assertEqual(embed.semantic_source(source), embed.semantic_source(embed.render(source, self.root, self.root)[0]))
        (self.root / 'assets/main.js').write_text('console.log("new");')
        self.assertNotEqual(embed.semantic_source(source), embed.semantic_source(embed.render(source, self.root, self.root)[0]))
        (self.root / 'assets/main.js').write_text('console.log("current");')
        (self.root / 'base.html').write_text('<script defer src="__ENTRY__"></script>')
        self.assertNotEqual(embed.semantic_source(source), embed.semantic_source(embed.render(source, self.root, self.root)[0]))

    def test_compression_metadata_does_not_change_semantic_comparison(self):
        source, _ = embed.render(self.source, self.root, self.root)
        import re
        match = re.search(r'payload = """\n([A-Za-z0-9+/=\s]+)\n"""', source)
        payload = gzip.decompress(base64.b64decode(match[1]))
        replacement = base64.b64encode(gzip.compress(payload, mtime=123456)).decode()
        alternative = source[:match.start(1)] + replacement + source[match.end(1):]
        self.assertNotEqual(source, alternative)
        self.assertEqual(embed.semantic_source(source), embed.semantic_source(alternative))

    def test_installer_code_changes_are_not_ignored(self):
        source, _ = embed.render(self.source, self.root, self.root)
        self.assertNotEqual(embed.semantic_source(source), embed.semantic_source(source.replace("os.replace(temporary, path)", "pass")))
