import React, { useEffect, useRef, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Checkbox,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControlLabel,
  LinearProgress,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import { api } from "../api";
import { t } from "../i18n";
import { bytes, date, KeyValues } from "../components";

const names = {
  "db.sqlite": "Accounts, receivers, rovers and history",
  "config.yaml": "Server settings",
  "config.py": "Program startup settings",
  "app.tar.gz": "Application code",
};
const countNames = {
  admin: "Accounts",
  base_station: "Base stations",
  rover: "Rovers",
  mount_point: "Mountpoints",
  site_point: "Site points",
  system_setting: "Saved settings",
};

export default function RestoreBackup({ filename, onClose, onStarted }) {
  const [passphrase, setPassphrase] = useState("");
  const [preview, setPreview] = useState(null);
  const [typed, setTyped] = useState("");
  const [acknowledged, setAcknowledged] = useState(false);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const request = useRef(null);
  const encrypted = filename.endsWith(".enc");

  async function inspect(secret = passphrase) {
    request.current?.abort();
    const controller = new AbortController();
    request.current = controller;
    setBusy("preview");
    setError("");
    setPreview(null);
    setTyped("");
    setAcknowledged(false);
    try {
      const result = await api("/api/system/backups/preview", {
        method: "POST",
        body: { filename, passphrase: secret },
        signal: controller.signal,
        timeout: 260000,
      });
      if (!controller.signal.aborted) setPreview(result);
    } catch (e) {
      if (!controller.signal.aborted) setError(e.message);
    } finally {
      if (!controller.signal.aborted) setBusy("");
    }
  }
  useEffect(() => {
    if (!encrypted) inspect("");
    return () => request.current?.abort();
  }, [filename]);

  async function restore() {
    setBusy("restore");
    setError("");
    try {
      const result = await api("/api/system/backups/restore", {
        method: "POST",
        body: { filename, passphrase, archive_sha256: preview.archive_sha256 },
        timeout: 310000,
      });
      onStarted(result);
      onClose();
    } catch (e) {
      setError(e.message);
      // A fresh inspection is required after any uncertain or refused attempt.
      setPreview(null);
      setTyped("");
      setAcknowledged(false);
    } finally {
      setBusy("");
    }
  }
  const close = () => {
    if (busy !== "restore") {
      request.current?.abort();
      onClose();
    }
  };
  return (
    <Dialog
      open
      onClose={close}
      fullWidth
      maxWidth="sm"
      aria-labelledby="restore-title"
    >
      <DialogTitle id="restore-title">
        {t("Review backup restoration")}
      </DialogTitle>
      <DialogContent>
        <Stack spacing={2}>
          <Typography variant="body2" sx={{ overflowWrap: "anywhere" }}>
            {filename}
          </Typography>
          <Typography variant="body2" color="text.secondary">
            {t(
              "Restoration replaces data and YAML settings, keeps the installed program version, stops correction streams and restarts the service. Code inside the archive is not installed. Your session may end. Only continue after field work has stopped.",
            )}
          </Typography>
          {error && <Alert severity="error">{t(error)}</Alert>}
          {encrypted && (
            <TextField
              fullWidth
              type="password"
              label={t("Backup passphrase")}
              value={passphrase}
              disabled={Boolean(busy)}
              autoComplete="off"
              helperText={t("Leave blank to use the stored passphrase.")}
              onChange={(e) => {
                setPassphrase(e.target.value);
                setPreview(null);
                setTyped("");
                setAcknowledged(false);
              }}
            />
          )}
          <Button
            variant="outlined"
            disabled={Boolean(busy)}
            onClick={() => inspect()}
          >
            {t("Inspect backup")}
          </Button>
          {busy && (
            <Box role="status">
              <LinearProgress />
              <Typography variant="body2" sx={{ mt: 1 }}>
                {t(
                  busy === "preview"
                    ? "Checking archive and compatibility…"
                    : "Rechecking the archive and starting restoration…",
                )}
              </Typography>
            </Box>
          )}
          {preview && (
            <>
              <Alert
                severity={
                  preview.compatible
                    ? preview.legacy
                      ? "warning"
                      : "success"
                    : "error"
                }
              >
                {t(
                  preview.compatible
                    ? preview.legacy
                      ? "Legacy backup: review the limitations before continuing"
                      : "Compatible with this installation"
                    : "This backup cannot be restored on this installation",
                )}
              </Alert>
              <KeyValues
                data={{
                  [t("Backup application version")]:
                    preview.source_version || t("Not recorded"),
                  [t("Installed application version")]:
                    preview.installed_version,
                  [t("Backup creation time")]: preview.created_at
                    ? date(preview.created_at)
                    : t("Not recorded"),
                  [t("Database schema")]:
                    `${preview.schema_version} / ${preview.installed_schema_version}`,
                }}
              />
              {preview.reasons?.map((message) => (
                <Alert key={message} severity="error">
                  {t(message)}
                </Alert>
              ))}
              {preview.warnings?.map((message) => (
                <Alert key={message} severity="warning">
                  {t(message)}
                </Alert>
              ))}
              <Typography variant="subtitle2">
                {t("What will change")}
              </Typography>
              {preview.components?.map((item) => (
                <Stack
                  key={item.name}
                  direction="row"
                  justifyContent="space-between"
                  spacing={2}
                >
                  <Typography variant="body2">
                    {t(names[item.name] || item.name)}
                    <Typography
                      component="span"
                      variant="caption"
                      color="text.secondary"
                    >{` · ${bytes(item.size_bytes)}`}</Typography>
                  </Typography>
                  <Typography variant="body2" sx={{ flexShrink: 0 }}>
                    {t(
                      item.restored ? "Restore from backup" : "Keep installed",
                    )}
                  </Typography>
                </Stack>
              ))}
              <Typography variant="subtitle2">
                {t("Records in the backup")}
              </Typography>
              <KeyValues
                data={Object.fromEntries(
                  Object.entries(preview.counts || {}).map(([key, value]) => [
                    t(countNames[key] || key),
                    value,
                  ]),
                )}
              />
              <Alert severity="info">
                {t(
                  "Accounts, passwords and saved settings return to the backup date. Current sessions may end. Compatibility checks do not prove who created an archive; restore only a copy you trust.",
                )}
              </Alert>
              {preview.legacy && preview.compatible && (
                <FormControlLabel
                  control={
                    <Checkbox
                      checked={acknowledged}
                      disabled={Boolean(busy)}
                      onChange={(e) => setAcknowledged(e.target.checked)}
                    />
                  }
                  label={t(
                    "I understand the limitations of this legacy backup.",
                  )}
                />
              )}
            </>
          )}
          <TextField
            fullWidth
            label={t("Type {0} to confirm", ["RESTORE"])}
            value={typed}
            disabled={Boolean(busy)}
            onChange={(e) => setTyped(e.target.value)}
            autoComplete="off"
          />
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button disabled={busy === "restore"} onClick={close}>
          {t("Cancel")}
        </Button>
        <Button
          variant="contained"
          color="error"
          disabled={
            Boolean(busy) ||
            !preview?.compatible ||
            typed !== "RESTORE" ||
            (preview.legacy && !acknowledged)
          }
          onClick={restore}
        >
          {t("Confirm")}
        </Button>
      </DialogActions>
    </Dialog>
  );
}
