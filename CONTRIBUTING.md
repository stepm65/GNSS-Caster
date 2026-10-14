# Development workflow

The canonical repository is https://github.com/stepm65/GNSS-Caster.

1. Start from an up-to-date `main` and create a branch for the change.
2. Edit source files. The Python runtime is embedded in `gnss-caster-install.sh`; web source is in `frontend/src/` and `frontend/templates/`.
3. If the web source changes, run the locked frontend build and `python tools/embed_frontend.py`. Commit both the source and the updated installer.
4. Run checks appropriate to the change, update `CHANGES.md` and describe behavior, verification and remaining limitations in a pull request.
5. Merge after review and passing checks. Deploy to operating equipment separately, with an appropriate maintenance window and backup.

Use English in the interface. Preserve existing routes, API contracts, role checks and CSRF protection unless a change explicitly requires otherwise. Hardware recovery, installation and restore operations need particular care because they can interrupt correction delivery.

Do not commit SSH credentials, environment files, access tokens, databases, receiver backups, live configuration or private operating logs. Local field records are intentionally ignored. Test data and screenshots must use non-sensitive sample values.

## Tests

```sh
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tests -v
bash -n gnss-caster-install.sh
cd frontend
pnpm install --frozen-lockfile
pnpm run build
pnpm test
pnpm run test:browser
```

The default local test browser is Microsoft Edge. For Chromium, install it with `pnpm exec playwright install chromium` and set `PLAYWRIGHT_CHANNEL=chromium`. GitHub Actions uses Chromium on Linux. The local preview uses only sample data and mock write responses.

Dependency versions are locked. Update the lockfiles deliberately and preserve applicable third-party license notices. The production Python lock lives inside the installer; see `DEPENDENCIES.md`.

Known limitations and the remaining hardware checks are in `validation/ui/REPORT.md` and `REPAIR_TEST_PLAN.md`.
