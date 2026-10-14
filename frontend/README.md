# GNSS Caster web interface

English/Russian React 19 + Material UI 7 cabinet, served by the existing Flask app.
Production assets are embedded in `gnss-caster-install.sh`. Raspberry Pi
does not need Node.js, pnpm, a build step, or access to a CDN.

## Build and package

Use Node.js 22.12+ and pnpm 11.25.0. The checked-in `pnpm-lock.yaml` pins the
complete dependency tree. Only esbuild's installation script is enabled.

```text
cd frontend
pnpm install --frozen-lockfile
pnpm run build
cd ..
python tools/embed_frontend.py
```

The embed tool replaces the generated asset block and Jinja templates in the
installer. Always run it after rebuilding. Do not edit the embedded minified
assets. Asset SHA256 hashes and an entry-point manifest are installed with the
bundle. Both a full installation and `--repair` install the same bundle inside
the existing runtime transaction.

Frontend source lives in `src/`; authentication, authorization, persistence and
receiver operations remain in the Flask APIs. Page URLs are unchanged; server
navigation preserves direct links and Flask login checks. `/diagnostics` and
`/backups` are the two added authenticated pages.

## Preview and test

```text
cd frontend
pnpm run preview
pnpm test
pnpm run test:browser
```

Preview: `http://127.0.0.1:5173/dashboard`. This is a local-only server using
sample data. It never forwards requests to the Raspberry Pi and rejects writes.
The page displays a preview banner. Browser tests use explicit mocked responses
for write operations. The default test browser is installed Microsoft Edge.
Set `PLAYWRIGHT_CHANNEL=chromium` and run `pnpm exec playwright install chromium`
to use Chromium instead, as in GitHub Actions.

Installer/Jinja integration tests require the same Jinja version as production:

```text
python -m pip install Jinja2==3.1.6
python -m unittest discover -s tests -p test_frontend_bundle.py
```

## Languages

The header and sign-in screens provide a language selector. The browser stores
only the language preference in `gnss_language`; English is the default.
Switching language updates labels and Material UI controls without discarding
form drafts. Date and number formatting uses the selected locale.

English UI messages are the keys in `src/locales/ru.json`; use `t()` from
`src/i18n.js` and numbered placeholders for dynamic messages. Interpolate user
values after translation. Do not translate station names, passwords, command
identifiers or raw receiver output. Translation tests verify explicit keys and
matching placeholders. Browser tests cover both languages and independent bot
language saving.

The administrator's **Notifications → Telegram bot language** setting persists
as `telegram_language` on the server. It controls replies, buttons, notifications
and backup captions independently of each browser's language. Existing databases
default to `en`; changing to `ru` requires no service restart.

## Pages and operations

| Page | Functions |
| --- | --- |
| Overview | Fresh correction availability, receiver count, active rover sessions, host load |
| Base stations | Add/edit/delete, bulk delete, Bluetooth discovery/pair/connect/disconnect/test, serial-port selection |
| Station detail | Telemetry, receiver configuration, generated command preview, shared-buffer console, manual commands, CSV command history, configuration versions, position history and saved site points |
| Rovers | Accounts, passwords, mountpoint access, expiry, connection limits |
| Mountpoints | Streams, base assignment, activation and RTCM overrides |
| RTCM messages | Message/group selection, explicit save, presets and defaults |
| Diagnostics | Component health, last valid frames, CRC failures, connection recovery, host details and readiness |
| Logs | Filters, message search and CSV export |
| Backups | Create, upload with progress/cancel, verify, download, restore, delete, storage health and job status |
| System settings | Names, connections, retention, backup/encryption policy, Telegram, certificates, reboot/shutdown |
| Account & access | Passwords, 2FA, recovery codes, roles, administrator password reset, API tokens |
| Sign in / 2FA | Existing native POST forms, CSRF fields, server lockout and authenticator logic |

Destructive actions use confirmation dialogs. Restore and host power require
typing a confirmation word. Uploading an archive never starts restoration.
Blank secret fields preserve existing credentials. Secrets are not written to
browser storage. Polling is bounded by request timeouts, pauses in hidden tabs,
stops after session expiry and is cancelled when a page component unmounts.

## Deployment boundary

This release is prepared locally. Local tests do not validate actual BlueZ,
receiver commands, nginx upload limits, systemd jobs or field NTRIP traffic.
Deploy only outside field work, with a current backup and an available rollback.
After deployment verify login/2FA, role permissions, each page and a backup
upload/verification through nginx before scheduling a real restore drill.

Library references: [Material UI installation](https://mui.com/material-ui/getting-started/installation/),
[Vite production builds](https://vite.dev/guide/build).
