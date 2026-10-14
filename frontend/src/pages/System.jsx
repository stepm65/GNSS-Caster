import { t } from "../i18n";
import React, { useContext, useEffect, useRef, useState } from "react";
import {
  Alert,
  Box,
  Button,
  LinearProgress,
  Stack,
  Tab,
  Tabs,
  Typography,
} from "@mui/material";
import BackupOutlined from "@mui/icons-material/BackupOutlined";
import FileUploadOutlined from "@mui/icons-material/FileUploadOutlined";
import { Session } from "../session";
import { api, uploadBackup } from "../api";
import { useAction, useResource, useUnsavedChanges } from "../hooks";
import {
  Confirm,
  DataTable,
  Fields,
  GridBox,
  KeyValues,
  Notice,
  PageTitle,
  Panel,
  ResourceState,
  Status,
  bool,
  bytes,
  date,
  label,
} from "../components";
const field = (key, type = "text", extra = {}) => ({
  key,
  type,
  ...extra,
});
const groups = [
  {
    name: "General",
    fields: [
      field("system_name", "text", {
        required: true,
      }),
      field("bluetooth_name"),
      field("log_retention", "number", {
        label: "Log retention (days)",
        min: 1,
        max: 365,
      }),
      field("data_retention", "number", {
        label: "Backup retention (days)",
        min: 1,
        max: 3650,
      }),
      field("gnss_time_sync", "boolean", {
        label: "Synchronize time from GNSS",
      }),
    ],
  },
  {
    name: "Connections",
    fields: [
      field("ntrip_enabled", "boolean", {
        label: "NTRIP server enabled",
      }),
      field("max_connections", "number", {
        label: "Maximum NTRIP connections",
        min: 1,
        max: 1000,
      }),
      field("bluetooth_enabled", "boolean"),
      field("bluetooth_discoverable", "boolean"),
    ],
  },
  {
    name: "Notifications",
    fields: [
      field("telegram_enabled", "boolean"),
      field("telegram_language", "text", {
        label: "Telegram language",
        options: [
          {
            value: "en",
            label: "English",
          },
          {
            value: "ru",
            label: "Русский",
          },
        ],
      }),
      field("telegram_commands_enabled", "boolean"),
      field("telegram_bot_token", "password", {
        label: "Telegram bot token",
      }),
      field("telegram_chat_id", "text", {
        label: "Notification chat ID",
      }),
      field("telegram_admin_id", "text", {
        label: "Administrator chat ID",
      }),
      field("telegram_send_backup", "boolean", {
        label: "Send backup files to Telegram",
      }),
      ...[
        "station_up",
        "station_down",
        "station_error",
        "rover_connect",
        "rover_disconnect",
        "backup",
        "service",
      ].map((k) =>
        field(`notify_${k}`, "boolean", {
          label: k
            .replaceAll("_", " ")
            .replace(/\b\w/g, (c) => c.toUpperCase()),
        }),
      ),
    ],
  },
  {
    name: "Backup policy",
    fields: [
      field("auto_backup", "boolean", {
        label: "Automatic backups",
      }),
      field("backup_interval", "number", {
        label: "Backup interval (seconds)",
        min: 3600,
        max: 604800,
        help: "86400 = daily; 3600 = hourly.",
      }),
      field("backup_external_path", "text", {
        label: "External backup directory",
        help: "An absolute path on the caster. Leave blank to disable the external copy.",
      }),
      field("backup_encryption_enabled", "boolean"),
      field("backup_encryption_passphrase", "password", {
        label: "Encryption passphrase",
        help: "At least 12 characters. Keep this separately so you can restore old backups.",
      }),
    ],
  },
];
function SettingsForm({ group, settings, onSaved }) {
  const { isAdmin } = useContext(Session),
    action = useAction();
  const [value, setValue] = useState(() =>
    Object.fromEntries(
      group.fields.map((f) => [
        f.key,
        f.type === "boolean"
          ? bool(settings[f.key]?.value)
          : (settings[f.key]?.value ?? ""),
      ]),
    ),
  );
  const [jobs, setJobs] = useState([]);
  useEffect(() => {
    setValue(
      Object.fromEntries(
        group.fields.map((f) => [
          f.key,
          f.type === "boolean"
            ? bool(settings[f.key]?.value)
            : (settings[f.key]?.value ?? ""),
        ]),
      ),
    );
  }, [group, settings]);
  const changed = Object.fromEntries(
    group.fields
      .filter((f) => {
        if (settings[f.key]?.is_secret && !value[f.key]) return false;
        return (
          String(value[f.key] ?? "") !==
          String(
            f.type === "boolean"
              ? bool(settings[f.key]?.value)
              : (settings[f.key]?.value ?? ""),
          )
        );
      })
      .map((f) => [f.key, value[f.key]]),
  );
  useUnsavedChanges(Object.keys(changed).length > 0 && !action.busy);
  return (
    <Panel
      title={group.name}
      caption={t(
        "Changes are saved explicitly. Connection settings may require a service restart.",
      )}
    >
      <Box
        component="form"
        onSubmit={(e) => {
          e.preventDefault();
          action.run(
            () =>
              api("/api/system/settings/update", {
                method: "POST",
                body: changed,
              }),
            (result) => {
              setJobs(
                Object.entries(result.applied || {})
                  .filter(([key]) => key.endsWith("_job_id"))
                  .map(([, id]) => id),
              );
              onSaved();
            },
          );
        }}
      >
        <Notice value={action.notice} />
        <Fields
          schema={group.fields.map((f) =>
            settings[f.key]?.is_secret
              ? {
                  ...f,
                  help: `${t(settings[f.key].is_set ? "A value is stored." : "No value is stored.")} ${t("Leave blank to keep it.")} ${t(f.help || "")}`,
                }
              : f,
          )}
          value={value}
          onChange={setValue}
          disabled={!isAdmin || action.busy}
        />
        <Stack
          direction="row"
          spacing={2}
          sx={{
            mt: 3,
          }}
        >
          {isAdmin && (
            <Button
              variant="contained"
              type="submit"
              disabled={action.busy || !Object.keys(changed).length}
            >
              {t(`Save ${group.name.toLowerCase()}`)}
            </Button>
          )}
          {group.name === "Notifications" && isAdmin && (
            <Button
              disabled={action.busy}
              onClick={() =>
                action.run(() =>
                  api("/api/system/notify/test", {
                    method: "POST",
                  }),
                )
              }
            >
              {t("Send test notification")}
            </Button>
          )}
        </Stack>
      </Box>
      {jobs.map((id) => (
        <PrivilegedJob key={id} id={id} />
      ))}
    </Panel>
  );
}
function PrivilegedJob({ id }) {
  const [finished, setFinished] = useState(false),
    resource = useResource(
      `/api/system/privileged_jobs/${encodeURIComponent(id)}`,
      finished ? 0 : 3000,
    );
  useEffect(() => {
    if (
      ["done", "failed", "completed", "error"].includes(
        resource.data?.status,
      ) ||
      resource.error?.status === 200
    )
      setFinished(true);
  }, [resource.data, resource.error]);
  return (
    <Box
      sx={{
        mt: 2,
      }}
    >
      <ResourceState resource={resource} />
      {resource.data && (
        <Alert
          severity={
            resource.data.error ||
            ["error", "failed"].includes(resource.data.status)
              ? "error"
              : finished
                ? "success"
                : "info"
          }
        >
          {resource.data.kind || t("Settings update")}:{" "}
          {resource.data.error || resource.data.message || resource.data.status}
        </Alert>
      )}
    </Box>
  );
}
export default function System() {
  return location.pathname === "/backups" ? <Backups /> : <SystemSettings />;
}
function SystemSettings() {
  const { isAdmin } = useContext(Session),
    settings = useResource("/api/system/settings", 0),
    tls = useResource("/api/system/tls", 0),
    [tab, setTab] = useState(0),
    [confirm, setConfirm] = useState(null),
    action = useAction();
  return (
    <>
      <PageTitle
        title={t("System settings")}
        eyebrow={t("MANAGEMENT")}
        description={t(
          "Configure this caster, notifications and maintenance policies.",
        )}
      />
      <ResourceState resource={settings} />
      <Notice value={action.notice} />
      {!isAdmin && (
        <Alert
          severity="info"
          sx={{
            mb: 2,
          }}
        >
          {t("Your account has read-only access to system settings.")}
        </Alert>
      )}
      <Tabs
        value={tab}
        onChange={(_, v) => setTab(v)}
        variant="scrollable"
        allowScrollButtonsMobile
        sx={{
          mb: 3,
        }}
      >
        {groups.map((g) => (
          <Tab key={g.name} label={t(g.name)} />
        ))}
        <Tab label={t("Certificates")} />
        <Tab label={t("Power")} />
      </Tabs>
      {tab < groups.length && settings.data && (
        <SettingsForm
          key={tab}
          group={groups[tab]}
          settings={settings.data}
          onSaved={settings.refresh}
        />
      )}
      {tab === 4 && (
        <Panel
          title={t("TLS certificates")}
          caption={t("HTTPS certificate information and renewal.")}
        >
          <ResourceState resource={tls} />
          <KeyValues data={tls.data} />
          {isAdmin && (
            <Stack
              direction="row"
              spacing={2}
              sx={{
                mt: 3,
              }}
            >
              <Button
                disabled={action.busy}
                variant="outlined"
                onClick={() =>
                  setConfirm({
                    title: t("Renew HTTPS certificates?"),
                    description: t("Runs certificate renewal on the caster."),
                    url: "/api/system/tls/renew",
                    body: {
                      force: false,
                    },
                  })
                }
              >
                {t("Renew certificates")}
              </Button>
              <Button
                disabled={action.busy}
                color="warning"
                onClick={() =>
                  setConfirm({
                    title: t("Force certificate renewal?"),
                    description: t(
                      "Requests a new certificate even if renewal is not due. Certificate authority rate limits apply.",
                    ),
                    url: "/api/system/tls/renew",
                    body: {
                      force: true,
                    },
                  })
                }
              >
                {t("Force renewal")}
              </Button>
            </Stack>
          )}
        </Panel>
      )}
      {tab === 5 && (
        <Panel
          title={t("Host power")}
          caption={t(
            "These actions interrupt all correction streams and disconnect the web interface.",
          )}
        >
          {isAdmin ? (
            <Stack
              direction="row"
              spacing={2}
              sx={{
                mt: 3,
              }}
            >
              {["reboot", "shutdown"].map((type) => (
                <Button
                  key={type}
                  color="error"
                  variant="outlined"
                  onClick={() =>
                    setConfirm({
                      title: t("{0} the caster?", [label(type)]),
                      description: t(
                        "All connected rovers will lose corrections. Make sure field work has finished before continuing.",
                      ),
                      word: type,
                      url: `/api/system/power/${type}`,
                      body: {
                        confirm: type,
                      },
                    })
                  }
                >
                  {label(type)}
                </Button>
              ))}
            </Stack>
          ) : (
            <Alert severity="info">{t("Administrator access required.")}</Alert>
          )}
        </Panel>
      )}
      {confirm && (
        <Confirm
          {...confirm}
          onClose={() => setConfirm(null)}
          onConfirm={async () => {
            const result = await api(confirm.url, {
              method: "POST",
              body: confirm.body,
              timeout: 180000,
            });
            action.setNotice({
              severity: "info",
              text: result.message,
            });
            tls.refresh();
            return result;
          }}
        />
      )}
    </>
  );
}
function Backups() {
  const { isAdmin, canEdit } = useContext(Session),
    backups = useResource("/api/system/backups?limit=50"),
    storage = useResource("/api/system/backups/storage", 60000),
    action = useAction();
  const [confirm, setConfirm] = useState(null),
    [uploading, setUploading] = useState(false),
    [progress, setProgress] = useState(0);
  const [job, setJob] = useState(() => {
    try {
      return JSON.parse(
        sessionStorage.getItem("gnss_maintenance_job") || "null",
      );
    } catch {
      return null;
    }
  });
  const [finished, setFinished] = useState(false);
  const jobResource = useResource(
    job?.unit_name
      ? `/api/system/jobs/${encodeURIComponent(job.unit_name)}`
      : null,
    finished ? 0 : 3000,
  );
  const fileInput = useRef(),
    uploadController = useRef();
  useEffect(() => () => uploadController.current?.abort(), []);
  useEffect(() => {
    if (jobResource.data?.is_finished) {
      setFinished(true);
      backups.refresh();
      storage.refresh();
    }
  }, [jobResource.data?.is_finished]);
  function rememberJob(result) {
    if (result.job?.unit_name) {
      setFinished(false);
      setJob(result.job);
      try {
        sessionStorage.setItem(
          "gnss_maintenance_job",
          JSON.stringify(result.job),
        );
      } catch {}
    }
  }
  function dismissJob() {
    setJob(null);
    try {
      sessionStorage.removeItem("gnss_maintenance_job");
    } catch {}
  }
  const activeJob = !!job && !finished;
  async function upload(file) {
    if (!file) return;
    setUploading(true);
    setProgress(0);
    action.setNotice(null);
    const controller = new AbortController();
    uploadController.current = controller;
    try {
      const result = await uploadBackup(file, setProgress, controller.signal);
      backups.refresh();
      action.setNotice({
        severity: "success",
        text: "Backup uploaded. Review the archive below before restoring.",
      });
      setConfirm({
        type: "restore",
        filename: result.filename,
      });
    } catch (e) {
      action.setNotice({
        severity: "error",
        text: e.message,
      });
    } finally {
      setUploading(false);
      uploadController.current = null;
      if (fileInput.current) fileInput.current.value = "";
    }
  }
  return (
    <>
      <PageTitle
        title={t("Backups & restore")}
        eyebrow={t("MAINTENANCE")}
        description={t(
          "Keep recovery copies and restore a backup from any date.",
        )}
        action={
          canEdit && (
            <Button
              startIcon={<BackupOutlined />}
              variant="contained"
              disabled={action.busy || activeJob || uploading}
              onClick={() =>
                action.run(
                  () =>
                    api("/api/system/backups/create", {
                      method: "POST",
                    }),
                  rememberJob,
                )
              }
            >
              {t("Create backup")}
            </Button>
          )
        }
      />
      <Notice value={action.notice} />
      <ResourceState resource={backups} />
      {job && (
        <Panel
          title={t("Maintenance job")}
          caption={job.filename || job.unit_name}
          sx={{
            mb: 3,
          }}
          action={
            <Button onClick={dismissJob}>
              {finished ? t("Dismiss") : t("Hide job")}
            </Button>
          }
        >
          <ResourceState resource={jobResource} />
          <Alert
            severity={
              jobResource.data?.status === "failed"
                ? "error"
                : jobResource.data?.status === "completed"
                  ? "success"
                  : "info"
            }
          >
            {jobResource.data?.message ||
              t(
                "Waiting for the job status. The server may briefly disconnect during restoration.",
              )}
          </Alert>
          {jobResource.error && (
            <Button onClick={jobResource.refresh}>
              {t("Check job status")}
            </Button>
          )}
        </Panel>
      )}
      {isAdmin && (
        <Panel
          sx={{
            mb: 3,
            borderStyle: "dashed",
            bgcolor: "action.hover",
          }}
        >
          <Stack
            direction={{
              xs: "column",
              sm: "row",
            }}
            alignItems={{
              sm: "center",
            }}
            spacing={3}
          >
            <Box
              sx={{
                flex: 1,
              }}
            >
              <Typography variant="h6">
                {t("Restore a file from your computer")}
              </Typography>
              <Typography
                color="text.secondary"
                variant="body2"
                sx={{
                  mt: 1,
                }}
              >
                {t(
                  "Choose a backup you downloaded from Telegram or saved elsewhere. Supports .tar.gz and encrypted .tar.gz.enc files up to 128 MiB.",
                )}
              </Typography>
            </Box>
            <input
              ref={fileInput}
              type="file"
              accept=".gz,.enc"
              aria-label={t("Choose backup file")}
              hidden
              onChange={(e) => upload(e.target.files?.[0])}
            />
            <Button
              startIcon={<FileUploadOutlined />}
              variant="outlined"
              disabled={uploading || activeJob || action.busy}
              onClick={() => fileInput.current.click()}
            >
              {t("Choose backup file")}
            </Button>
          </Stack>
          {uploading && (
            <Box
              sx={{
                mt: 3,
              }}
            >
              <LinearProgress variant="determinate" value={progress} />
              <Stack
                direction="row"
                justifyContent="space-between"
                sx={{
                  mt: 1,
                }}
              >
                <Typography variant="body2">
                  {progress < 100
                    ? t("Uploading \xB7 {0}%", [progress])
                    : t("Upload complete. Checking file\u2026")}
                </Typography>
                <Button
                  size="small"
                  onClick={() => uploadController.current?.abort()}
                >
                  {t("Cancel upload")}
                </Button>
              </Stack>
            </Box>
          )}
        </Panel>
      )}
      <Panel
        title={t("Saved backups")}
        caption={t("{0} archives \xB7 {1}", [
          backups.data?.count ?? 0,
          bytes(backups.data?.total_size_bytes),
        ])}
        action={<Button onClick={backups.refresh}>{t("Refresh")}</Button>}
      >
        <DataTable
          rows={backups.data?.items || []}
          columns={[
            {
              key: "filename",
              label: t("Backup archive"),
            },
            {
              key: "modified_at",
              label: t("Date"),
              render: (r) => date(r.modified_at),
            },
            {
              key: "size_bytes",
              label: t("Size"),
              render: (r) => bytes(r.size_bytes),
            },
          ]}
          actions={(r) => (
            <>
              <Button
                size="small"
                disabled={action.busy || activeJob}
                onClick={() =>
                  setConfirm({
                    type: "verify",
                    filename: r.filename,
                  })
                }
              >
                {t("Verify")}
              </Button>
              {isAdmin && (
                <>
                  <Button
                    size="small"
                    href={`/api/system/backups/download/${encodeURIComponent(r.filename)}`}
                  >
                    {t("Download")}
                  </Button>
                  <Button
                    size="small"
                    disabled={activeJob || uploading}
                    onClick={() =>
                      setConfirm({
                        type: "restore",
                        filename: r.filename,
                      })
                    }
                  >
                    {t("Restore")}
                  </Button>
                  <Button
                    size="small"
                    color="error"
                    disabled={activeJob || uploading}
                    onClick={() =>
                      setConfirm({
                        type: "delete",
                        filename: r.filename,
                      })
                    }
                  >
                    {t("Delete")}
                  </Button>
                </>
              )}
            </>
          )}
        />
      </Panel>
      <Box
        sx={{
          mt: 3,
        }}
      >
        <ResourceState resource={storage} />
        {storage.data?.warnings?.map((text, i) => (
          <Alert
            severity="warning"
            key={i}
            sx={{
              mb: 2,
            }}
          >
            {text}
          </Alert>
        ))}
        <GridBox>
          <Panel title={t("Local storage")}>
            <KeyValues data={storage.data?.local} />
          </Panel>
          <Panel title={t("External copy")}>
            <KeyValues data={storage.data?.external} />
          </Panel>
        </GridBox>
      </Box>
      {confirm && (
        <Confirm
          title={t("{0} backup?", [label(confirm.type)])}
          description={
            confirm.type === "restore"
              ? t(
                  "Restoration replaces the caster data and configuration, stops correction streams and restarts the service. Your session may end. Only continue after field work has stopped.",
                )
              : confirm.type === "delete"
                ? t("This permanently deletes the selected archive.")
                : t(
                    "Checks whether this archive can be read. Restoration performs additional checks before replacing any data.",
                  )
          }
          word={confirm.type === "restore" ? "RESTORE" : undefined}
          password={
            confirm.type !== "delete" && confirm.filename?.endsWith(".enc")
          }
          onClose={() => setConfirm(null)}
          onConfirm={async (passphrase) => {
            const result = await api(`/api/system/backups/${confirm.type}`, {
              method: "POST",
              body: {
                filename: confirm.filename,
                ...(passphrase
                  ? {
                      passphrase,
                    }
                  : {}),
              },
              timeout: confirm.type === "verify" ? 260000 : 30000,
            });
            rememberJob(result);
            action.setNotice({
              severity: "info",
              text: result.message,
            });
            backups.refresh();
            return result;
          }}
        >
          <Typography
            sx={{
              mb: 2,
              p: 2,
              bgcolor: "action.hover",
              borderRadius: 2,
              overflowWrap: "anywhere",
            }}
          >
            {confirm.filename}
          </Typography>
        </Confirm>
      )}
    </>
  );
}
