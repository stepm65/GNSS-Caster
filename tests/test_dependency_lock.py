import importlib.util
import json
from pathlib import Path
import re
import unittest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('lock_builder',ROOT/'tools/build_dependency_lock.py')
builder=importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)

class DependencyLockTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source=(ROOT/'gnss-caster-install-3.0.1.sh').read_text(encoding='utf-8')
        cls.lock=cls.source.split("cat > $BASE/requirements.txt << 'EOF'\n",1)[1].split('\nEOF',1)[0]
        cls.metadata=json.loads((ROOT/'tests/dependency_metadata.json').read_text())
        logical=cls.lock.replace('\\\n',' ')
        cls.entries={}
        for line in logical.splitlines():
            if not line.strip() or line.startswith('#'): continue
            head,*hashes=line.split()
            req=builder.Requirement(head)
            cls.entries[builder.canonicalize_name(req.name)]=(req,hashes)

    def test_every_package_has_exact_version_and_release_hashes(self):
        self.assertEqual(set(self.entries),set(self.metadata))
        for name,(req,hashes) in self.entries.items():
            item=self.metadata[name]
            self.assertEqual(str(req.specifier),'=='+item['version'])
            self.assertEqual(set(hashes),{'--hash=sha256:'+f['sha256'] for f in item['files']})

    def test_all_linux_runtime_dependencies_are_present_and_satisfied(self):
        for item in self.metadata.values():
            for raw in item['requires_dist']:
                req=builder.Requirement(raw)
                if builder.applies(req):
                    dependency=self.metadata[builder.canonicalize_name(req.name)]
                    self.assertIn(dependency['version'],req.specifier,raw)

    def test_supported_python_versions_satisfy_metadata(self):
        for item in self.metadata.values():
            for target in builder.TARGETS:
                self.assertIn(target['python_full_version'],builder.SpecifierSet(item['requires_python'] or ''))

    def test_every_installer_pip_install_enforces_hashes(self):
        commands=[line for line in self.source.splitlines() if '-m pip install' in line]
        self.assertEqual(len(commands),3)
        self.assertTrue(all('--require-hashes' in line for line in commands))
        self.assertNotRegex(self.source,r'(?m)^\s*pip install --upgrade')
        self.assertEqual(self.source.count('-m pip check'),3)

if __name__=='__main__': unittest.main()
