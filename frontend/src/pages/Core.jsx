import { t, getLocale, serverMessage } from "../i18n";
import React, { useContext, useEffect, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Checkbox,
  Divider,
  LinearProgress,
  Stack,
  Switch,
  TextField,
  MenuItem,
  Typography,
} from "@mui/material";
import CellTower from "@mui/icons-material/CellTower";
import Route from "@mui/icons-material/Route";
import HubOutlined from "@mui/icons-material/HubOutlined";
import Sensors from "@mui/icons-material/Sensors";
import ArrowForward from "@mui/icons-material/ArrowForward";
import Refresh from "@mui/icons-material/Refresh";
import { Session } from "../session";
import { api } from "../api";
import { useAction, useResource, useUnsavedChanges } from "../hooks";
import {
  Confirm,
  CrudPage,
  DataTable,
  Empty,
  FormDialog,
  GridBox,
  KeyValues,
  Metric,
  Notice,
  PageTitle,
  Panel,
  ResourceState,
  Status,
  bytes,
  date,
  label,
  number,
} from "../components";
export function Dashboard() {
  const health = useResource("/api/diagnostics", 15000),
    system = useResource("/api/status"),
    ntrip = useResource("/api/ntrip/status", 15000);
  const stations = health.data?.stations || [],
    stats = system.data?.database || {},
    resources = system.data?.resources || {};
  const good = stations.filter((s) => s.rtcm === "ok").length;
  return (
    <>
      <PageTitle
        eyebrow={t("LIVE OPERATIONS")}
        title={t("Overview")}
        description={t(
          "Your base stations and field connections, at a glance.",
        )}
        action={
          <Button
            variant="outlined"
            startIcon={<Refresh />}
            onClick={() => {
              health.refresh();
              system.refresh();
              ntrip.refresh();
            }}
          >
            {t("Refresh")}
          </Button>
        }
      />
      <ResourceState resource={health} />
      <ResourceState resource={system} />
      <ResourceState resource={ntrip} />
      <GridBox columns={4}>
        <Metric
          label={t("Corrections")}
          value={health.error ? "Unknown" : `${good} / ${stations.length}`}
          caption={t("Stations with fresh RTCM")}
          icon={<Sensors />}
        />
        <Metric
          label={t("Base stations")}
          value={stats.base_stations}
          caption={t("{0} connected", [
            health.error
              ? "—"
              : stations.filter((s) => s.receiver === "ok").length,
          ])}
          icon={<CellTower />}
        />
        <Metric
          label={t("Rovers online")}
          value={ntrip.error ? "—" : ntrip.data?.connections?.length}
          caption={t("Active field connections")}
          icon={<Route />}
        />
        <Metric
          label={t("Mountpoints")}
          value={stats.mountpoints}
          caption={t("Configured correction streams")}
          icon={<HubOutlined />}
        />
      </GridBox>
      <Box
        sx={{
          display: "grid",
          gridTemplateColumns: {
            xs: "1fr",
            lg: "minmax(0, 2fr) minmax(280px, 1fr)",
          },
          gap: 2.5,
          mt: 3,
        }}
      >
        <Stack spacing={2.5}>
          <Panel
            title={t("Base stations")}
            caption={t("Connection and correction availability")}
            action={
              <Button
                href="/base_stations"
                endIcon={<ArrowForward />}
                size="small"
              >
                {t("Manage")}
              </Button>
            }
          >
            <DataTable
              rows={stations}
              columns={[
                {
                  key: "name",
                  label: t("Station"),
                  render: (s) => (
                    <Button
                      href={`/base_stations/${s.id}`}
                      sx={{
                        px: 0,
                      }}
                    >
                      {s.name}
                    </Button>
                  ),
                },
                {
                  key: "receiver",
                  label: t("Receiver"),
                  render: (s) => (
                    <Status
                      value={health.error ? "unknown" : s.receiver}
                      text={
                        !health.error && s.receiver === "ok"
                          ? t("Connected")
                          : undefined
                      }
                    />
                  ),
                },
                {
                  key: "rtcm",
                  label: t("Corrections"),
                  render: (s) => (
                    <Status
                      value={health.error ? "unknown" : s.rtcm}
                      text={
                        !health.error && s.rtcm === "ok"
                          ? t("Streaming")
                          : undefined
                      }
                    />
                  ),
                },
              ]}
              empty={t("No base stations configured")}
            />
            <Box
              sx={{
                mt: 2,
                textAlign: "right",
              }}
            >
              <Button href="/diagnostics" size="small">
                {t("Open diagnostics")}
              </Button>
            </Box>
          </Panel>
          <Panel
            title={t("Field connections")}
            caption={t("Rovers currently receiving corrections")}
            action={
              <Status
                value={
                  ntrip.error
                    ? "unknown"
                    : ntrip.data?.running
                      ? "running"
                      : "stopped"
                }
                text={
                  ntrip.error
                    ? t("Unavailable")
                    : ntrip.data?.running
                      ? t("NTRIP online")
                      : t("NTRIP offline")
                }
              />
            }
          >
            <DataTable
              rows={ntrip.data?.connections || []}
              empty={t("No rovers connected")}
              columns={[
                {
                  key: "rover",
                  label: t("Rover"),
                },
                {
                  key: "mountpoint",
                },
                {
                  key: "duration",
                  label: t("Session"),
                  render: (r) =>
                    t("{0} min", [Math.floor((r.duration || 0) / 60)]),
                },
              ]}
            />
          </Panel>
        </Stack>
        <Stack spacing={2.5}>
          <Panel
            title={t("Host resources")}
            caption={system.data?.system?.hostname || t("Caster computer")}
          >
            {[
              ["CPU", resources.cpu_percent],
              ["Memory", resources.memory_percent],
              ["Storage", resources.disk_percent],
            ].map(([name, value]) => (
              <Box
                key={t(name)}
                sx={{
                  my: 2.5,
                }}
              >
                <Stack
                  direction="row"
                  justifyContent="space-between"
                  sx={{
                    mb: 1,
                  }}
                >
                  <Typography variant="body2">{t(name)}</Typography>
                  <Typography variant="body2" fontWeight={600}>
                    {value == null ? "—" : `${value.toFixed(0)}%`}
                  </Typography>
                </Stack>
                <LinearProgress
                  variant="determinate"
                  value={value ?? 0}
                  color={value > 90 ? "warning" : "primary"}
                  sx={{
                    height: 6,
                    borderRadius: 3,
                  }}
                />
              </Box>
            ))}
            <Divider />
            <Stack
              direction="row"
              justifyContent="space-between"
              sx={{
                pt: 2,
              }}
            >
              <Typography variant="body2" color="text.secondary">
                {t("CPU temperature")}
              </Typography>
              <Typography variant="body2">
                {resources.cpu_temp_c == null
                  ? "—"
                  : t("{0} \xB0C", [resources.cpu_temp_c.toFixed(1)])}
              </Typography>
            </Stack>
          </Panel>
          <Panel title={t("Workspace tools")}>
            <Stack spacing={1}>
              <Button href="/backups" variant="outlined">
                {t("Backup & restore")}
              </Button>
              <Button href="/logs" variant="outlined">
                {t("View event logs")}
              </Button>
              <Button href="/rtcm_settings" variant="outlined">
                {t("Configure RTCM messages")}
              </Button>
            </Stack>
          </Panel>
          <Typography variant="caption" color="text.secondary">
            {health.updatedAt
              ? t("Updated {0}", [
                  health.updatedAt.toLocaleTimeString(getLocale()),
                ])
              : t("Waiting for station data")}
          </Typography>
        </Stack>
      </Box>
    </>
  );
}
export function Diagnostics() {
  const health = useResource("/api/diagnostics"),
    host = useResource("/api/status"),
    bt = useResource("/api/bluetooth/status"),
    readiness = useResource("/api/system/readiness", 60000);
  return (
    <>
      <PageTitle
        eyebrow={t("MAINTENANCE")}
        title={t("Diagnostics")}
        description={t(
          "Component health, receiver recovery and correction quality.",
        )}
        action={
          <Button
            variant="outlined"
            onClick={() => {
              health.refresh();
              host.refresh();
              bt.refresh();
              readiness.refresh();
            }}
          >
            {t("Run checks")}
          </Button>
        }
      />
      <ResourceState resource={health} />
      <GridBox columns={3}>
        {Object.entries(health.data?.components || {}).map(([key, item]) => (
          <Panel
            key={key}
            title={
              {
                web: "Web interface",
                database: "Database",
                ntrip: "NTRIP server",
                receivers: "Receivers",
                rtcm: "Correction stream",
              }[key] || label(key)
            }
            action={<Status value={item.status} />}
          >
            <Typography variant="body2" color="text.secondary">
              {serverMessage(item.message)}
            </Typography>
          </Panel>
        ))}
      </GridBox>
      <Panel
        title={t("Receiver health")}
        caption={t(
          "RTCM becomes stale after 30 seconds without a valid frame. Checks refresh every 30 seconds.",
        )}
        sx={{
          mt: 3,
        }}
      >
        <DataTable
          rows={health.data?.stations || []}
          columns={[
            {
              key: "name",
              label: t("Receiver"),
            },
            {
              key: "rtcm",
              label: t("RTCM"),
              render: (r) => <Status value={r.rtcm} />,
            },
            {
              key: "last_frame_age_seconds",
              label: t("Last valid frame"),
              render: (r) =>
                r.last_frame_age_seconds == null
                  ? t("Never")
                  : t("{0} s ago", [r.last_frame_age_seconds]),
            },
            {
              key: "frames_parsed",
              label: t("Valid frames"),
              render: (r) => number(r.frames_parsed),
            },
            {
              key: "crc_failures",
              label: t("CRC failures"),
              render: (r) => number(r.crc_failures),
            },
            {
              key: "message",
              label: t("Details"),
              render: (r) => serverMessage(r.message),
            },
          ]}
        />
      </Panel>
      <GridBox>
        <Panel
          title={t("Connection recovery")}
          sx={{
            mt: 3,
          }}
        >
          <ResourceState resource={bt} />
          {(bt.data?.stations || []).map((s) => (
            <Box
              key={s.id}
              sx={{
                mb: 3,
              }}
            >
              <Typography fontWeight={600}>{s.name}</Typography>
              <KeyValues
                data={{
                  connection: s.connection_type,
                  connected: s.connected,
                  last_error: s.last_error,
                  reconnects: s.reconnect_count,
                  last_attempt: date(s.last_attempt),
                  signal: s.rssi == null ? null : `${s.rssi} dBm`,
                }}
              />
            </Box>
          ))}
        </Panel>
        <Panel
          title={t("Host information")}
          sx={{
            mt: 3,
          }}
        >
          <ResourceState resource={host} />
          <KeyValues data={host.data?.system} />
          <KeyValues data={host.data?.resources} />
        </Panel>
      </GridBox>
      <Panel
        title={t("Field readiness")}
        sx={{
          mt: 3,
        }}
      >
        <ResourceState resource={readiness} />
        <Readiness data={readiness.data} />
      </Panel>
    </>
  );
}
export function Readiness({ data }) {
  if (!data) return null;
  if (Array.isArray(data.stations))
    return (
      <Stack spacing={2}>
        {(data.issues || []).length > 0 && (
          <Alert severity="warning">
            {data.issues
              .map((issue) => {
                const station = data.stations.find((s) =>
                  issue.startsWith(`${s.name}: `),
                );
                return station
                  ? `${station.name}: ${serverMessage(issue.slice(station.name.length + 2))}`
                  : serverMessage(issue);
              })
              .join(" · ")}
          </Alert>
        )}
        {data.stations.map((s) => (
          <Box key={s.id}>
            <Stack direction="row" justifyContent="space-between">
              <Typography fontWeight={600}>{s.name}</Typography>
              <Status
                value={s.ready ? "ok" : "warning"}
                text={s.ready ? t("Ready") : t("Needs attention")}
              />
            </Stack>
            <Typography variant="body2" color="text.secondary">
              {s.issues?.length
                ? s.issues.map(serverMessage).join(" · ")
                : t("{0} satellites \xB7 {1} rovers", [
                    s.satellites ?? "—",
                    s.rovers ?? 0,
                  ])}
            </Typography>
          </Box>
        ))}
      </Stack>
    );
  const rows = data.checks || data.items;
  if (Array.isArray(rows))
    return (
      <Stack spacing={1.5}>
        {rows.map((row, i) => (
          <Alert
            key={i}
            severity={
              ["ok", "ready", "pass"].includes(row.status)
                ? "success"
                : row.status === "error"
                  ? "error"
                  : "warning"
            }
          >
            {row.name || row.label || row.title}: {row.message || row.detail}
          </Alert>
        ))}
      </Stack>
    );
  return <KeyValues data={data} />;
}
export function Rovers() {
  const { canEdit } = useContext(Session),
    resource = useResource("/api/rovers"),
    mounts = useResource("/api/mountpoints");
  const schema = [
    {
      key: "username",
      required: true,
    },
    {
      key: "password",
      type: "password",
      required: false,
      help: t(
        "Required for new rovers. Leave blank when editing to keep the password.",
      ),
    },
    {
      key: "email",
      type: "email",
    },
    {
      key: "max_conn",
      label: t("Maximum connections"),
      type: "number",
      min: 1,
    },
    {
      key: "mountpoints_text",
      label: t("Allowed mountpoints"),
      wide: true,
      help: t("Comma-separated names. Available: {0}. Leave blank for all.", [
        (mounts.data || []).map((m) => m.name).join(", ") || "none",
      ]),
    },
    {
      key: "expires_date",
      label: t("Expires on"),
      type: "date",
      help: t("Leave blank for no expiration."),
    },
    {
      key: "is_active",
      label: t("Enabled"),
      type: "boolean",
    },
  ];
  const data = resource.data?.map((r) => ({
    ...r,
    mountpoints_text: r.mountpoints.join(", "),
    expires_date: r.expires
      ? new Date(r.expires * 1000).toISOString().slice(0, 10)
      : "",
  }));
  return (
    <CrudPage
      title={t("Rovers")}
      description={t("Field accounts and access to correction streams.")}
      resource={{
        ...resource,
        data,
      }}
      schema={schema}
      defaults={{
        max_conn: 1,
        is_active: true,
      }}
      base="/api/rovers"
      canEdit={canEdit}
      prepare={(r) => ({
        username: r.username,
        password: r.password || "",
        email: r.email || "",
        max_conn: r.max_conn,
        is_active: r.is_active,
        mountpoints: (r.mountpoints_text || "")
          .split(",")
          .map((v) => v.trim())
          .filter(Boolean),
        expires: r.expires_date
          ? Math.floor(new Date(`${r.expires_date}T23:59:59`).getTime() / 1000)
          : 0,
      })}
      columns={[
        {
          key: "username",
          label: t("Rover"),
        },
        {
          key: "is_active",
          label: t("Access"),
          render: (r) => (
            <Status value={r.is_active ? "enabled" : "disabled"} />
          ),
        },
        {
          key: "active_conn",
          label: t("Connections"),
          render: (r) => `${r.active_conn} / ${r.max_conn}`,
        },
        {
          key: "mountpoints_text",
          label: t("Mountpoints"),
          render: (r) => r.mountpoints_text || "All",
        },
        {
          key: "expires",
          render: (r) => (r.expires ? date(r.expires) : t("Never")),
        },
        {
          key: "last_connection",
          render: (r) => date(r.last_connection),
        },
      ]}
    />
  );
}
export function Mountpoints() {
  const { canEdit } = useContext(Session),
    resource = useResource("/api/mountpoints"),
    stations = useResource("/api/base_stations");
  return (
    <CrudPage
      title={t("Mountpoints")}
      description={t("Publish each base station as a named NTRIP stream.")}
      resource={{
        ...resource,
        data: resource.data?.map((r) => ({
          ...r,
          rtcm_json: JSON.stringify(r.rtcm_settings || {}, null, 2),
        })),
      }}
      base="/api/mountpoints"
      canEdit={canEdit}
      defaults={{
        is_active: true,
        rtcm_json: "{}",
      }}
      schema={[
        {
          key: "name",
          required: true,
          help: t("Letters, numbers, underscores and dashes."),
        },
        {
          key: "base_id",
          label: t("Base station"),
          required: true,
          options: (stations.data || []).map((s) => ({
            value: s.id,
            label: s.name,
            literal: true,
          })),
        },
        {
          key: "description",
          wide: true,
        },
        {
          key: "is_active",
          label: t("Enabled"),
          type: "boolean",
        },
        {
          key: "rtcm_json",
          label: t("RTCM overrides (JSON)"),
          type: "multiline",
          wide: true,
          help: t(
            'Optional message overrides, for example {"1077": true}. Empty object uses global settings.',
          ),
        },
      ]}
      prepare={(r) => {
        const settings = JSON.parse(r.rtcm_json || "{}");
        if (
          !settings ||
          Array.isArray(settings) ||
          typeof settings !== "object" ||
          Object.values(settings).some((v) => typeof v !== "boolean")
        )
          throw new Error(
            "RTCM overrides must be an object with boolean values.",
          );
        return {
          name: r.name,
          base_id: r.base_id,
          description: r.description,
          is_active: r.is_active,
          rtcm_settings: settings,
        };
      }}
      columns={[
        {
          key: "name",
        },
        {
          key: "base_id",
          label: t("Base station"),
          render: (r) =>
            stations.data?.find((s) => s.id === r.base_id)?.name || r.base_id,
        },
        {
          key: "description",
        },
        {
          key: "is_active",
          label: t("Status"),
          render: (r) => (
            <Status value={r.is_active ? "enabled" : "disabled"} />
          ),
        },
      ]}
    />
  );
}
export function Logs() {
  const [level, setLevel] = useState(""),
    [module, setModule] = useState(""),
    [search, setSearch] = useState("");
  const params = new URLSearchParams({
    limit: "200",
    ...(level
      ? {
          level,
        }
      : {}),
    ...(module
      ? {
          module,
        }
      : {}),
  });
  const resource = useResource(`/api/logs?${params}`);
  return (
    <>
      <PageTitle
        title={t("Event logs")}
        eyebrow={t("MAINTENANCE")}
        description={t(
          "Connection events, receiver messages and administrative changes.",
        )}
        action={
          <Button variant="outlined" href={`/api/logs/export?${params}`}>
            {t("Export CSV")}
          </Button>
        }
      />
      <Panel>
        <Stack
          direction={{
            xs: "column",
            sm: "row",
          }}
          spacing={2}
          sx={{
            mb: 3,
          }}
        >
          <TextField
            select
            label={t("Level")}
            value={level}
            onChange={(e) => setLevel(e.target.value)}
            sx={{
              minWidth: 140,
            }}
          >
            {["", "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"].map((v) => (
              <MenuItem key={v} value={v}>
                {v || t("All levels")}
              </MenuItem>
            ))}
          </TextField>
          <TextField
            label={t("Module")}
            value={module}
            onChange={(e) => setModule(e.target.value)}
          />
          <TextField
            label={t("Search messages")}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            sx={{
              flex: 1,
            }}
          />
          <Button onClick={resource.refresh}>{t("Refresh")}</Button>
        </Stack>
        <ResourceState resource={resource} />
        <DataTable
          rows={(resource.data || []).filter((r) =>
            r.message.toLowerCase().includes(search.toLowerCase()),
          )}
          columns={[
            {
              key: "timestamp",
              label: t("Time"),
              render: (r) => date(r.timestamp),
              sx: {
                whiteSpace: "nowrap",
              },
            },
            {
              key: "level",
              render: (r) => <Status value={r.level} />,
            },
            {
              key: "module",
            },
            {
              key: "message",
              sx: {
                minWidth: 280,
                overflowWrap: "anywhere",
              },
            },
          ]}
          pageSize={25}
        />
      </Panel>
    </>
  );
}
export function Rtcm() {
  const { canEdit } = useContext(Session),
    messages = useResource("/api/rtcm/messages", 0),
    saved = useResource("/api/rtcm/settings", 0),
    presets = useResource("/api/rtcm/presets", 0);
  const [draft, setDraft] = useState(null),
    [presetName, setPresetName] = useState(""),
    [confirmation, setConfirmation] = useState(null),
    [savePreset, setSavePreset] = useState(false),
    [search, setSearch] = useState("");
  const action = useAction();
  useUnsavedChanges(!!draft && !action.busy);
  const defaults = Object.fromEntries(
    Object.values(messages.data || {})
      .flat()
      .map((m) => [m.type, m.enabled]),
  );
  const values = draft || {
    ...defaults,
    ...Object.fromEntries(
      (saved.data || []).map((m) => [m.msg_type, m.enabled]),
    ),
  };
  const reload = () => {
    setDraft(null);
    saved.refresh();
    presets.refresh();
  };
  return (
    <>
      <PageTitle
        title={t("RTCM messages")}
        description={t("Choose which correction messages are sent to rovers.")}
        action={
          canEdit && (
            <Button
              variant="contained"
              disabled={action.busy || !draft}
              onClick={() =>
                action.run(
                  () =>
                    api("/api/rtcm/settings/update", {
                      method: "POST",
                      body: {
                        settings: values,
                      },
                    }),
                  reload,
                )
              }
            >
              {t("Save changes")}
            </Button>
          )
        }
      />
      <Notice value={action.notice} />
      <ResourceState resource={messages} />
      <ResourceState resource={saved} />
      <ResourceState resource={presets} />
      <Panel
        title={t("Message presets")}
        sx={{
          mb: 3,
        }}
      >
        <Stack
          direction={{
            xs: "column",
            sm: "row",
          }}
          spacing={1.5}
        >
          <TextField
            select
            label={t("Saved preset")}
            value={presetName}
            onChange={(e) => setPresetName(e.target.value)}
            sx={{
              minWidth: 220,
            }}
          >
            <MenuItem value="">{t("Select a preset")}</MenuItem>
            {(presets.data?.presets || []).map((p) => (
              <MenuItem key={p.name} value={p.name}>
                {p.name} · {p.enabled_count}
                {t(" messages")}
              </MenuItem>
            ))}
          </TextField>
          {canEdit && (
            <>
              <Button
                disabled={!presetName}
                onClick={() =>
                  setConfirmation({
                    title: t("Apply {0}?", [presetName]),
                    url: "/api/rtcm/presets/apply",
                    body: {
                      name: presetName,
                    },
                  })
                }
              >
                {t("Apply")}
              </Button>
              <Button
                disabled={!presetName}
                color="error"
                onClick={() =>
                  setConfirmation({
                    title: t("Delete {0}?", [presetName]),
                    url: "/api/rtcm/presets/delete",
                    body: {
                      name: presetName,
                    },
                  })
                }
              >
                {t("Delete")}
              </Button>
              <Button onClick={() => setSavePreset(true)}>
                {t("Save as preset")}
              </Button>
              <Button
                color="warning"
                onClick={() =>
                  setConfirmation({
                    title: t("Restore default messages?"),
                    url: "/api/rtcm/settings/reset",
                    body: {},
                  })
                }
              >
                {t("Reset defaults")}
              </Button>
            </>
          )}
        </Stack>
      </Panel>
      <TextField
        label={t("Search message ID or description")}
        fullWidth
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        sx={{
          mb: 3,
        }}
      />
      <GridBox>
        {Object.entries(messages.data || {}).map(([group, items]) => {
          const filtered = items.filter((m) =>
            `${m.type} ${m.description}`
              .toLowerCase()
              .includes(search.toLowerCase()),
          );
          return filtered.length ? (
            <Panel
              key={group}
              title={group}
              action={
                canEdit && (
                  <Switch
                    inputProps={{
                      "aria-label": t("Enable all {0}", [group]),
                    }}
                    checked={items.every((m) => values[m.type])}
                    onChange={(e) =>
                      setDraft({
                        ...values,
                        ...Object.fromEntries(
                          items.map((m) => [m.type, e.target.checked]),
                        ),
                      })
                    }
                  />
                )
              }
            >
              <DataTable
                pageSize={10}
                rows={filtered.map((m) => ({
                  ...m,
                  id: m.type,
                }))}
                columns={[
                  {
                    key: "type",
                    label: t("ID"),
                  },
                  {
                    key: "description",
                    label: t("Message"),
                  },
                  {
                    key: "enabled",
                    label: t("Enabled"),
                    render: (m) => (
                      <Checkbox
                        disabled={!canEdit}
                        checked={!!values[m.type]}
                        inputProps={{
                          "aria-label": t("Message {0}", [m.type]),
                        }}
                        onChange={(e) =>
                          setDraft({
                            ...values,
                            [m.type]: e.target.checked,
                          })
                        }
                      />
                    ),
                  },
                ]}
              />
            </Panel>
          ) : null;
        })}
      </GridBox>
      {confirmation && (
        <Confirm
          title={confirmation.title}
          description={t("This changes the saved correction configuration.")}
          onClose={() => setConfirmation(null)}
          onConfirm={async () => {
            const r = await api(confirmation.url, {
              method: "POST",
              body: confirmation.body,
            });
            reload();
            return r;
          }}
        />
      )}
      {savePreset && (
        <FormDialog
          title={t("Save message preset")}
          schema={[
            {
              key: "name",
              required: true,
            },
          ]}
          initial={{}}
          onClose={() => setSavePreset(false)}
          onSubmit={async (v) => {
            const r = await api("/api/rtcm/presets/save", {
              method: "POST",
              body: {
                name: v.name,
                settings: values,
              },
            });
            presets.refresh();
            return r;
          }}
        />
      )}
      {draft && (
        <Alert
          severity="info"
          sx={{
            mt: 3,
          }}
        >
          {t("You have unsaved message changes.")}
        </Alert>
      )}
    </>
  );
}
