# Maintenance privilege boundary — 3.4.0

The web service, Bluetooth manager and Telegram handlers run as `gnss-caster`. They request fixed maintenance actions over a local Unix socket instead of invoking sudo. HTTP authentication, roles, CSRF, administrator confirmation and the field-work policy remain in place.

## Service boundary

`gnss-caster-maintenance.socket` is owned by root, mode `0660`, group `gnss-caster`, in a root-owned `0755` directory. It accepts at most eight concurrent connections. systemd starts one `gnss-caster-maintenance@.service` instance for each accepted connection and passes the connected socket as standard input. No network listener is added.

The service executes `/usr/bin/python3 -I /opt/gnss-caster/maintenance-broker.py` as root. The broker uses only the standard library, a fixed root-owned helper, a fixed environment and `/` as its working directory. It never imports the web application. Files must be regular, root-owned, not group/other writable and not hard-linked; their parent must also be root-owned and not group/other writable.

The broker verifies the sender UID/PID using Linux `SO_PEERCRED`: only root and the configured `gnss-caster` account may send requests. Membership of the socket group alone does not pass this check. The client verifies the root-owned socket and root peer. The protocol accepts exactly `version` and an argument list, rejects duplicate fields and unknown arguments, and processes one request per connection. No executable, shell text, environment or working directory can be supplied.

The main service, including its compatibility fallback, uses `NoNewPrivileges=yes`. The installer removes only its own `/etc/sudoers.d/gnss-caster` rule. There is no sudo fallback if the socket is unavailable. See the systemd documentation for [socket activation](https://www.freedesktop.org/software/systemd/man/latest/systemd.socket.html) and [execution restrictions](https://www.freedesktop.org/software/systemd/man/latest/systemd.exec.html). `NoNewPrivileges` restricts privilege gains through execution; it does not revoke the ability to request actions from another service.

## Allowed requests

| Area | Allowed operation and constraints |
| --- | --- |
| Availability | Protocol ping; status of seven named services; start Bluetooth only |
| Bluetooth | Unblock, RFCOMM bind/release on channels 1–30, RSSI for a MAC, existing controller recovery procedures |
| Time | Set a valid timestamp with the existing clock policy |
| Releases | Check/status; install a stable numeric tag with its expected SHA-256, subject to the release helper's verification |
| Backups | Start the fixed backup script; restore a validated backup filename, optionally with a fixed-format protected key-file path |
| Configuration | Log retention 1–3650 days; enable/disable backup schedule with interval 3600–604800 seconds |
| Certificates | Inspect the fixed local certificate or constrained Let's Encrypt paths; invoke the fixed renewal procedure |
| Service/host | Delayed caster restart, reboot or shutdown; existing maintenance/admission locks and field-work checks apply |

The root helper retains its own validation. The broker additionally enforces exact argument counts, operation-specific unit names and bounds. A restore request is rewritten to an internal data-only action; clients cannot request the internal action directly or select full code restoration. Delayed host power actions check maintenance eligibility when scheduled and again before execution.

Requests are limited to 8 KiB and five seconds to arrive. Commands have fixed limits, normally 5–120 seconds, with 1800 seconds for certificate renewal. Helper output above 128 KiB fails the request; the process group is terminated on timeout or excess output. The systemd worker has a 128 MiB memory limit, 32 tasks and a final 1815-second limit. Responses are bounded by the client as well. These limits do not make the helper's temporary-file output a hard disk quota.

The client never retries automatically after losing a reply. A detached job may already have been accepted: inspect its existing status before requesting the operation again. A successful broker result for a scheduled task means it was accepted, not that a subsequent update, restore or restart completed.

## Protected audit

`/var/log/gnss-caster-maintenance/` is root-only (`0700`). `actions.jsonl` and its lock are created with `0600`. The journal records a request ID, verified UID/PID, validated action/arguments and the helper exit status. A mutation must have a durable `accepted` record before execution; inability to create it prevents the action. A failure to record the result reports an incomplete outcome, even if the action ran.

Writes use a lock, no-follow opens and file/directory synchronization. Rotation retains the current file and three previous files, rotating at 1 MiB. This is a bounded local diagnostic history, not immutable remote evidence. Root can change it; a filesystem failure can prevent the final record. Successful routine status/RSSI/ping queries do not create audit entries. Rejected requests are recorded without raw unvalidated payloads. Local root helper calls record their action before execution; they do not provide the same complete request/result pairing as broker calls.

Tokens, passwords, passphrase contents and helper output are not stored in this audit. Restore arguments include the key file's name, not its contents. Ordinary application logs remain service-writable and must not be treated as protected audit evidence. Their directory is now root-owned `0750`, allowing writes to existing log files without granting permission to replace them. Uninstall preserves the protected journal.

## Data restoration and trusted code

From 3.4.0, restoration requested through the application installs the archived database and YAML settings while keeping the installed application and `config.py`. Archives are still unpacked and checked using the existing archive restrictions and checksums; application files in an archive are not executed or installed by this path. The confirmation explains this in English and Russian.

Pre-restore rollback snapshots are stored below root-only `/var/backups/gnss-caster/restore-*`. This avoids placing executable rollback material in the service-writable backup directory. Release changes use the existing verified release updater. A root administrator can still use the local legacy full-restore command, which trusts the archive's code and requires independent compatibility judgment; it is not exposed through the socket.

This change does **not** yet provide a schema/version compatibility manifest, a preview of every restored setting, or an authenticated archive format. Old data may be incompatible with a newer application. The existing validation and rollback help detect failures but cannot prove semantic compatibility. R08, R10 and R12 track those remaining changes.

## Installation and recovery

The installer includes the broker, client and units. Their source is in `runtime/maintenance_broker.py`, `runtime/maintenance_client.py` and `tools/embed_maintenance.py`; run the generator after edits. CI checks that the embedded files match.

Installation/repair snapshots include the broker, units, old sudo rule, application client and original socket state. The health gate pings the service from the actual service account. Rollback stops the new listening socket, restores files and the previous service state. Socket activation starts on caster startup; no separate manual enable step is needed. An upgrade from an older version requires a planned window without field work.

For an authorized Linux maintenance window, verify installation and rollback first on a disposable machine: socket activation, ownership and permissions, a ping from the service UID, rejection of another UID, audit persistence/rotation, behavior with a full audit filesystem, and absence of the managed sudo rule. Then exercise backup/data restore and both restart eligibility checks with simulated rover sessions. Test normal Bluetooth connection/recovery and updates on the target hardware only in a separately authorized window.

Local and CI tests use temporary sockets, files and processes, mocked service calls and systemd unit validation without starting real units. They do not establish that physical Bluetooth recovery works or that a power interruption on Raspberry Pi is recoverable in every case.

## Remaining threat boundary

A compromised web process can still request the allowed actions, access its database/settings and use the pre-existing BlueZ policy. Broker peer identity is an OS account, not a verified web administrator. The protected log therefore records OS identity, not proof of which human approved an operation. The improvement is explicit root-side validation, a separate execution boundary, protected audit and exclusion of archive code from web restoration. It does not make every allowed operation harmless or replace the remaining security work in the roadmap.
