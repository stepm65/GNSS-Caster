# Repository instructions

- Canonical remote: https://github.com/stepm65/GNSS-Caster.git.
- Keep subsequent development in Git branches and pull requests. Preserve unrelated local changes and never force-push shared history.
- The current source of the backend and Linux scripts is the embedded code in `gnss-caster-install.sh`. Web source lives in `frontend/`; build it and run `tools/embed_frontend.py` whenever it changes.
- The release updater is maintained in `runtime/release_update.py`; run `tools/embed_release_updater.py` after changing it. Do not edit its generated installer block directly.
- The root-only recovery journal is maintained in `runtime/recovery.py`; run `tools/embed_recovery.py` after changing it. Keep its generated installer block consistent.
- Maintain English and Russian web translations; keep the Telegram language independent of the browser language. Preserve authentication, roles, CSRF and existing API behavior.
- Run relevant tests and update `CHANGES.md`. Report local/mocked verification separately from hardware verification.
- Publishing code does not authorize deployment, service restarts, Bluetooth scans or monitoring. Only operate a live caster when the current task authorizes it, considering ongoing field work.
- Do not commit credentials, runtime databases, backup archives or private field logs. Do not remove local-only records to tidy the checkout.
- Preserve the existing proprietary license; do not relicense the project without an explicit request.
