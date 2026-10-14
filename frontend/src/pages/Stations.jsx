import { t } from "../i18n";
import React, { useContext, useEffect, useRef, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Checkbox,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  MenuItem,
  Stack,
  Tab,
  Tabs,
  TextField,
  Typography,
} from "@mui/material";
import Add from "@mui/icons-material/Add";
import BluetoothSearching from "@mui/icons-material/BluetoothSearching";
import ArrowBack from "@mui/icons-material/ArrowBack";
import { Session } from "../session";
import { api } from "../api";
import { useAction, useResource, useUnsavedChanges } from "../hooks";
import {
  Confirm,
  DataTable,
  Empty,
  Fields,
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
const connectionFields = [
  {
    key: "name",
    label: "Station name",
    required: true,
  },
  {
    key: "connection_type",
    label: "Connection",
    options: [
      {
        value: "bluetooth",
        label: "Bluetooth Classic",
      },
      {
        value: "ble",
        label: "Bluetooth LE",
      },
      {
        value: "serial",
        label: "USB / serial",
      },
    ],
  },
  {
    key: "bt_mac",
    label: "Bluetooth address",
    required: true,
    when: (v) => v.connection_type !== "serial",
    help: "Example: AA:BB:CC:DD:EE:FF",
  },
  {
    key: "channel",
    label: "RFCOMM channel",
    type: "number",
    min: 1,
    max: 30,
    when: (v) => v.connection_type === "bluetooth",
  },
  {
    key: "gnss_port",
    label: "Serial device",
    required: true,
    when: (v) => v.connection_type === "serial",
    help: "Use /dev/serial/by-id/... when available.",
  },
  {
    key: "baudrate",
    label: "Baud rate",
    type: "number",
    min: 1,
  },
  {
    key: "receiver_brand",
    options: ["comnav", "unicore", "ublox", "generic_nmea"],
  },
  {
    key: "data_type",
    label: "Output format",
    options: ["RTCM3", "NMEA", "BOTH"],
  },
  {
    key: "output_interval",
    label: "Output interval (s)",
    type: "number",
    min: 1,
    max: 60,
  },
];
const positionFields = [
  {
    key: "operation_mode",
    options: ["base", "rover", "moving_base"],
  },
  {
    key: "position_mode",
    options: [
      {
        value: "auto",
        label: "Survey in",
      },
      {
        value: "manual",
        label: "Known position",
      },
    ],
  },
  {
    key: "survey_duration_sec",
    label: "Survey duration (s)",
    type: "number",
    min: 15,
    max: 300,
  },
  {
    key: "position_accuracy",
    label: "Position accuracy (m)",
    type: "number",
    min: 0.001,
  },
  {
    key: "manual_lat",
    label: "Latitude (°)",
    type: "number",
    min: -90,
    max: 90,
  },
  {
    key: "manual_lon",
    label: "Longitude (°)",
    type: "number",
    min: -180,
    max: 180,
  },
  {
    key: "manual_alt",
    label: "Altitude (m)",
    type: "number",
  },
  {
    key: "antenna_height",
    label: "Antenna height (m)",
    type: "number",
  },
  {
    key: "add_antenna_height",
    type: "boolean",
  },
  {
    key: "antenna_type",
  },
  {
    key: "antenna_serial",
  },
];
const commandFields = [
  {
    key: "data_bits",
    type: "number",
    min: 7,
    max: 8,
  },
  {
    key: "stop_bits",
    type: "number",
    min: 1,
    max: 2,
  },
  {
    key: "parity",
    options: ["N", "E", "O"],
  },
  {
    key: "command_strategy",
    options: ["generated", "overrides", "replace"],
    help: "Generated uses RTCM settings. Overrides appends custom commands. Replace uses custom commands.",
  },
  {
    key: "startup_commands",
    type: "multiline",
    wide: true,
    maxLength: 4000,
  },
  {
    key: "shutdown_commands",
    type: "multiline",
    wide: true,
    maxLength: 4000,
  },
];
const defaults = {
  name: "",
  connection_type: "bluetooth",
  bt_mac: "",
  channel: 1,
  gnss_port: "/dev/ttyACM0",
  baudrate: 115200,
  receiver_brand: "unicore",
  data_type: "RTCM3",
  output_interval: 1,
  operation_mode: "base",
  position_mode: "auto",
  survey_duration_sec: 30,
  position_accuracy: 1,
  manual_lat: 0,
  manual_lon: 0,
  manual_alt: 0,
  antenna_height: 0,
  add_antenna_height: false,
  command_strategy: "generated",
  startup_commands: "",
  shutdown_commands: "",
  data_bits: 8,
  stop_bits: 1,
  parity: "N",
};
export function stationPayload(value) {
  const payload = Object.fromEntries(
    [...connectionFields, ...positionFields, ...commandFields]
      .map((f) => [f.key, value[f.key]])
      .filter(([, v]) => v !== undefined),
  );
  if (payload.connection_type !== "serial") delete payload.gnss_port;
  return payload;
}
function StationEditor({ station, onClose, onSaved }) {
  const [value, setValue] = useState({
      ...defaults,
      ...station,
    }),
    [tab, setTab] = useState(0),
    [preview, setPreview] = useState(null),
    [ports, setPorts] = useState(null);
  const action = useAction();
  useUnsavedChanges(
    !action.busy &&
      JSON.stringify(value) !==
        JSON.stringify({
          ...defaults,
          ...station,
        }),
  );
  return (
    <Dialog
      open
      onClose={() => !action.busy && onClose()}
      maxWidth="md"
      fullWidth
    >
      <Box
        component="form"
        noValidate
        onSubmit={(e) => {
          e.preventDefault();
          action.run(
            () =>
              api(
                `/api/base_stations/${station.id ? station.id + "/update" : "create"}`,
                {
                  method: station.id ? "PUT" : "POST",
                  body: stationPayload(value),
                },
              ),
            () => {
              onSaved();
              onClose();
            },
          );
        }}
      >
        <DialogTitle>
          {station.id ? t("Edit base station") : t("Add base station")}
        </DialogTitle>
        <DialogContent dividers>
          <Notice value={action.notice} />
          <Tabs
            value={tab}
            onChange={(_, v) => setTab(v)}
            variant="scrollable"
            allowScrollButtonsMobile
            sx={{
              mb: 3,
            }}
          >
            <Tab label={t("Connection")} />
            <Tab label={t("Position & antenna")} />
            <Tab label={t("Receiver commands")} />
          </Tabs>
          {[connectionFields, positionFields, commandFields].map(
            (schema, i) => (
              <Box
                key={i}
                sx={{
                  display: tab === i ? "block" : "none",
                }}
              >
                <Fields
                  schema={schema}
                  value={value}
                  onChange={setValue}
                  disabled={action.busy}
                />
              </Box>
            ),
          )}
          {tab === 0 && value.connection_type === "serial" && (
            <Box
              sx={{
                mt: 2,
              }}
            >
              <Button
                disabled={action.busy}
                onClick={() =>
                  action.run(
                    () => api("/api/base_stations/serial_ports"),
                    (r) => setPorts(r.ports),
                  )
                }
              >
                {t("Find serial ports")}
              </Button>
              {ports?.map((p) => (
                <Button
                  key={p.device}
                  onClick={() =>
                    setValue({
                      ...value,
                      gnss_port: p.by_id || p.device,
                    })
                  }
                >
                  {p.label} · {p.device}
                </Button>
              ))}
            </Box>
          )}
          {tab === 2 && (
            <Box
              sx={{
                mt: 2,
              }}
            >
              <Button
                disabled={action.busy}
                onClick={() =>
                  action.run(
                    () =>
                      api("/api/base_stations/receiver_defaults", {
                        method: "POST",
                        body: stationPayload(value),
                      }),
                    setPreview,
                  )
                }
              >
                {t("Preview generated commands")}
              </Button>
              {preview && (
                <>
                  <Alert
                    severity="info"
                    sx={{
                      my: 2,
                    }}
                  >
                    {preview.message}
                  </Alert>
                  <Typography variant="subtitle2">{t("Startup")}</Typography>
                  <Code>
                    {preview.effective_startup_commands || t("No commands")}
                  </Code>
                  <Typography variant="subtitle2">{t("Shutdown")}</Typography>
                  <Code>
                    {preview.effective_shutdown_commands || t("No commands")}
                  </Code>
                </>
              )}
            </Box>
          )}
          <Typography
            variant="caption"
            color="text.secondary"
            sx={{
              display: "block",
              mt: 3,
            }}
          >
            {t(
              "Save stores the configuration. Use Apply configuration on the station page to send it to the receiver.",
            )}
          </Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={onClose} disabled={action.busy}>
            {t("Cancel")}
          </Button>
          <Button type="submit" disabled={action.busy} variant="contained">
            {action.busy ? t("Saving\u2026") : t("Save station")}
          </Button>
        </DialogActions>
      </Box>
    </Dialog>
  );
}
function Code({ children }) {
  return (
    <Box
      component="pre"
      sx={{
        p: 2,
        bgcolor: "action.hover",
        borderRadius: 2,
        fontSize: ".78rem",
        whiteSpace: "pre-wrap",
        overflowWrap: "anywhere",
        maxHeight: 350,
        overflow: "auto",
      }}
    >
      {children}
    </Box>
  );
}
function Scanner({ onAdd, onUpdated }) {
  const action = useAction(),
    [devices, setDevices] = useState(null),
    [confirm, setConfirm] = useState(null);
  return (
    <Panel
      title={t("Nearby Bluetooth devices")}
      caption={t("Discovery runs only when you request a scan.")}
      sx={{
        mb: 3,
      }}
      action={
        <Button
          startIcon={<BluetoothSearching />}
          disabled={action.busy}
          onClick={() =>
            action.run(
              () =>
                api("/api/bluetooth/scan", {
                  timeout: 45000,
                }),
              setDevices,
            )
          }
        >
          {action.busy ? t("Working\u2026") : t("Scan nearby")}
        </Button>
      }
    >
      <Notice value={action.notice} />
      {devices && (
        <DataTable
          rows={devices.map((d) => ({
            ...d,
            id: d.mac,
          }))}
          columns={[
            {
              key: "name",
            },
            {
              key: "mac",
              label: t("Address"),
            },
            {
              key: "rssi",
              label: t("Signal"),
              render: (d) => (d.rssi == null ? "—" : `${d.rssi} dBm`),
            },
            {
              key: "paired",
              render: (d) => <Status value={d.paired ? "yes" : "no"} />,
            },
          ]}
          actions={(d) => (
            <>
              <Button
                size="small"
                disabled={action.busy}
                onClick={() =>
                  action.run(
                    () =>
                      api("/api/bluetooth/connect", {
                        method: "POST",
                        body: {
                          mac: d.mac,
                        },
                        timeout: 45000,
                      }),
                    onUpdated,
                  )
                }
              >
                {t("Connect")}
              </Button>
              {!d.is_registered && (
                <Button
                  size="small"
                  onClick={() =>
                    onAdd({
                      ...defaults,
                      name: d.name || "",
                      bt_mac: d.mac,
                    })
                  }
                >
                  {t("Add")}
                </Button>
              )}
              <Button
                size="small"
                onClick={() =>
                  setConfirm({
                    device: d,
                    type: d.paired ? "unpair" : "pair",
                  })
                }
              >
                {d.paired ? t("Unpair") : t("Pair")}
              </Button>
              <Button
                size="small"
                onClick={() =>
                  setConfirm({
                    device: d,
                    type: "disconnect",
                  })
                }
              >
                {t("Disconnect")}
              </Button>
              <Button
                size="small"
                disabled={action.busy}
                onClick={() =>
                  action.run(() =>
                    api("/api/bluetooth/test", {
                      method: "POST",
                      body: {
                        mac: d.mac,
                        channel: 1,
                      },
                      timeout: 45000,
                    }),
                  )
                }
              >
                {t("Test")}
              </Button>
            </>
          )}
        />
      )}
      {confirm && (
        <Confirm
          title={`${label(confirm.type)} ${confirm.device.name || confirm.device.mac}?`}
          description={t(
            "Changing the Bluetooth connection may interrupt corrections from this receiver.",
          )}
          onClose={() => setConfirm(null)}
          onConfirm={async () => {
            const r = await api(`/api/bluetooth/${confirm.type}`, {
              method: "POST",
              body: {
                mac: confirm.device.mac,
              },
              timeout: 45000,
            });
            onUpdated();
            action.setNotice({
              severity: "info",
              text: r.message,
            });
            return r;
          }}
        />
      )}
    </Panel>
  );
}
export default function Stations() {
  const id = Number(location.pathname.split("/")[2]);
  return id ? <StationDetail id={id} /> : <StationList />;
}
function StationList() {
  const { canEdit } = useContext(Session),
    resource = useResource("/api/base_stations"),
    live = useResource("/api/bluetooth/status", 15000);
  const [editor, setEditor] = useState(null),
    [selected, setSelected] = useState([]),
    [deleting, setDeleting] = useState(null),
    [search, setSearch] = useState(""),
    [scanning, setScanning] = useState(false);
  const action = useAction();
  const refresh = () => {
    resource.refresh();
    live.refresh();
  };
  const rows = (resource.data || []).filter((s) =>
    s.name.toLowerCase().includes(search.toLowerCase()),
  );
  return (
    <>
      <PageTitle
        title={t("Base stations")}
        description={t("Receivers that supply your correction streams.")}
        action={
          canEdit && (
            <Stack direction="row" spacing={1}>
              <Button variant="outlined" onClick={() => setScanning(!scanning)}>
                {t("Bluetooth devices")}
              </Button>
              <Button
                variant="contained"
                startIcon={<Add />}
                onClick={() => setEditor(defaults)}
              >
                {t("Add station")}
              </Button>
            </Stack>
          )
        }
      />
      <ResourceState resource={resource} />
      <ResourceState resource={live} />
      <Notice value={action.notice} />
      {scanning && <Scanner onAdd={setEditor} onUpdated={refresh} />}
      <Panel>
        <Stack
          direction="row"
          spacing={2}
          alignItems="center"
          sx={{
            mb: 2,
          }}
        >
          <TextField
            label={t("Search stations")}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            sx={{
              flex: 1,
              maxWidth: 350,
            }}
          />
          {canEdit && selected.length > 0 && (
            <Button color="error" onClick={() => setDeleting(selected)}>
              {t("Delete selected (")}
              {selected.length})
            </Button>
          )}
          <Button onClick={refresh}>{t("Refresh")}</Button>
        </Stack>
        <DataTable
          rows={rows}
          columns={[
            ...(canEdit
              ? [
                  {
                    key: "select",
                    label: "",
                    render: (s) => (
                      <Checkbox
                        inputProps={{
                          "aria-label": t("Select {0}", [s.name]),
                        }}
                        checked={selected.includes(s.id)}
                        onChange={(e) =>
                          setSelected(
                            e.target.checked
                              ? [...selected, s.id]
                              : selected.filter((id) => id !== s.id),
                          )
                        }
                      />
                    ),
                  },
                ]
              : []),
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
              key: "connection_type",
              label: t("Connection"),
              render: (s) => label(s.connection_type),
            },
            {
              key: "bt_mac",
              label: t("Address / port"),
              render: (s) =>
                s.connection_type === "serial" ? s.gnss_port : s.bt_mac,
            },
            {
              key: "status",
              render: (s) => (
                <Status
                  value={
                    live.error
                      ? "unknown"
                      : live.data?.stations?.find((v) => v.id === s.id)
                            ?.connected
                        ? "connected"
                        : "disconnected"
                  }
                />
              ),
            },
            {
              key: "bytes_received",
              label: t("Received"),
              render: (s) => bytes(s.bytes_received),
            },
          ]}
          actions={
            canEdit
              ? (s) => (
                  <>
                    <Button size="small" onClick={() => setEditor(s)}>
                      {t("Edit")}
                    </Button>
                    {s.connection_type !== "serial" && (
                      <Button
                        size="small"
                        disabled={action.busy}
                        onClick={() =>
                          action.run(
                            () =>
                              api("/api/bluetooth/connect", {
                                method: "POST",
                                body: {
                                  mac: s.bt_mac,
                                },
                                timeout: 45000,
                              }),
                            refresh,
                          )
                        }
                      >
                        {t("Connect")}
                      </Button>
                    )}
                    <Button
                      size="small"
                      color="error"
                      onClick={() => setDeleting([s.id])}
                    >
                      {t("Delete")}
                    </Button>
                  </>
                )
              : undefined
          }
        />
      </Panel>
      {editor && (
        <StationEditor
          station={editor}
          onClose={() => setEditor(null)}
          onSaved={refresh}
        />
      )}
      {deleting && (
        <Confirm
          title={t("Delete {0} station(s)?", [deleting.length])}
          description={t(
            "This removes the station configuration and may affect its mountpoints. Active field work may be interrupted.",
          )}
          onClose={() => setDeleting(null)}
          onConfirm={async () => {
            const r =
              deleting.length === 1
                ? await api(`/api/base_stations/${deleting[0]}/delete`, {
                    method: "POST",
                  })
                : await api("/api/base_stations/bulk_delete", {
                    method: "POST",
                    body: {
                      ids: deleting,
                    },
                  });
            setSelected([]);
            refresh();
            return r;
          }}
        />
      )}
    </>
  );
}
function StationDetail({ id }) {
  const { canEdit } = useContext(Session),
    resource = useResource("/api/base_stations"),
    live = useResource("/api/bluetooth/status", 10000),
    health = useResource("/api/diagnostics", 15000);
  const [tab, setTab] = useState(0),
    [editor, setEditor] = useState(false),
    [confirm, setConfirm] = useState(null),
    [result, setResult] = useState(null);
  const action = useAction();
  const station = resource.data?.find((s) => s.id === id),
    current = live.data?.stations?.find((s) => s.id === id),
    telemetry = current?.telemetry || {},
    stream = current?.stream || {},
    check = health.data?.stations?.find((s) => s.id === id);
  const refresh = () => {
    resource.refresh();
    live.refresh();
    health.refresh();
  };
  return (
    <>
      <Button
        startIcon={<ArrowBack />}
        href="/base_stations"
        sx={{
          mb: 2,
        }}
      >
        {t("All base stations")}
      </Button>
      <PageTitle
        title={station?.name || t("Base station")}
        description={
          station
            ? `${label(station.connection_type)} · ${station.bt_mac || station.gnss_port}`
            : t("Loading receiver information\u2026")
        }
        action={
          canEdit && (
            <Stack direction="row" spacing={1}>
              <Button
                variant="outlined"
                disabled={!station}
                onClick={() => setEditor(true)}
              >
                {t("Edit station")}
              </Button>
              <Button
                variant="contained"
                disabled={!current?.connected || action.busy}
                onClick={() =>
                  setConfirm({
                    title: t("Apply receiver configuration?"),
                    description: t(
                      "This sends the saved configuration to the receiver. Its correction output may briefly change.",
                    ),
                    url: `/api/base_stations/${id}/apply_config`,
                    body: {},
                  })
                }
              >
                {t("Apply configuration")}
              </Button>
            </Stack>
          )
        }
      />
      <ResourceState resource={resource} />
      <ResourceState resource={live} />
      <ResourceState resource={health} />
      <Notice value={action.notice} />
      <GridBox columns={4}>
        <Metric
          label={t("Receiver")}
          value={
            live.error
              ? "Unknown"
              : current?.connected
                ? "Connected"
                : "Offline"
          }
          caption={check?.message || t("Waiting for receiver data")}
        />
        <Metric
          label={t("Corrections")}
          value={
            health.error
              ? "Unknown"
              : check?.rtcm === "ok"
                ? "Streaming"
                : label(check?.rtcm || "unknown")
          }
          caption={
            check?.last_frame_age_seconds != null
              ? t("Last frame {0} s ago", [check.last_frame_age_seconds])
              : t("No valid frame received")
          }
        />
        <Metric
          label={t("Satellites")}
          value={telemetry.satellites_used}
          caption={t("{0} visible", [telemetry.satellites_visible ?? "—"])}
        />
        <Metric
          label={t("Rover clients")}
          value={current?.rover_clients}
          caption={t("{0} received", [bytes(current?.bytes_received)])}
        />
      </GridBox>
      <Tabs
        value={tab}
        onChange={(_, v) => setTab(v)}
        variant="scrollable"
        allowScrollButtonsMobile
        sx={{
          my: 3,
        }}
      >
        <Tab label={t("Telemetry")} />
        <Tab label={t("Position & site points")} />
        <Tab label={t("Receiver console")} />
        <Tab label={t("Command history")} />
        <Tab label={t("Config versions")} />
      </Tabs>
      {tab === 0 && (
        <GridBox>
          <Panel title={t("GNSS telemetry")}>
            <KeyValues data={telemetry} />
          </Panel>
          <Stack spacing={2.5}>
            <Panel title={t("Receiver details")}>
              <KeyValues
                data={{
                  brand: station?.receiver_brand,
                  model: current?.receiver_model,
                  firmware: current?.firmware_version,
                  serial: current?.receiver_serial,
                  signal_dbm: current?.rssi,
                  reconnects: current?.reconnect_count,
                  last_error: current?.last_error,
                }}
              />
            </Panel>
            <Panel title={t("RTCM stream")}>
              <KeyValues data={stream} />
            </Panel>
          </Stack>
        </GridBox>
      )}
      {tab === 1 && <Position id={id} station={station} onUpdated={refresh} />}
      {tab === 2 && <Console id={id} canEdit={canEdit} />}
      {tab === 3 && <Commands id={id} />}
      {tab === 4 && <Versions id={id} onUpdated={refresh} />}
      {editor && station && (
        <StationEditor
          station={station}
          onClose={() => setEditor(false)}
          onSaved={refresh}
        />
      )}
      {confirm && (
        <Confirm
          {...confirm}
          onClose={() => setConfirm(null)}
          onConfirm={async () => {
            const r = await api(confirm.url, {
              method: "POST",
              body: confirm.body,
              timeout: 60000,
            });
            setResult(r);
            refresh();
            return r;
          }}
        />
      )}
      {result && (
        <Panel
          title={t("Configuration result")}
          sx={{
            mt: 3,
          }}
        >
          <Alert severity={result.success ? "success" : "warning"}>
            {result.message}
          </Alert>
          <KeyValues
            data={{
              sent_count: result.sent_count,
            }}
          />
          <DataTable
            rows={result.results || []}
            columns={[
              {
                key: "command",
              },
              {
                key: "status",
              },
              {
                key: "response",
              },
            ]}
          />
        </Panel>
      )}
    </>
  );
}
function Console({ id, canEdit }) {
  const [running, setRunning] = useState(false),
    [lines, setLines] = useState([]),
    [command, setCommand] = useState(""),
    [confirm, setConfirm] = useState(false),
    [error, setError] = useState(null),
    [results, setResults] = useState(null);
  const output = useRef();
  useEffect(() => {
    if (!running) return;
    setError(null);
    const source = new EventSource(`/api/base_stations/${id}/stream`);
    source.onmessage = (e) => setLines((old) => [...old.slice(-499), e.data]);
    source.onerror = (e) => {
      setError(
        e.data ||
          "Receiver stream disconnected. Start the console again when the connection is restored.",
      );
      source.close();
      setRunning(false);
    };
    return () => source.close();
  }, [running, id]);
  useEffect(() => {
    if (output.current) output.current.scrollTop = output.current.scrollHeight;
  }, [lines]);
  function download() {
    const url = URL.createObjectURL(
      new Blob([lines.join("\n")], {
        type: "text/plain",
      }),
    );
    const a = document.createElement("a");
    a.href = url;
    a.download = `receiver-${id}.txt`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  return (
    <Panel
      title={t("Receiver console")}
      caption={t(
        "Live receiver output. The console reads a shared buffer without consuming rover corrections.",
      )}
      action={
        <Stack direction="row">
          <Button onClick={() => setRunning(!running)}>
            {running ? t("Stop") : t("Start")}
          </Button>
          <Button onClick={() => setLines([])}>{t("Clear")}</Button>
          <Button disabled={!lines.length} onClick={download}>
            {t("Download")}
          </Button>
        </Stack>
      }
    >
      {error && (
        <Alert
          severity="warning"
          sx={{
            mb: 2,
          }}
        >
          {error}
        </Alert>
      )}
      <Box
        ref={output}
        component="pre"
        aria-label={t("Receiver output")}
        sx={{
          height: 320,
          overflow: "auto",
          bgcolor: "#12211d",
          color: "#b8d7c9",
          p: 2,
          borderRadius: 2,
          fontSize: ".75rem",
          whiteSpace: "pre-wrap",
          overflowWrap: "anywhere",
        }}
      >
        {lines.length
          ? lines.join("\n")
          : t("Start the console to view receiver output.")}
      </Box>
      {canEdit && (
        <Stack direction="row" spacing={1.5}>
          <TextField
            label={t("Receiver command")}
            value={command}
            onChange={(e) => setCommand(e.target.value)}
            fullWidth
          />
          <Button
            disabled={!command.trim()}
            variant="outlined"
            onClick={() => setConfirm(true)}
          >
            {t("Send")}
          </Button>
        </Stack>
      )}
      {confirm && (
        <Confirm
          title={t("Send receiver command?")}
          description={command}
          onClose={() => setConfirm(false)}
          onConfirm={async () => {
            const r = await api(`/api/base_stations/${id}/command_test`, {
              method: "POST",
              body: {
                phase: "manual",
                commands: command.split("\n").filter(Boolean),
              },
              timeout: 60000,
            });
            setResults(r);
            setCommand("");
            return r;
          }}
        />
      )}
      {results && (
        <>
          <Alert
            severity="info"
            sx={{
              mt: 2,
            }}
          >
            {results.message}
          </Alert>
          <DataTable
            rows={results.results || []}
            columns={[
              {
                key: "command",
              },
              {
                key: "status",
              },
              {
                key: "response",
              },
            ]}
          />
        </>
      )}
    </Panel>
  );
}
function Commands({ id }) {
  const resource = useResource(
    `/api/base_stations/${id}/command_log?limit=100`,
    15000,
  );
  return (
    <Panel
      title={t("Command history")}
      action={
        <Button href={`/api/base_stations/${id}/command_log/export`}>
          {t("Export CSV")}
        </Button>
      }
    >
      <ResourceState resource={resource} />
      <DataTable
        rows={
          Array.isArray(resource.data)
            ? resource.data
            : resource.data?.entries || resource.data?.items || []
        }
        columns={[
          {
            key: "ts",
            label: t("Time"),
            render: (r) => date(r.ts),
          },
          {
            key: "phase",
          },
          {
            key: "command",
          },
          {
            key: "response",
          },
        ]}
      />
    </Panel>
  );
}
function Versions({ id, onUpdated }) {
  const { canEdit } = useContext(Session),
    resource = useResource(`/api/base_stations/${id}/config_versions`, 0),
    [selected, setSelected] = useState(null),
    [restore, setRestore] = useState(false);
  const detail = useResource(
    selected ? `/api/base_stations/${id}/config_versions/${selected.id}` : null,
    0,
  );
  return (
    <Panel
      title={t("Configuration versions")}
      caption={t(
        "Restoring a version updates saved settings. Apply configuration separately to send them to the receiver.",
      )}
      action={<Button onClick={resource.refresh}>{t("Refresh")}</Button>}
    >
      <ResourceState resource={resource} />
      <DataTable
        rows={resource.data || []}
        columns={[
          {
            key: "version",
          },
          {
            key: "source",
          },
          {
            key: "created_by",
            label: t("Author"),
          },
          {
            key: "created_at",
            label: t("Saved"),
            render: (r) => date(r.created_at),
          },
          {
            key: "note",
          },
        ]}
        actions={(r) => (
          <Button size="small" onClick={() => setSelected(r)}>
            {t("View changes")}
          </Button>
        )}
      />
      {selected && (
        <Dialog open maxWidth="md" fullWidth onClose={() => setSelected(null)}>
          <DialogTitle>
            {t("Version ")}
            {selected.version}
          </DialogTitle>
          <DialogContent dividers>
            <ResourceState resource={detail} />
            <DataTable
              rows={Object.entries(detail.data?.diff_vs_current || {}).map(
                ([key, v]) => ({
                  id: key,
                  field: label(key),
                  current: String(v.current ?? ""),
                  saved: String(v.version ?? ""),
                }),
              )}
              empty={t("No differences from the saved configuration")}
              columns={[
                {
                  key: "field",
                },
                {
                  key: "current",
                },
                {
                  key: "saved",
                  label: t("This version"),
                },
              ]}
            />
            <KeyValues data={detail.data?.config} />
          </DialogContent>
          <DialogActions>
            <Button onClick={() => setSelected(null)}>{t("Close")}</Button>
            {canEdit && (
              <Button variant="contained" onClick={() => setRestore(true)}>
                {t("Restore version")}
              </Button>
            )}
          </DialogActions>
        </Dialog>
      )}
      {restore && (
        <Confirm
          title={t("Restore version {0}?", [selected.version])}
          description={t("This replaces the saved receiver configuration.")}
          onClose={() => setRestore(false)}
          onConfirm={async () => {
            const r = await api(
              `/api/base_stations/${id}/config_versions/${selected.id}/restore`,
              {
                method: "POST",
              },
            );
            resource.refresh();
            onUpdated();
            setSelected(null);
            return r;
          }}
        />
      )}
    </Panel>
  );
}
const pointFields = [
  {
    key: "name",
    required: true,
  },
  {
    key: "description",
  },
  {
    key: "latitude",
    type: "number",
    required: true,
    min: -90,
    max: 90,
  },
  {
    key: "longitude",
    type: "number",
    required: true,
    min: -180,
    max: 180,
  },
  {
    key: "altitude",
    label: "Altitude (m)",
    type: "number",
  },
  {
    key: "antenna_height",
    label: "Antenna height (m)",
    type: "number",
  },
  {
    key: "add_antenna_height",
    type: "boolean",
  },
];
function Position({ id, station, onUpdated }) {
  const { canEdit } = useContext(Session),
    [hours, setHours] = useState(24),
    [editor, setEditor] = useState(null),
    [confirm, setConfirm] = useState(null);
  const history = useResource(
      `/api/base_stations/${id}/position_history?hours=${hours}`,
      60000,
    ),
    points = useResource("/api/site_points", 0);
  const samples = history.data?.samples || [],
    offsets = samples.filter((s) => s.offset_m != null),
    max = Math.max(0.01, ...offsets.map((s) => s.offset_m));
  return (
    <Stack spacing={3}>
      <Panel
        title={t("Position stability")}
        caption={t("Maximum offset: {0} m \xB7 Mean offset: {1} m", [
          history.data?.max_offset_m?.toFixed(3) ?? "—",
          history.data?.mean_offset_m?.toFixed(3) ?? "—",
        ])}
        action={
          <TextField
            select
            label={t("Period")}
            value={hours}
            onChange={(e) => setHours(e.target.value)}
            sx={{
              minWidth: 130,
            }}
          >
            {[1, 6, 24, 72, 168].map((h) => (
              <MenuItem key={h} value={h}>
                {h}
                {t(" hours")}
              </MenuItem>
            ))}
          </TextField>
        }
      >
        <ResourceState resource={history} />
        {offsets.length > 1 && (
          <Box
            component="svg"
            role="img"
            aria-label={t("Position offset in metres over time")}
            viewBox="0 0 700 160"
            sx={{
              width: "100%",
              height: 160,
              color: "primary.main",
              my: 2,
            }}
          >
            <line
              x1="20"
              y1="140"
              x2="680"
              y2="140"
              stroke="currentColor"
              opacity=".2"
            />
            <polyline
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              points={offsets
                .map(
                  (s, i) =>
                    `${20 + (660 * i) / (offsets.length - 1)},${140 - (s.offset_m / max) * 115}`,
                )
                .join(" ")}
            />
            <text x="20" y="14" fontSize="11" fill="currentColor">
              {max.toFixed(3)}
              {t(" m")}
            </text>
            <text x="20" y="157" fontSize="10" fill="currentColor">
              {date(offsets[0].ts)}
            </text>
            <text
              x="680"
              y="157"
              textAnchor="end"
              fontSize="10"
              fill="currentColor"
            >
              {date(offsets.at(-1).ts)}
            </text>
          </Box>
        )}
        <DataTable
          rows={[...samples].reverse()}
          columns={[
            {
              key: "ts",
              label: t("Time"),
              render: (s) => date(s.ts),
            },
            {
              key: "latitude",
            },
            {
              key: "longitude",
            },
            {
              key: "altitude",
            },
            {
              key: "offset_m",
              label: t("Offset (m)"),
            },
            {
              key: "satellites",
            },
            {
              key: "hdop",
              label: t("HDOP"),
            },
          ]}
        />
      </Panel>
      <Panel
        title={t("Saved site points")}
        caption={t("Known coordinates you can reuse for a base station.")}
        action={
          canEdit && (
            <Button
              onClick={() =>
                setEditor({
                  name: "",
                  latitude: station?.manual_lat || 0,
                  longitude: station?.manual_lon || 0,
                  altitude: station?.manual_alt || 0,
                  antenna_height: station?.antenna_height || 0,
                  add_antenna_height: station?.add_antenna_height || false,
                })
              }
            >
              {t("Save a point")}
            </Button>
          )
        }
      >
        <ResourceState resource={points} />
        <DataTable
          rows={points.data || []}
          columns={[
            {
              key: "name",
            },
            {
              key: "latitude",
            },
            {
              key: "longitude",
            },
            {
              key: "altitude",
              label: t("Altitude (m)"),
            },
          ]}
          actions={
            canEdit
              ? (p) => (
                  <>
                    <Button onClick={() => setEditor(p)}>{t("Edit")}</Button>
                    <Button
                      onClick={() =>
                        setConfirm({
                          title: t("Use {0}?", [p.name]),
                          url: `/api/site_points/${p.id}/apply/${id}`,
                          description: t(
                            "Updates the saved base position. Apply configuration separately to send it to the receiver.",
                          ),
                        })
                      }
                    >
                      {t("Use point")}
                    </Button>
                    <Button
                      color="error"
                      onClick={() =>
                        setConfirm({
                          title: t("Delete {0}?", [p.name]),
                          url: `/api/site_points/${p.id}/delete`,
                          description: t(
                            "Removes this point from your saved coordinates.",
                          ),
                        })
                      }
                    >
                      {t("Delete")}
                    </Button>
                  </>
                )
              : undefined
          }
        />
      </Panel>
      {editor && (
        <FormDialog
          title={t("Site point")}
          schema={pointFields.map((f) =>
            f.key === "name" && editor.id
              ? {
                  ...f,
                  disabled: true,
                }
              : f,
          )}
          initial={editor}
          onClose={() => setEditor(null)}
          onSubmit={async (v) => {
            const r = await api("/api/site_points/save", {
              method: "POST",
              body: v,
            });
            points.refresh();
            return r;
          }}
        />
      )}
      {confirm && (
        <Confirm
          {...confirm}
          onClose={() => setConfirm(null)}
          onConfirm={async () => {
            const r = await api(confirm.url, {
              method: "POST",
            });
            points.refresh();
            onUpdated();
            return r;
          }}
        />
      )}
    </Stack>
  );
}
