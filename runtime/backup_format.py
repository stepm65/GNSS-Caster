"""Backup metadata and conservative data-restore compatibility. Stdlib only.

Never imports archived or installed application code. CLI inspection is isolated
from Flask and bounded on Linux; hashes are integrity checks, not signatures.
"""
import argparse
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import sqlite3
import stat
import subprocess
import sys
import tarfile
import tempfile
import time

FORMAT = 'gnss-caster-backup'
FORMAT_VERSION = 2
DATA_CONTRACT = 1
MIN_RESTORE = '3.4.1'
SCHEMA_VERSION = 8
MAX_ARCHIVE = 256 * 1024 ** 2
MAX_EXPANDED = 2 * 1024 ** 3
FILES = {'db.sqlite', 'config.yaml', 'config.py', 'app.tar.gz'}
PAYLOAD = FILES | {'manifest.txt', 'manifest.json'}
LABELS = {'db.sqlite': 'Database', 'config.yaml': 'Config',
          'config.py': 'Python Config', 'app.tar.gz': 'App Archive'}


class BackupError(ValueError):
    pass


def version(value):
    if not isinstance(value, str) or not re.fullmatch(r'[0-9]{1,5}\.[0-9]{1,5}\.[0-9]{1,5}', value):
        raise BackupError('Backup version is invalid')
    return tuple(map(int, value.split('.')))


def installed_version(path):
    match = re.search(r'^__version__ = [\'"]([0-9.]+)[\'"]$', Path(path).read_text(encoding='utf-8'), re.M)
    if not match:
        raise BackupError('Installed version could not be read')
    version(match[1])
    return match[1]


def regular_file(path):
    info = Path(path).lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise BackupError('Backup component must be a regular file without links')
    return info


def digest(path):
    regular_file(path)
    result = hashlib.sha256()
    with open(path, 'rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def safe_extract(archive_path, destination, kind):
    if kind not in ('backup', 'app'):
        raise BackupError('Unknown archive kind')
    destination = Path(destination)
    if destination.exists():
        raise BackupError('Extraction destination must not exist')
    deadline = time.monotonic() + 120
    with tarfile.open(archive_path, 'r:gz') as archive:
        entries, names, roots = [], set(), set()
        total_size = 0
        for member in archive:
            raw = member.name
            if not raw or len(raw) > 512 or raw.startswith('/') or '\\' in raw or any(ord(c) < 32 for c in raw):
                raise BackupError('Unsafe archive path')
            if '..' in raw.split('/'):
                raise BackupError('Parent traversal in archive')
            parts = PurePosixPath(raw).parts
            normalized = str(PurePosixPath(raw))
            if not parts or normalized in names:
                raise BackupError('Empty or duplicate archive path')
            if not (member.isdir() or member.isreg()) or member.issparse():
                raise BackupError('Only regular files and directories may be restored')
            if kind == 'app':
                if parts[0] != 'app' or (len(parts) == 1 and not member.isdir()):
                    raise BackupError('Application archive must contain only app/')
            else:
                if not parts[0].startswith('backup_'):
                    raise BackupError('Unexpected backup root')
                if len(parts) == 1:
                    if not member.isdir():
                        raise BackupError('Backup root must be a directory')
                elif len(parts) != 2 or parts[1] not in PAYLOAD or not member.isreg():
                    raise BackupError('Unexpected backup component')
                if len(parts) == 2 and parts[1] in ('manifest.json', 'manifest.txt') and member.size > 65536:
                    raise BackupError('Backup manifest is too large')
                if len(parts) == 2 and parts[1] in ('config.yaml', 'config.py') and member.size > 1024 * 1024:
                    raise BackupError('Backup configuration is too large')
            roots.add(parts[0]); names.add(normalized)
            total_size += member.size
            if member.size < 0 or total_size > MAX_EXPANDED or len(entries) >= 100000 or time.monotonic() > deadline:
                raise BackupError('Archive exceeds restore size or file-count limit')
            entries.append((member, parts))
        if len(roots) != 1:
            raise BackupError('Archive must contain exactly one root directory')
        file_names = {str(PurePosixPath(*parts)) for member, parts in entries if member.isreg()}
        for _, parts in entries:
            if any(str(PurePosixPath(*parts[:i])) in file_names for i in range(1, len(parts))):
                raise BackupError('File used as an archive directory')
        if kind == 'backup' and next(iter(roots)) + '/app.tar.gz' not in file_names:
            raise BackupError('Backup is missing app.tar.gz')
        if shutil.disk_usage(destination.parent).free < total_size + 64 * 1024 ** 2:
            raise BackupError('Not enough free space to inspect the backup')
        destination.mkdir(mode=0o700)
        for member, parts in entries:
            target = destination.joinpath(*parts)
            if member.isdir():
                target.mkdir(mode=0o700, parents=True, exist_ok=True)
            else:
                target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                with archive.extractfile(member) as source, target.open('xb') as output:
                    os.chmod(target, 0o600)
                    while block := source.read(65536):
                        if time.monotonic() > deadline:
                            raise BackupError('Backup inspection timed out')
                        output.write(block)


def database_info(path, *, check=True):
    regular_file(path)
    uri = Path(path).resolve().as_uri() + '?mode=ro'
    with closing(sqlite3.connect(uri, uri=True, timeout=5)) as db:
        db.execute('PRAGMA query_only=ON')
        db.execute('PRAGMA trusted_schema=OFF')
        deadline = time.monotonic() + 30
        db.set_progress_handler(lambda: int(time.monotonic() > deadline), 10000)
        db.execute('BEGIN')
        objects = db.execute("SELECT type,name,tbl_name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name").fetchall()
        if len(objects) > 256 or any(row[0] not in ('table', 'index') or 'VIRTUAL TABLE' in str(row[3]).upper() for row in objects):
            raise BackupError('Backup database contains unsupported schema objects')
        tables = {}
        quote = lambda name: '"' + name.replace('"', '""') + '"'
        for kind, name, _, definition in objects:
            if kind != 'table':
                continue
            if not re.fullmatch(r'[a-z_][a-z_0-9]{0,127}', name):
                raise BackupError('Backup database contains unsupported table names')
            columns = db.execute('PRAGMA table_xinfo(' + quote(name) + ')').fetchall()
            indexes = []
            for index in db.execute('PRAGMA index_list(' + quote(name) + ')'):
                # Include implicit UNIQUE/PK indexes as well as named indexes.
                indexes.append([index[2], index[3], index[4],
                                db.execute('PRAGMA index_xinfo(' + quote(index[1]) + ')').fetchall()])
            tables[name] = {'definition': definition.strip(),
                            'columns': sorted([list(row[1:]) for row in columns]),
                            'indexes': sorted(indexes, key=lambda item: json.dumps(item)),
                            'foreign_keys': sorted(db.execute('PRAGMA foreign_key_list(' + quote(name) + ')').fetchall())}
        if not {'admin', 'base_station', 'rover', 'system_setting'} <= tables.keys():
            raise BackupError('Backup database is missing required tables')
        if check and db.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
            raise BackupError('Backup database integrity check failed')
        migrations = []
        if 'schema_migration' in tables:
            migrations = [row[0] for row in db.execute('SELECT version FROM schema_migration ORDER BY version LIMIT 100')]
        if migrations and (any(type(v) is not int or not 1 <= v <= 100 for v in migrations) or migrations != list(range(1, max(migrations) + 1))):
            raise BackupError('Backup migration history is invalid')
        shape = {'tables': tables, 'indexes': [(row[1], row[2], str(row[3]).strip()) for row in objects if row[0] == 'index']}
        schema_hash = hashlib.sha256(json.dumps(shape, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        counts = {name: db.execute('SELECT COUNT(*) FROM ' + quote(name)).fetchone()[0]
                  for name in ('admin', 'base_station', 'rover', 'mount_point', 'site_point', 'system_setting') if name in tables}
        return {'migration': max(migrations, default=0), 'schema_sha256': schema_hash, 'counts': counts}


def unique_json(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise BackupError('Backup manifest has duplicate fields')
        result[key] = value
    return result


def create_manifest(payload, app_version):
    payload = Path(payload)
    version(app_version)
    if not {'db.sqlite', 'config.yaml', 'app.tar.gz'} <= {p.name for p in payload.iterdir()}:
        raise BackupError('Backup is missing required components')
    info = database_info(payload / 'db.sqlite')
    if info['migration'] != SCHEMA_VERSION:
        raise BackupError('Database schema is not supported by this backup version')
    components = {name: {'size_bytes': regular_file(payload / name).st_size, 'sha256': digest(payload / name)}
                  for name in sorted(FILES) if (payload / name).exists()}
    manifest = {'format': FORMAT, 'format_version': FORMAT_VERSION, 'created_at': int(time.time()),
                'application_version': app_version,
                'restore': {'mode': 'data-only', 'data_contract': DATA_CONTRACT, 'minimum_version': MIN_RESTORE},
                'database': {k: info[k] for k in ('migration', 'schema_sha256')}, 'components': components}
    with (payload / 'manifest.json').open('x', encoding='utf-8') as output:
        json.dump(manifest, output, indent=2, sort_keys=True)
        output.flush(); os.fsync(output.fileno())
    return manifest


def inspect_payload(payload, target_database, app_version):
    payload = Path(payload)
    version(app_version)
    components = {name: {'size_bytes': regular_file(payload / name).st_size, 'sha256': digest(payload / name)}
                  for name in sorted(FILES) if (payload / name).exists()}
    if not {'db.sqlite', 'config.yaml', 'app.tar.gz'} <= components.keys():
        raise BackupError('Backup is missing required components')
    archived = database_info(payload / 'db.sqlite')
    current = database_info(target_database, check=False)
    warnings, reasons = [], []
    source_version, created_at = None, None
    legacy = not (payload / 'manifest.json').exists()
    if legacy:
        warnings.append('Legacy backup: application version and data contract are not recorded.')
        manifest = payload / 'manifest.txt'
        if not manifest.exists() or regular_file(manifest).st_size > 65536:
            raise BackupError('Backup manifest is missing or too large')
        text = manifest.read_text(encoding='utf-8')
        for name, item in components.items():
            expected = re.findall(r'^- ' + re.escape(LABELS[name]) + r' SHA256: ([0-9a-f]{64})$', text, re.M)
            if not expected and name in ('config.yaml', 'config.py'):
                warnings.append('Legacy settings have no checksum; their original integrity cannot be confirmed.')
                continue
            if len(expected) != 1 or expected[0] != item['sha256']:
                raise BackupError('Backup component checksum does not match')
    else:
        path = payload / 'manifest.json'
        if regular_file(path).st_size > 65536:
            raise BackupError('Backup manifest is too large')
        metadata = json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=unique_json)
        if not isinstance(metadata, dict) or metadata.get('format') != FORMAT or type(metadata.get('format_version')) is not int or metadata['format_version'] != FORMAT_VERSION:
            raise BackupError('Backup format version is not supported')
        source_version = metadata.get('application_version')
        source = version(source_version)
        policy = metadata.get('restore')
        if not isinstance(policy, dict) or policy.get('mode') != 'data-only' or type(policy.get('data_contract')) is not int or policy['data_contract'] != DATA_CONTRACT:
            reasons.append('This backup uses an unsupported data contract.')
        else:
            if version(policy.get('minimum_version')) > version(app_version):
                reasons.append('This backup requires a newer application version.')
        if source > version(app_version):
            reasons.append('This backup was created by a newer application version.')
        if metadata.get('components') != components:
            raise BackupError('Backup component sizes or checksums do not match')
        if metadata.get('database') != {k: archived[k] for k in ('migration', 'schema_sha256')}:
            raise BackupError('Backup schema does not match its manifest')
        created_at = metadata.get('created_at')
        if type(created_at) is not int or not 0 < created_at < 32503680000:
            raise BackupError('Backup creation time is invalid')
    if archived['migration'] != SCHEMA_VERSION or current['migration'] != SCHEMA_VERSION:
        reasons.append('The database schema needs a separate migration before restoration.')
    if archived['schema_sha256'] != current['schema_sha256']:
        reasons.append('The backup database structure differs from this installation.')
    # The installed Python configuration is retained; do not silently restore a
    # YAML file that points it at some other database.
    config = (payload / 'config.yaml').read_text(encoding='utf-8')
    paths = re.findall(r'^\s+path:\s*[\'\"]?([^\s\'\"#]+)[\'\"]?\s*(?:#.*)?$', config, re.M)
    if paths != ['/opt/gnss-caster/instance/db.sqlite']:
        reasons.append('The backup uses an unsupported database location.')
    return {'compatible': not reasons, 'legacy': legacy, 'format_version': 1 if legacy else FORMAT_VERSION,
            'source_version': source_version, 'installed_version': app_version, 'created_at': created_at,
            'schema_version': archived['migration'], 'installed_schema_version': current['migration'],
            'components': [{'name': name, 'size_bytes': item['size_bytes'],
                            'restored': name in ('db.sqlite', 'config.yaml')} for name, item in components.items()],
            'counts': archived['counts'], 'warnings': list(dict.fromkeys(warnings)), 'reasons': reasons,
            'restoration_mode': 'data-only'}


def freeze_archive(path, destination):
    path = Path(path)
    info = regular_file(path)
    if not 0 < info.st_size <= MAX_ARCHIVE:
        raise BackupError('Backup exceeds the 256 MiB inspection limit')
    if shutil.disk_usage(Path(destination).parent).free < info.st_size * 2 + 64 * 1024 ** 2:
        raise BackupError('Not enough free space to inspect the backup')
    checksum, total = hashlib.sha256(), 0
    descriptor = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0))
    with os.fdopen(descriptor, 'rb') as source, open(destination, 'xb') as output:
        if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
            raise BackupError('Backup must be a regular file')
        while block := source.read(65536):
            total += len(block)
            if total > MAX_ARCHIVE:
                raise BackupError('Backup exceeds the 256 MiB inspection limit')
            checksum.update(block); output.write(block)
    return checksum.hexdigest()


def preview_archive(path, target_database, app_version, passphrase=''):
    path = Path(path)
    with tempfile.TemporaryDirectory(prefix='gnss-backup-preview-') as folder:
        root = Path(folder)
        frozen = root / 'input.archive'
        checksum = freeze_archive(path, frozen)
        archive = frozen
        if str(path).endswith('.enc'):
            if not passphrase:
                raise BackupError('Encrypted backup requires its passphrase for verification')
            if '\n' in passphrase or '\r' in passphrase or len(passphrase.encode()) > 4096:
                raise BackupError('Backup passphrase is invalid')
            archive = root / 'decrypted.tar.gz'
            result = subprocess.run(['openssl', 'enc', '-d', '-aes-256-cbc', '-pbkdf2', '-iter', '200000',
                                     '-in', str(frozen), '-out', str(archive), '-pass', 'stdin'],
                                    input=passphrase + '\n', capture_output=True, text=True, timeout=120)
            if result.returncode:
                raise BackupError('Encrypted backup could not be decrypted with the supplied/current passphrase')
        safe_extract(archive, root / 'payload', 'backup')
        payload = next((root / 'payload').iterdir())
        safe_extract(payload / 'app.tar.gz', root / 'application', 'app')
        result = inspect_payload(payload, target_database, app_version)
        result['archive_sha256'] = checksum
        return result


def main():
    if sys.platform.startswith('linux'):
        import resource
        resource.setrlimit(resource.RLIMIT_AS, (384 * 1024 ** 2, 384 * 1024 ** 2))
        resource.setrlimit(resource.RLIMIT_CPU, (180, 190))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('manifest', 'preview', 'validate', 'extract', 'freeze'))
    parser.add_argument('path')
    parser.add_argument('target')
    parser.add_argument('version_file', nargs='?')
    args = parser.parse_args()
    try:
        if args.action == 'freeze':
            print(freeze_archive(args.path, args.target))
            return
        if args.action == 'extract':
            safe_extract(args.path, args.target, args.version_file)
            return
        app_version = installed_version(args.target if args.action == 'manifest' else args.version_file)
        if args.action == 'manifest':
            result = create_manifest(args.path, app_version)
        elif args.action == 'preview':
            secret = sys.stdin.read(4097)
            if len(secret) > 4096:
                raise BackupError('Backup passphrase is invalid')
            result = preview_archive(args.path, args.target, app_version, secret)
        else:
            result = inspect_payload(args.path, args.target, app_version)
        print(json.dumps(result))
        if args.action == 'validate' and not result['compatible']:
            raise SystemExit(2)
    except (BackupError, OSError, ValueError, sqlite3.Error, tarfile.TarError, subprocess.TimeoutExpired, MemoryError) as exc:
        message = str(exc) if isinstance(exc, BackupError) else 'Backup inspection failed; the archive was not applied'
        print(json.dumps({'error': message}))
        raise SystemExit(1)


if __name__ == '__main__':
    main()
