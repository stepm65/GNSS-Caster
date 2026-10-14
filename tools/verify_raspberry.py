"""Explicitly invoked on the Raspberry Pi; never prints credentials.

backup: restore application files and SQLite into a new private directory.
web: run real Flask authentication tests on a private clone of the database.
ntrip: create a short-lived rover, test the running server, remove the rover.
observe: sample live diagnostics for a bounded interval.
"""
import argparse
import base64
import collections
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import sqlite3
import sys
import tarfile
import tempfile
import time
import urllib.request

BASE = Path('/opt/gnss-caster')
ROOT = Path('/var/backups/gnss-caster')

def report(**values):
    print(json.dumps(values), flush=True)

def connect(path=BASE / 'instance/db.sqlite', readonly=True):
    return sqlite3.connect('file:' + str(path) + ('?mode=ro' if readonly else '?mode=rw'), uri=True, timeout=10)

def private_dir(label):
    ROOT.mkdir(exist_ok=True)
    return Path(tempfile.mkdtemp(prefix=label+'-', dir=ROOT))

def backup(source):
    source = Path(source).resolve()
    assert source.is_relative_to(ROOT.resolve())
    archive = source/'system-before.tar'
    expected = (source/'SHA256SUMS').read_text().split()[0]
    with archive.open('rb') as f:
        assert hashlib.file_digest(f, 'sha256').hexdigest() == expected, 'Archive checksum failed'
    target = private_dir('restore-verification')
    count = 0
    # Restore only application source/config, not system paths or the venv.
    with tarfile.open(archive) as t:
        for member in t:
            name = member.name
            allowed = name.startswith('opt/gnss-caster/app/') or name in (
                'opt/gnss-caster/main.py', 'opt/gnss-caster/requirements.txt',
                'opt/gnss-caster/instance/config.yaml', 'opt/gnss-caster/instance/config.py')
            if not allowed:
                continue
            dest = (target/name).resolve()
            assert dest.is_relative_to(target)
            if member.isdir():
                dest.mkdir(parents=True, exist_ok=True)
            elif member.isfile():
                dest.parent.mkdir(parents=True, exist_ok=True)
                with t.extractfile(member) as inp, dest.open('xb') as out:
                    shutil.copyfileobj(inp, out)
                assert dest.stat().st_size == member.size
                count += 1
            else:
                raise AssertionError('Unexpected source link or special file')
    dbpath = target/'restored.sqlite'
    with connect(source/'db.sqlite') as old, sqlite3.connect(dbpath) as new:
        old.backup(new)
        assert new.execute('PRAGMA integrity_check').fetchall() == [('ok',)]
        counts = {t:new.execute('SELECT count(*) FROM '+t).fetchone()[0]
                  for t in ['admin','base_station','rover','mountpoint']}
    assert (target/'opt/gnss-caster/app/web/factory.py').is_file()
    report(check='backup', result='PASS', restored_files=count, counts=counts, directory=str(target))

def web(installer=None):
    import yaml
    work = private_dir('web-verification')
    shutil.copytree(BASE/'app', work/'app', ignore=shutil.ignore_patterns('__pycache__'))
    if installer:
        source=Path(installer).read_text()
        for relative in ['web/factory.py','web/templates/system_configuration.html']:
            marker="cat > $APP/"+relative+" << 'EOF'\n"
            (work/'app'/relative).write_text(source.split(marker,1)[1].split('\nEOF\n',1)[0]+'\n')
    (work/'instance').mkdir()
    dbpath = work/'instance/db.sqlite'
    with connect() as src, sqlite3.connect(dbpath) as dst:
        src.backup(dst)
        dst.execute("UPDATE system_setting SET value='false' WHERE key IN ('telegram_enabled','telegram_commands_enabled','gnss_time_sync')")
    cfg = yaml.safe_load((BASE/'instance/config.yaml').read_text())
    cfg['database']['path'] = str(dbpath)
    cfg['logging']['level'] = 'ERROR'
    cfg['security']['bootstrap_admin_password_file'] = str(work/'bootstrap')
    (work/'instance/config.yaml').write_text(yaml.safe_dump(cfg))
    os.environ['SECRET_KEY'] = secrets.token_hex(32)
    sys.path.insert(0, str(work))
    from app.web.factory import create_app
    from app.db.models import db, Admin
    import bcrypt
    import pyotp
    app = create_app()
    app.config['TESTING'] = True
    assert Path(dbpath).resolve().is_relative_to(work)
    username = 'verify_'+secrets.token_hex(4)
    password, changed = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
    with app.app_context():
        assert str(db.engine.url.database) == str(dbpath)
        admin = Admin(username=username, password=bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode(), role='admin', must_change_password=False)
        db.session.add(admin); db.session.commit()
    a, b = app.test_client(), app.test_client()
    checks = []
    def csrf(client):
        client.get('/login')
        with client.session_transaction() as sess:
            return sess['_csrf_token']
    def post(client, route, data=None, payload=None):
        token = csrf(client)
        return client.post(route, data=data, json=payload, headers={'X-CSRF-Token':token})
    def login(client, pw):
        return post(client, '/login', data={'username':username,'password':pw})
    def passed(name, condition):
        assert condition, name
        checks.append(name)
    passed('login', login(a,password).status_code == 302 and a.get('/api/2fa/status').status_code == 200)
    passed('second_session', login(b,password).status_code == 302)
    passed('csrf_rejected', a.post('/api/2fa/setup').status_code == 403)
    # Locate the installed route instead of assuming a URL spelling.
    route = next(r.rule for r in app.url_map.iter_rules() if r.endpoint == 'api_change_password')
    r = post(a,route,payload={'current_password':password,'new_password':changed,'confirm_password':changed})
    passed('password_change', r.status_code == 200)
    passed('old_session_revoked', b.get('/api/2fa/status').status_code in (302,401))
    passed('current_session_preserved', a.get('/api/2fa/status').status_code == 200)
    secret = post(a,'/api/2fa/setup').get_json()['secret']
    r = post(a,'/api/2fa/enable',payload={'code':pyotp.TOTP(secret).now()})
    passed('2fa_enable', r.status_code == 200 and len(r.get_json()['backup_codes']) == 10)
    passed('active_2fa_setup_rejected', post(a,'/api/2fa/setup').status_code == 409)
    post(a, '/logout')
    passed('logout', a.get('/api/2fa/status').status_code in (302,401))
    r = login(a,changed)
    passed('2fa_challenge', r.status_code == 302 and '2fa' in r.location)
    passed('password_alone_not_authenticated', a.get('/api/2fa/status').status_code in (302,401))
    route = next(r.rule for r in app.url_map.iter_rules() if r.endpoint == 'login_2fa')
    passed('2fa_login', post(a,route,data={'code':pyotp.TOTP(secret).now()}).status_code == 302 and a.get('/api/2fa/status').status_code == 200)
    passed('2fa_wrong_password_rejected', post(a,'/api/2fa/disable',payload={'password':'incorrect'}).status_code == 403)
    passed('2fa_disable', post(a,'/api/2fa/disable',payload={'password':changed}).status_code == 200)
    if any(r.endpoint=='api_system_backup_upload' for r in app.url_map.iter_rules()):
        import io,gzip
        uploads=work/'uploads';uploads.mkdir()
        app.config['BACKUP_UPLOAD_DIR']=str(uploads)
        body=gzip.compress(os.urandom(3*1024*1024))
        passed('upload_requires_csrf', a.post('/api/system/backups/upload',data={'file':(io.BytesIO(body),'backup_test.tar.gz')}).status_code==403)
        passed('missing_upload_rejected', post(a,'/api/system/backups/upload').status_code==400)
        passed('invalid_upload_rejected', post(a,'/api/system/backups/upload',data={'file':(io.BytesIO(b'bad'),'backup_test.tar.gz')}).status_code==400)
        r=post(a,'/api/system/backups/upload',data={'file':(io.BytesIO(body),'backup_20260901_120000.tar.gz')})
        passed('multipart_upload_over_2mb',r.status_code==201)
        saved=r.get_json()['filename']
        passed('upload_bytes_preserved',(uploads/saved).read_bytes()==body)
        with app.app_context():
            admin=Admin.query.filter_by(username=username).one();admin.role='viewer';db.session.commit()
        passed('viewer_cannot_upload',post(a,'/api/system/backups/upload',data={'file':(io.BytesIO(body),'backup_test.tar.gz')}).status_code==403)
        passed('no_unexpected_uploaded_files',len(list(uploads.iterdir()))==1)
    with app.app_context():
        db.session.remove(); db.engine.dispose()
    report(check='web', result='PASS', checks=checks, isolated_directory=str(work))

def ntrip():
    import bcrypt
    user, password = 'verify_'+secrets.token_hex(4), secrets.token_urlsafe(24)
    with connect(readonly=False) as c:
        mp = c.execute('SELECT name FROM mountpoint WHERE is_active=1 LIMIT 1').fetchone()
        assert mp, 'No active mountpoint'
        mount = mp[0]
        row = c.execute('INSERT INTO rover (username,password,mountpoints,max_conn,active_conn,expires,total_connections,is_active,created_at,updated_at) VALUES (?,?,?,1,0,?,0,1,?,?)',
                        (user,bcrypt.hashpw(password.encode(),bcrypt.gensalt()).decode(),mount,int(time.time())+600,int(time.time()),int(time.time())))
        rid = row.lastrowid
    def open_stream(pw):
        s=socket.create_connection(('127.0.0.1',2101),timeout=10)
        auth=base64.b64encode((user+':'+pw).encode()).decode()
        s.sendall(f'GET /{mount} HTTP/1.0\r\nUser-Agent: NTRIP verification\r\nAuthorization: Basic {auth}\r\n\r\n'.encode())
        data=b''
        while b'\r\n\r\n' not in data and b'\r\n' not in data:
            part=s.recv(4096)
            if not part: break
            data+=part
        return s,data
    sockets=[]
    try:
        s,head=open_stream('incorrect');sockets.append(s)
        assert not head or b'401' in head, 'Unexpected response to invalid credentials'
        s.close()
        s,head=open_stream(password);sockets.append(s)
        assert b'200 OK' in head, 'NTRIP authentication failed'
        extra,rejected=open_stream(password);sockets.append(extra)
        assert not rejected or b'200 OK' not in rejected, 'Connection limit bypassed'
        extra.close()
        with connect() as c:
            assert c.execute('SELECT active_conn FROM rover WHERE id=?',(rid,)).fetchone()[0] == 1, 'Rejected client changed active slot'
        stream=bytearray(head.split(b'\r\n',1)[1])
        types=collections.Counter(); bad=0; total=0
        end=time.monotonic()+20
        while time.monotonic()<end:
            data=s.recv(8192)
            assert data, 'NTRIP closed stream'
            total+=len(data);stream.extend(data)
            while len(stream)>=6:
                if stream[0]!=0xD3: del stream[0];continue
                size=((stream[1]&3)<<8|stream[2])+6
                if len(stream)<size: break
                frame=bytes(stream[:size]);del stream[:size]
                crc=0
                for byte in frame[:-3]:
                    crc ^= byte<<16
                    for _ in range(8):
                        crc <<= 1
                        if crc&0x1000000: crc ^= 0x1864CFB
                if crc != int.from_bytes(frame[-3:],'big'): bad+=1
                else: types[(frame[3]<<4)|(frame[4]>>4)]+=1
        assert sum(types.values())>0 and bad==0, 'Invalid RTCM output'
        s.shutdown(socket.SHUT_RDWR);s.close()
        for _ in range(20):
            with connect() as c: active=c.execute('SELECT active_conn FROM rover WHERE id=?',(rid,)).fetchone()[0]
            if active==0: break
            time.sleep(1)
        assert active==0, 'Rover slot was not released'
        s,head=open_stream(password);sockets.append(s)
        assert b'200 OK' in head, 'Reconnect failed'
        report(check='ntrip',result='PASS',bytes=total,frames=sum(types.values()),types=dict(types),crc_errors=bad,connection_limit=True,slot_released=True,reconnect=True)
    finally:
        for s in sockets: s.close()
        time.sleep(3)
        with connect(readonly=False) as c: c.execute('DELETE FROM rover WHERE id=? AND username=?',(rid,user))

def observe(seconds):
    from flask import Flask
    from flask.sessions import SecureCookieSessionInterface
    app=Flask('verification')
    app.secret_key=next(l.split('=',1)[1].strip() for l in Path('/etc/gnss-caster/secrets/secret.env').read_text().splitlines() if l.startswith('SECRET_KEY='))
    with connect() as c: uid,v=c.execute('SELECT id,session_version FROM admin LIMIT 1').fetchone()
    cookie=SecureCookieSessionInterface().get_signing_serializer(app).dumps({'_user_id':f'{uid}:{v}','_fresh':True})
    end=time.monotonic()+seconds
    while True:
        req=urllib.request.Request('http://127.0.0.1:8080/api/diagnostics',headers={'Cookie':'session='+cookie})
        try:
            with urllib.request.urlopen(req,timeout=8) as r: data=json.load(r)
            import subprocess
            proc=subprocess.run(['systemctl','show','gnss-caster','-p','MainPID','--value'],capture_output=True,text=True,check=True).stdout.strip()
            status=Path('/proc',proc,'status').read_text()
            metrics={l.split(':')[0]:l.split(':',1)[1].strip() for l in status.splitlines() if l.startswith(('VmRSS:','Threads:'))}
            report(check='observe',timestamp=data['timestamp'],status=data['status'],stations=data['stations'],process=metrics)
        except Exception as e: report(check='observe',error=type(e).__name__)
        if time.monotonic()>=end: break
        time.sleep(min(15,max(0,end-time.monotonic())))

if __name__=='__main__':
    os.umask(0o077)
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['backup','web','ntrip','observe']);p.add_argument('--source');p.add_argument('--installer');p.add_argument('--seconds',type=int,default=600)
    args=p.parse_args()
    if args.mode=='backup': backup(args.source)
    elif args.mode=='web': web(args.installer)
    elif args.mode=='ntrip': ntrip()
    else: observe(args.seconds)
