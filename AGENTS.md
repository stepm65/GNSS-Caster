# Repository instructions

- Canonical remote: https://github.com/stepm65/GNSS-Caster.git.
- Keep subsequent development in Git branches and pull requests. Preserve unrelated local changes and never force-push shared history.
- The current source of the backend and Linux scripts is the embedded code in `gnss-caster-install-3.0.1.sh`. Web source lives in `frontend/`; build it and run `tools/embed_frontend.py` whenever it changes.
- Keep the web interface in English. Preserve authentication, roles, CSRF and existing API behavior.
- Run relevant tests and update `CHANGES.md`. Report local/mocked verification separately from hardware verification.
- Publishing code does not authorize deployment, service restarts, Bluetooth scans or monitoring. Only operate a live caster when the current task authorizes it, considering ongoing field work.
- Do not commit credentials, runtime databases, backup archives or private field logs. Do not remove local-only records to tidy the checkout.
- Preserve the existing proprietary license; do not relicense the project without an explicit request.
