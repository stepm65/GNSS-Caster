import React, { useEffect, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  LinearProgress,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import { api } from "../api";
import { useAction, useResource } from "../hooks";
import { Notice, Panel, date } from "../components";
import { t } from "../i18n";

const busyStates = ["queued", "checking", "downloading", "installing"];

export default function Updates() {
  const resource = useResource("/api/system/updates/status", 5000);
  const action = useAction();
  const [confirmation, setConfirmation] = useState(false);
  const [password, setPassword] = useState("");
  const [word, setWord] = useState("");
  const [accepted, setAccepted] = useState(null);
  const job = resource.data?.job || { status: "idle" };
  const release = resource.data?.release;
  const candidate = release?.candidate;
  const recovery = resource.data?.recovery || [];
  const active = Boolean(accepted) || busyStates.includes(job.status);
  useEffect(() => {
    if (accepted && job.started_at >= accepted.started_at) setAccepted(null);
  }, [accepted, job.started_at]);
  const close = () => {
    if (action.busy) return;
    setConfirmation(false);
    setPassword("");
    setWord("");
  };
  return (
    <Panel
      title={t("Software updates")}
      caption={t(
        "Stable releases from stepm65/GNSS-Caster. Installation starts only after your confirmation.",
      )}
    >
      <Notice value={action.notice} />
      {resource.error && (
        <Alert severity="warning" sx={{ mb: 2 }}>
          {active
            ? t(
                "Waiting for the service to reconnect. Do not repeat installation.",
              )
            : resource.error.message}
        </Alert>
      )}
      {resource.loading && !resource.data && (
        <LinearProgress aria-label={t("Loading…")} />
      )}
      <Stack spacing={2}>
        <Typography>
          {t("Installed version: {0}", [resource.data?.current_version || "—"])}
        </Typography>
        <Typography color="text.secondary">
          {t("Last checked: {0}", [
            release?.checked_at ? date(release.checked_at) : t("Never"),
          ])}
        </Typography>
        <Alert severity="info">
          {t(
            "Updates interrupt correction streams and web access. Finish field work and disconnect all rovers first. A rollback snapshot is created before files are changed.",
          )}
        </Alert>
        {recovery.map((item) => (
          <Alert severity="warning" key={item.id}>
            <Typography>
              {t("Unfinished maintenance needs local recovery before another update. Snapshot: {0}.", [item.id])}
            </Typography>
            <Typography variant="body2" sx={{ mt: 1 }}>
              {t("An administrator must inspect the journal over SSH. Recovery checks the saved files before restoring them.")}
            </Typography>
            <Typography component="pre" variant="body2" sx={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>
              {item.recovery_command}
            </Typography>
          </Alert>
        ))}
        <Box>
          <Button
            variant="outlined"
            disabled={action.busy || active || Boolean(resource.error)}
            onClick={() =>
              action.run(async () => {
                await api("/api/system/updates/check", {
                  method: "POST",
                  body: {},
                  timeout: 50000,
                });
                resource.refresh();
                return { message: "Release check completed" };
              })
            }
          >
            {action.busy && !confirmation
              ? t("Checking…")
              : t("Check for updates")}
          </Button>
        </Box>
        {release && !candidate && (
          <Alert severity="info">
            {t("No published stable release is available yet.")}
          </Alert>
        )}
        {candidate && (
          <>
            <Typography variant="h6">
              {t("Stable version: {0}", [candidate.version])}
            </Typography>
            {!candidate.available && (
              <Alert severity="success">
                {t("No newer stable version is available.")}
              </Alert>
            )}
            <Button
              href={candidate.url}
              target="_blank"
              rel="noopener noreferrer"
              sx={{ alignSelf: "flex-start" }}
            >
              {t("View release on GitHub")}
            </Button>
            {candidate.notes && (
              <Typography
                component="div"
                role="region"
                aria-label={t("Release notes")}
                tabIndex={0}
                sx={{
                  whiteSpace: "pre-wrap",
                  overflowWrap: "anywhere",
                  maxHeight: 260,
                  overflow: "auto",
                }}
              >
                {candidate.notes}
              </Typography>
            )}
            {candidate.available && (
              <Box>
                <Button
                  variant="contained"
                  disabled={active || action.busy || Boolean(resource.error) || recovery.length > 0}
                  onClick={() => {
                    action.setNotice(null);
                    setConfirmation(true);
                  }}
                >
                  {t("Install version {0}", [candidate.version])}
                </Button>
              </Box>
            )}
          </>
        )}
        {(active || job.status !== "idle") && (
          <Alert
            severity={
              active
                ? "info"
                : job.status === "succeeded"
                  ? "success"
                  : "warning"
            }
          >
            <Typography>
              {t(accepted?.message || job.message || "Update queued")}
            </Typography>
            {active && (
              <LinearProgress
                aria-label={t("Update progress")}
                sx={{ mt: 1.5 }}
              />
            )}
            {job.snapshot && (
              <Typography
                variant="body2"
                sx={{ mt: 1, overflowWrap: "anywhere" }}
              >
                {t("Rollback snapshot: {0}", [job.snapshot])}
              </Typography>
            )}
            {job.status === "succeeded" && (
              <Button onClick={() => location.reload()}>{t("Reload")}</Button>
            )}
            {["failed", "interrupted", "rolled_back"].includes(job.status) && (
              <Typography variant="body2" sx={{ mt: 1 }}>
                {t(
                  "Administrator log: /var/lib/gnss-caster-updates/maintenance.log. A power interruption may require recovery over SSH.",
                )}
              </Typography>
            )}
          </Alert>
        )}
      </Stack>
      {confirmation && candidate && (
        <Dialog open fullWidth maxWidth="sm" onClose={close}>
          <Box
            component="form"
            onSubmit={(event) => {
              event.preventDefault();
              if (word !== "UPDATE" || !password || active) return;
              action.run(async () => {
                try {
                  const result = await api("/api/system/updates/install", {
                    method: "POST",
                    body: {
                      tag: candidate.tag,
                      sha256: candidate.sha256,
                      confirm: word,
                      password,
                    },
                    timeout: 50000,
                  });
                  setAccepted(result);
                  setConfirmation(false);
                  setWord("");
                  resource.refresh();
                  return { message: result.message };
                } finally {
                  setPassword("");
                  resource.refresh();
                }
              });
            }}
          >
            <DialogTitle>
              {t("Install version {0}?", [candidate.version])}
            </DialogTitle>
            <DialogContent dividers>
              <Notice value={action.notice} />
              <Alert severity="warning" sx={{ mb: 3 }}>
                {t(
                  "All corrections will stop during installation. Automatic rollback is attempted on installation failure; it cannot guarantee recovery after a power cut.",
                )}
              </Alert>
              <TextField
                fullWidth
                label={t("Current password")}
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                disabled={action.busy}
                sx={{ mb: 3 }}
              />
              <TextField
                fullWidth
                label={t("Type UPDATE to confirm")}
                value={word}
                onChange={(event) => setWord(event.target.value)}
                disabled={action.busy}
                autoComplete="off"
              />
            </DialogContent>
            <DialogActions>
              <Button onClick={close} disabled={action.busy}>
                {t("Cancel")}
              </Button>
              <Button
                type="submit"
                variant="contained"
                disabled={
                  word !== "UPDATE" || !password || active || action.busy
                }
              >
                {t("Install update")}
              </Button>
            </DialogActions>
          </Box>
        </Dialog>
      )}
    </Panel>
  );
}
