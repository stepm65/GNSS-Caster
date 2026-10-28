import gzip
import io
import os
from pathlib import Path
import re
import secrets
import shutil
import tempfile
import unittest
from types import SimpleNamespace as NS
from unittest.mock import patch
from test_security_regressions import load_function, SOURCE

class UploadTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.save=load_function('_store_uploaded_backup',dict(os=os,shutil=shutil,re=re,secrets=secrets,tempfile=tempfile))
    def upload(self,name='backup_20260901_120000.tar.gz',body=None,limit=1024):
        return self.save(NS(filename=name,stream=io.BytesIO(gzip.compress(b'archive') if body is None else body)),str(self.root),limit)
    def test_upload_keeps_date_and_never_replaces_old_copy(self):
        a=self.upload();b=self.upload()
        self.assertNotEqual(a['filename'],b['filename'])
        self.assertTrue(a['filename'].startswith('backup_20260901_120000_upload_'))
        self.assertEqual(len(list(self.root.iterdir())),2)
    def test_encrypted_backup_supported(self):
        a=self.upload('copy.tar.gz.enc',b'Salted__'+b'x'*40)
        self.assertTrue(a['encrypted'])
    def test_bad_names_and_extensions_rejected(self):
        for n in ['../backup.tar.gz','C:\\backup.tar.gz','backup.tar.gz\n','backup.zip','']:
            with self.subTest(n=n),self.assertRaises(ValueError): self.upload(n)
        self.assertEqual(list(self.root.iterdir()),[])
    def test_invalid_and_empty_file_removed(self):
        for data in [b'',b'not a backup',b'\x1f\x8b\x08']:
            with self.assertRaises(ValueError): self.upload(body=data)
        self.assertEqual(list(self.root.iterdir()),[])
    def test_oversized_stream_removed_without_content_length(self):
        with self.assertRaises(ValueError): self.upload(body=b'x'*1025)
        self.assertEqual(list(self.root.iterdir()),[])
    def test_disk_full_check_happens_before_writing(self):
        with patch.object(shutil,'disk_usage',return_value=NS(free=0)),self.assertRaises(ValueError): self.upload()
        self.assertEqual(list(self.root.iterdir()),[])
    def test_collision_does_not_overwrite_or_leave_partial(self):
        with patch.object(secrets,'token_hex',return_value='fixed'):
            saved=self.upload()
            before=(self.root/saved['filename']).read_bytes()
            with self.assertRaises(FileExistsError): self.upload()
            self.assertEqual((self.root/saved['filename']).read_bytes(),before)
        self.assertEqual(len(list(self.root.iterdir())),1)
    def test_copy_failure_cleans_partial_file(self):
        class Broken:
            def read(self,*args): raise OSError('failed')
        with self.assertRaises(OSError): self.save(NS(filename='backup.tar.gz',stream=Broken()),str(self.root),1024)
        self.assertEqual(list(self.root.iterdir()),[])
    def test_non_admin_rejected_before_file_access(self):
        denied=({'error':'denied'},403)
        fn=load_function('api_system_backup_upload',{'_require_admin_role':lambda:denied})
        self.assertEqual(fn(),denied)
    def test_nginx_patch_preserves_tls_and_is_idempotent(self):
        code=SOURCE.split("<< 'PY_UPLOAD_NGINX'\n",1)[1].split('\nPY_UPLOAD_NGINX\n',1)[0]
        cfg=self.root/'nginx.conf'
        cfg.write_text('server {\n listen 443 ssl;\n ssl_certificate /safe/cert;\n location /api/ {\n proxy_pass http://127.0.0.1:8080;\n proxy_read_timeout 60s;\n }\n}\n')
        import sys
        with patch.object(sys,'argv',['patch',str(cfg)]):
            exec(code,{});first=cfg.read_text();exec(code,{})
        self.assertEqual(cfg.read_text(),first)
        self.assertEqual(first.count('location = /api/system/backups/upload'),1)
        self.assertIn('ssl_certificate /safe/cert;',first)
        self.assertIn('client_max_body_size 129m;',first)
        for action in ('preview','restore','verify'):
            self.assertEqual(first.count('location = /api/system/backups/'+action),1)
            block=first.split('location = /api/system/backups/'+action+' {',1)[1].split('}',1)[0]
            self.assertIn('proxy_read_timeout 300s;',block)
            self.assertNotIn('proxy_read_timeout 60s;',block)
            self.assertIn('proxy_pass http://127.0.0.1:8080;',block)
        self.assertIn('proxy_read_timeout 60s;',first.split('location /api/ {',1)[1])

if __name__=='__main__': unittest.main()
