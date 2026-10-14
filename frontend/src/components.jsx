import { t, getLocale } from "./i18n";
import React, { useState } from "react";
import {
  Alert,
  Box,
  Button,
  Chip,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Divider,
  FormControlLabel,
  LinearProgress,
  MenuItem,
  Paper,
  Stack,
  Switch,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TablePagination,
  TableRow,
  TextField,
  Typography,
} from "@mui/material";
import { api } from "./api";
import { useAction, useUnsavedChanges } from "./hooks";
export const label = (value) =>
  t(
    String(value)
      .replaceAll("_", " ")
      .replace(/\b\w/g, (c) => c.toUpperCase()),
  );
export const date = (value) =>
  value
    ? new Date(typeof value === "number" ? value * 1000 : value).toLocaleString(
        getLocale(),
      )
    : "—";
export const number = (value) =>
  value == null ? "—" : Number(value).toLocaleString(getLocale());
export const bytes = (value) =>
  value == null
    ? "—"
    : value < 1024
      ? `${value} B`
      : value < 1048576
        ? `${(value / 1024).toFixed(1)} KiB`
        : value < 1073741824
          ? `${(value / 1048576).toFixed(1)} MiB`
          : `${(value / 1073741824).toFixed(1)} GiB`;
export const bool = (value) =>
  value === true ||
  ["true", "1", "yes", "on"].includes(String(value).toLowerCase());
export function Status({ value, text }) {
  const key = String(value ?? "unknown").toLowerCase();
  const color = [
    "ok",
    "connected",
    "active",
    "enabled",
    "success",
    "running",
    "info",
    "true",
  ].includes(key)
    ? "success"
    : ["error", "failed", "critical"].includes(key)
      ? "error"
      : ["warning", "stale", "waiting", "disconnected", "unavailable"].includes(
            key,
          )
        ? "warning"
        : "default";
  return (
    <Chip
      size="small"
      color={color}
      variant="outlined"
      label={t(text) || label(key)}
    />
  );
}
export function Notice({ value }) {
  return (
    value && (
      <Alert
        sx={{
          mb: 2,
        }}
        severity={value.severity || "error"}
      >
        {t(value.text || value.message)}
        {value.status === 401 && (
          <Button href="/login" size="small">
            {t("Sign in")}
          </Button>
        )}
      </Alert>
    )
  );
}
export function ResourceState({ resource }) {
  return (
    <>
      {resource.loading && (
        <LinearProgress
          sx={{
            mb: 2,
          }}
        />
      )}
      {resource.error && (
        <Notice
          value={{
            text:
              t(resource.error.message) +
              (resource.data ? t(" Displaying the last received data.") : ""),
            status: resource.error.status,
          }}
        />
      )}
    </>
  );
}
export function PageTitle({
  eyebrow = "WORKSPACE",
  title,
  description,
  action,
}) {
  return (
    <Stack
      direction={{
        xs: "column",
        sm: "row",
      }}
      justifyContent="space-between"
      alignItems={{
        xs: "stretch",
        sm: "center",
      }}
      spacing={2}
      sx={{
        mb: 3.5,
      }}
    >
      <Box>
        <Typography variant="overline" color="primary">
          {t(eyebrow)}
        </Typography>
        <Typography variant="h4" component="h1">
          {title}
        </Typography>
        {description && (
          <Typography
            color="text.secondary"
            sx={{
              mt: 0.7,
            }}
          >
            {t(description)}
          </Typography>
        )}
      </Box>
      {action}
    </Stack>
  );
}
export function Panel({ title, caption, action, children, sx }) {
  return (
    <Paper
      variant="outlined"
      sx={{
        p: {
          xs: 2,
          md: 3,
        },
        ...sx,
      }}
    >
      {title && (
        <Stack
          direction="row"
          alignItems="center"
          justifyContent="space-between"
          spacing={2}
          sx={{
            mb: 2,
          }}
        >
          <Box>
            <Typography variant="h6">{t(title)}</Typography>
            {caption && (
              <Typography variant="body2" color="text.secondary">
                {t(caption)}
              </Typography>
            )}
          </Box>
          {action}
        </Stack>
      )}
      {children}
    </Paper>
  );
}
export function Metric({ label: name, value, caption, icon }) {
  return (
    <Panel>
      <Stack direction="row" justifyContent="space-between">
        <Typography variant="body2" color="text.secondary">
          {t(name)}
        </Typography>
        <Box color="primary.main">{icon}</Box>
      </Stack>
      <Typography
        variant="h3"
        sx={{
          my: 1,
          fontVariantNumeric: "tabular-nums",
          fontSize: {
            xs: String(value ?? "").length > 8 ? "1.2rem" : "1.75rem",
            md: String(value ?? "").length > 8 ? "1.75rem" : "2.25rem",
          },
        }}
      >
        {t(value) ?? "—"}
      </Typography>
      <Typography variant="body2" color="text.secondary">
        {t(caption)}
      </Typography>
    </Panel>
  );
}
export function GridBox({ children, columns = 2 }) {
  return (
    <Box
      sx={{
        display: "grid",
        gap: 2.5,
        gridTemplateColumns: {
          xs: columns === 4 ? "repeat(2, minmax(0, 1fr))" : "1fr",
          md: `repeat(${columns}, minmax(0, 1fr))`,
        },
      }}
    >
      {children}
    </Box>
  );
}
export function Empty({
  title = "Nothing here yet",
  text = "New items will appear here.",
}) {
  return (
    <Box
      sx={{
        py: 5,
        textAlign: "center",
      }}
    >
      <Typography variant="h6">{t(title)}</Typography>
      <Typography
        color="text.secondary"
        sx={{
          mt: 1,
        }}
      >
        {t(text)}
      </Typography>
    </Box>
  );
}
export function DataTable({
  rows = [],
  columns,
  empty,
  actions,
  pageSize = 10,
}) {
  const [page, setPage] = useState(0);
  const safePage = Math.min(
    page,
    Math.max(0, Math.ceil(rows.length / pageSize) - 1),
  );
  return (
    <>
      <TableContainer>
        <Table size="small">
          <TableHead>
            <TableRow>
              {columns.map((col) => (
                <TableCell key={col.key}>
                  {t(col.label) || label(col.key)}
                </TableCell>
              ))}
              {actions && <TableCell align="right">{t("Actions")}</TableCell>}
            </TableRow>
          </TableHead>
          <TableBody>
            {rows
              .slice(safePage * pageSize, (safePage + 1) * pageSize)
              .map((row, i) => (
                <TableRow key={row.id ?? row.name ?? i} hover>
                  {columns.map((col) => (
                    <TableCell key={col.key} sx={col.sx}>
                      {col.render
                        ? col.render(row)
                        : String(row[col.key] ?? "—")}
                    </TableCell>
                  ))}
                  {actions && (
                    <TableCell align="right">
                      <Stack
                        direction="row"
                        justifyContent="flex-end"
                        spacing={0.5}
                      >
                        {actions(row)}
                      </Stack>
                    </TableCell>
                  )}
                </TableRow>
              ))}
          </TableBody>
        </Table>
      </TableContainer>
      {!rows.length && <Empty title={empty || t("No records")} />}
      {rows.length > pageSize && (
        <TablePagination
          component="div"
          count={rows.length}
          page={safePage}
          rowsPerPage={pageSize}
          rowsPerPageOptions={[pageSize]}
          onPageChange={(_, n) => setPage(n)}
        />
      )}
    </>
  );
}
export function Fields({ schema, value, onChange, disabled }) {
  return (
    <Box
      sx={{
        display: "grid",
        gridTemplateColumns: {
          xs: "1fr",
          sm: "repeat(2, minmax(0,1fr))",
        },
        gap: 2.5,
      }}
    >
      {schema
        .filter((f) => !f.when || f.when(value))
        .map((f) => (
          <Box
            key={f.key}
            sx={{
              gridColumn: f.wide ? "1 / -1" : undefined,
            }}
          >
            {f.type === "boolean" ? (
              <FormControlLabel
                control={
                  <Switch
                    checked={bool(value[f.key])}
                    disabled={disabled || f.disabled}
                    onChange={(e) =>
                      onChange({
                        ...value,
                        [f.key]: e.target.checked,
                      })
                    }
                  />
                }
                label={t(f.label) || label(f.key)}
              />
            ) : (
              <TextField
                fullWidth
                label={t(f.label) || label(f.key)}
                name={f.key}
                value={value[f.key] ?? ""}
                disabled={disabled || f.disabled}
                onChange={(e) =>
                  onChange({
                    ...value,
                    [f.key]:
                      f.type === "number" && e.target.value !== ""
                        ? Number(e.target.value)
                        : e.target.value,
                  })
                }
                type={
                  f.options
                    ? undefined
                    : f.type === "multiline"
                      ? "text"
                      : f.type || "text"
                }
                select={!!f.options}
                multiline={f.type === "multiline"}
                minRows={f.type === "multiline" ? 3 : undefined}
                required={f.required}
                helperText={t(f.help)}
                autoComplete={
                  f.type === "password" ? "new-password" : undefined
                }
                slotProps={{
                  htmlInput: {
                    min: f.min,
                    max: f.max,
                    step: f.type === "number" ? "any" : undefined,
                    maxLength: f.maxLength,
                  },
                }}
              >
                {f.options?.map((option) => (
                  <MenuItem
                    key={option.value ?? option}
                    value={option.value ?? option}
                  >
                    {option.literal
                      ? option.label
                      : (t(option.label) ?? label(option))}
                  </MenuItem>
                ))}
              </TextField>
            )}
          </Box>
        ))}
    </Box>
  );
}
export function FormDialog({
  title,
  schema,
  initial,
  onClose,
  onSubmit,
  children,
  submitLabel = "Save changes",
}) {
  const [value, setValue] = useState(initial || {});
  const action = useAction();
  useUnsavedChanges(
    !action.busy && JSON.stringify(value) !== JSON.stringify(initial || {}),
  );
  return (
    <Dialog
      open
      onClose={() => !action.busy && onClose()}
      maxWidth="md"
      fullWidth
      component="section"
    >
      <Box
        component="form"
        onSubmit={(e) => {
          e.preventDefault();
          action.run(() => onSubmit(value), onClose);
        }}
      >
        <DialogTitle>{t(title)}</DialogTitle>
        <DialogContent dividers>
          <Notice value={action.notice} />
          {children}
          <Fields
            schema={schema}
            value={value}
            onChange={setValue}
            disabled={action.busy}
          />
        </DialogContent>
        <DialogActions>
          <Button disabled={action.busy} onClick={onClose}>
            {t("Cancel")}
          </Button>
          <Button type="submit" variant="contained" disabled={action.busy}>
            {action.busy ? t("Saving\u2026") : t(submitLabel)}
          </Button>
        </DialogActions>
      </Box>
    </Dialog>
  );
}
export function Confirm({
  title,
  description,
  onClose,
  onConfirm,
  word,
  password = false,
  children,
}) {
  const [typed, setTyped] = useState(""),
    [passphrase, setPassphrase] = useState("");
  const action = useAction();
  return (
    <Dialog
      open
      onClose={() => !action.busy && onClose()}
      maxWidth="sm"
      fullWidth
    >
      <DialogTitle>{t(title)}</DialogTitle>
      <DialogContent>
        <Notice value={action.notice} />
        <Typography
          sx={{
            mb: 2,
          }}
        >
          {t(description)}
        </Typography>
        {children}
        {password && (
          <TextField
            fullWidth
            type="password"
            label={t("Backup passphrase")}
            value={passphrase}
            onChange={(e) => setPassphrase(e.target.value)}
            helperText={t("Leave blank to use the stored passphrase.")}
            sx={{
              mb: 2,
            }}
          />
        )}
        {word && (
          <TextField
            autoFocus
            fullWidth
            label={t("Type {0} to confirm", [word])}
            value={typed}
            onChange={(e) => setTyped(e.target.value)}
          />
        )}
      </DialogContent>
      <DialogActions>
        <Button disabled={action.busy} onClick={onClose}>
          {t("Cancel")}
        </Button>
        <Button
          variant="contained"
          color="error"
          disabled={action.busy || (word && typed !== word)}
          onClick={() => action.run(() => onConfirm(passphrase), onClose)}
        >
          {action.busy ? t("Working\u2026") : t("Confirm")}
        </Button>
      </DialogActions>
    </Dialog>
  );
}
function detailValue(value, key = "") {
  if (value == null) return "—";
  if (typeof value === "boolean") return value ? t("Yes") : t("No");
  if (key.endsWith("_bytes") && typeof value === "number") return bytes(value);
  if (Array.isArray(value))
    return value.map((item) => detailValue(item)).join(", ");
  if (typeof value === "object")
    return Object.entries(value)
      .map(([k, v]) => `${label(k)}: ${detailValue(v, k)}`)
      .join(" · ");
  return String(value);
}
export function KeyValues({ data }) {
  return (
    <Box
      component="dl"
      sx={{
        m: 0,
      }}
    >
      {Object.entries(data || {}).map(([key, value]) => (
        <Box
          key={key}
          sx={{
            display: "grid",
            gridTemplateColumns: "minmax(120px, 1fr) 2fr",
            gap: 2,
            py: 1.2,
            borderBottom: "1px solid",
            borderColor: "divider",
          }}
        >
          <Typography component="dt" variant="body2" color="text.secondary">
            {label(key)}
          </Typography>
          <Typography
            component="dd"
            variant="body2"
            sx={{
              m: 0,
              overflowWrap: "anywhere",
            }}
          >
            {detailValue(value, key)}
          </Typography>
        </Box>
      ))}
    </Box>
  );
}
export function CrudPage({
  title,
  description,
  resource,
  schema,
  defaults,
  columns,
  base,
  canEdit,
  extra,
  prepare = (value) => value,
  customSave,
}) {
  const [editing, setEditing] = useState(null),
    [deleting, setDeleting] = useState(null),
    [search, setSearch] = useState("");
  const rows = (resource.data || []).filter((row) =>
    `${row.name || ""} ${row.username || ""} ${row.description || ""}`
      .toLowerCase()
      .includes(search.toLowerCase()),
  );
  return (
    <>
      <PageTitle
        title={t(title)}
        description={t(description)}
        action={
          canEdit && (
            <Button
              variant="contained"
              onClick={() =>
                setEditing({
                  ...defaults,
                })
              }
            >
              {t("Add")}{" "}
              {base === "/api/rovers"
                ? t("rover")
                : base === "/api/mountpoints"
                  ? t("mountpoint")
                  : t("item")}
            </Button>
          )
        }
      />
      <ResourceState resource={resource} />
      {extra}
      <Panel>
        <Stack
          direction="row"
          justifyContent="space-between"
          sx={{
            mb: 2,
          }}
        >
          <TextField
            size="small"
            label={t("Search {0}", [title.toLowerCase()])}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
          <Button onClick={resource.refresh}>{t("Refresh")}</Button>
        </Stack>
        <DataTable
          rows={rows}
          columns={columns}
          actions={
            canEdit
              ? (row) => (
                  <>
                    <Button
                      size="small"
                      onClick={() =>
                        setEditing({
                          ...row,
                        })
                      }
                    >
                      {t("Edit")}
                    </Button>
                    <Button
                      size="small"
                      color="error"
                      onClick={() => setDeleting(row)}
                    >
                      {t("Delete")}
                    </Button>
                  </>
                )
              : undefined
          }
        />
      </Panel>
      {editing && (
        <FormDialog
          title={t(
            editing.id
              ? base === "/api/rovers"
                ? "Edit rover"
                : "Edit mountpoint"
              : base === "/api/rovers"
                ? "Add rover"
                : "Add mountpoint",
          )}
          schema={schema}
          initial={editing}
          onClose={() => setEditing(null)}
          onSubmit={async (value) => {
            const result = customSave
              ? await customSave(value)
              : await api(
                  `${base}/${value.id ? value.id + "/update" : "create"}`,
                  {
                    method: value.id ? "PUT" : "POST",
                    body: prepare(value),
                  },
                );
            resource.refresh();
            return result;
          }}
        />
      )}
      {deleting && (
        <Confirm
          title={t("Delete {0}?", [deleting.name || deleting.username])}
          description={t(
            "This removes the saved configuration. This action cannot be undone.",
          )}
          onClose={() => setDeleting(null)}
          onConfirm={async () => {
            const result = await api(`${base}/${deleting.id}/delete`, {
              method: "POST",
            });
            resource.refresh();
            return result;
          }}
        />
      )}
    </>
  );
}
