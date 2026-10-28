# Backup compatibility and restoration

Source version 3.4.1 adds an administrator-only inspection before web restoration. Upload a `.tar.gz` or `.tar.gz.enc` file under **Backups & restore**, or select an existing copy. Encrypted copies need the passphrase used when they were created; leaving it blank uses the currently stored passphrase.

Inspection displays the recorded application version and creation date, database schema, component sizes, and counts of accounts, bases, rovers, mountpoints, site points and saved settings where present. It does not show passwords or setting values. The dialog explains which components change. A compatible archive requires the literal confirmation word `RESTORE`; legacy copies also require acknowledgement of their limitations. Inspection itself does not stop the caster or replace production files.

## What restoration changes

| Component | Web restoration |
| --- | --- |
| `db.sqlite` | Replaces accounts, password hashes, receivers, rovers, history and saved settings with the backup state |
| `config.yaml` | Restores the archived server configuration |
| `config.py` | Keeps the installed Python configuration |
| `app.tar.gz` | Keeps the installed application; archived code is never imported or installed by this path |

Restoration stops correction streams and restarts the service. Finish field work first. Accounts and access settings return to the backup date, so current sessions may end and older login credentials may be needed. Existing maintenance locks, rover checks, rollback snapshot and health checks still apply. Inspection is not a substitute for a tested recovery procedure on the target operating system.

## Format and compatibility policy

New backups include `manifest.json` with format `gnss-caster-backup`, format version **2**, creation time as Unix seconds, application version, data contract **1**, minimum restore version **3.4.1**, schema migration **8**, a schema fingerprint, and the size/SHA-256 of every data/code component. `manifest.txt` is retained for existing local tooling.

The validator checks actual SQLite integrity and schema, not just manifest claims. It compares table definitions, columns, constraints/indexes and foreign keys with the current installation. Both databases must have the supported contiguous migration history. The configured database path must remain `/opt/gnss-caster/instance/db.sqlite`. Newer application versions, unsupported contracts, altered component hashes, unsupported database objects and differing schemas cannot be applied through the web.

This is deliberately conservative: equivalent schemas with different SQL definitions may be rejected. Automatic conversion between schemas, compatibility adapters and a migration matrix are separate R12 work. Updating the schema requires explicitly updating the backup contract and its tests; changing only a recorded version is insufficient.

Older archives without JSON remain inspectable through `manifest.txt`. Database and application checksums are mandatory. Missing checksums for legacy configuration files produce a warning; the original integrity of those files cannot be confirmed. No application version, contract or trustworthy creation date is inferred from the filename. Legacy copies still need the same actual schema as the current installation. Very old or otherwise different schemas need a separate migration procedure and are blocked.

The local root-only full-restore command retains the older checksum policy and can replace application code. It is not exposed through the maintenance socket and does not receive the web data-compatibility guarantee. It requires independent administrator judgment about the archive and installed version.

## Validation and limits

The server inspects a private frozen copy in a separate process. Archive extraction accepts only regular files/directories, fixed backup components and one root; it rejects links, traversal, duplicate paths, sparse files and files used as directories. Archived Python is treated as bytes. SQLite is read-only with trusted schema disabled. Configuration and metadata sizes are bounded.

- Web upload: 128 MiB; inspection/frozen input: 256 MiB.
- Each outer/application archive: at most 2 GiB expanded and 100,000 entries; temporary space is checked before extraction. These are per-layer limits, not a hard filesystem quota.
- Manifest: 64 KiB; each configuration file: 1 MiB.
- Linux inspection process: 384 MiB address space, 180-second CPU limit with a 190-second hard limit. Archive and SQLite operations have additional deadlines; web inspection has a 240-second overall process deadline and at most two concurrent inspectors per web process. Dedicated nginx locations allow up to 300 seconds for preview/restore/verification; ordinary API timeouts are unchanged.

The browser sends the inspected archive SHA-256 with confirmation. The server re-inspects and rejects changes, then always passes its verified digest to the root job. The root job freezes and hashes the original encrypted/plain file again, validates compatibility under the maintenance lock, and only then enters the service-stop path. Existing API clients without the optional browser digest still receive server/root validation. The existing `/verify` API remains a readability check; `/preview` is the administrator-only compatibility API. Authentication, roles and CSRF remain enforced.

SHA-256 detects changes but does not authenticate the creator: an attacker can edit the data and recompute an unsigned manifest. Restore only trusted copies. Existing AES-CBC/PBKDF2 encryption remains supported; authenticated encryption and key handling improvements are separate R10 work. Neither preview nor an archive checksum proves semantic correctness of receiver settings.

## Development and verification

The shared validator lives in `runtime/backup_format.py`. Run `python tools/embed_backup_format.py` after edits and commit the generated installer together with the module. Root scripts use a root-owned copy; the web uses a separately installed readable copy. Both copies are included in installer rollback. CI checks source/embedded consistency.

Tests use temporary SQLite databases and plain/encrypted archives, actual parser/CLI calls, isolated shell gates, mocked web requests and browser fixtures. They check incompatible versions/schemas, tampering, legacy limitations, mandatory root validation, confirmation and changed-file rejection. They do not establish operational recovery on Raspberry Pi, physical Bluetooth behavior or resilience to a power failure. Deployment and hardware validation require a separate maintenance window.
