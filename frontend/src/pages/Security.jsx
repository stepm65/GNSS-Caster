import React, { useContext, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Stack,
  Tab,
  Tabs,
  TextField,
  Typography,
} from "@mui/material";
import { Session } from "../session";
import { api } from "../api";
import { useAction, useResource } from "../hooks";
import {
  Confirm,
  DataTable,
  Fields,
  FormDialog,
  GridBox,
  KeyValues,
  Notice,
  PageTitle,
  Panel,
  ResourceState,
  Status,
  date,
} from "../components";

export default function Security() {
  const { isAdmin } = useContext(Session),
    [tab, setTab] = useState(0);
  return (
    <>
      <PageTitle
        title="Account & access"
        eyebrow="MANAGEMENT"
        description="Protect your account and manage access to this caster."
      />
      <Tabs
        value={tab}
        onChange={(_, v) => setTab(v)}
        sx={{ mb: 3 }}
        variant="scrollable"
      >
        <Tab label="My account" />
        {isAdmin && <Tab label="User accounts" />}
        {isAdmin && <Tab label="API tokens" />}
      </Tabs>
      {tab === 0 && <Account />}
      {isAdmin && tab === 1 && <Accounts />}
      {isAdmin && tab === 2 && <Tokens />}
    </>
  );
}
function Account() {
  const session = useContext(Session),
    action = useAction(),
    status = useResource("/api/2fa/status", 0);
  const [passwords, setPasswords] = useState({
      current_password: "",
      new_password: "",
      confirm_password: "",
    }),
    [setup, setSetup] = useState(null),
    [code, setCode] = useState(""),
    [disable, setDisable] = useState(false),
    [codes, setCodes] = useState(null);
  return (
    <>
      <Notice value={action.notice} />
      <GridBox>
        <Panel
          title="Change password"
          caption={`Signed in as ${session.username}`}
        >
          <Box
            component="form"
            onSubmit={(e) => {
              e.preventDefault();
              action.run(
                async () => {
                  if (passwords.new_password !== passwords.confirm_password)
                    throw new Error("New passwords do not match.");
                  return api("/api/user/change_password", {
                    method: "POST",
                    body: passwords,
                  });
                },
                () =>
                  setPasswords({
                    current_password: "",
                    new_password: "",
                    confirm_password: "",
                  }),
              );
            }}
          >
            <Fields
              schema={[
                {
                  key: "current_password",
                  type: "password",
                  required: true,
                  wide: true,
                },
                {
                  key: "new_password",
                  type: "password",
                  required: true,
                  wide: true,
                  help: "Use a strong, unique password.",
                },
                {
                  key: "confirm_password",
                  type: "password",
                  required: true,
                  wide: true,
                },
              ]}
              value={passwords}
              onChange={setPasswords}
              disabled={action.busy}
            />
            <Button
              type="submit"
              variant="contained"
              disabled={action.busy}
              sx={{ mt: 3 }}
            >
              Update password
            </Button>
          </Box>
        </Panel>
        <Panel
          title="Two-factor authentication"
          caption="An authenticator code adds a second step when you sign in."
        >
          <ResourceState resource={status} />
          <Status value={status.data?.enabled ? "enabled" : "disabled"} />
          <Typography sx={{ my: 2 }} color="text.secondary">
            {status.data?.enabled
              ? `${status.data.backup_codes_remaining} backup codes remaining.`
              : "Set up an authenticator app to protect your account."}
          </Typography>
          {status.data?.enabled ? (
            <Button
              color="error"
              variant="outlined"
              onClick={() => setDisable(true)}
            >
              Disable two-factor authentication
            </Button>
          ) : (
            <Button
              variant="outlined"
              disabled={action.busy || !status.data}
              onClick={() =>
                action.run(
                  () => api("/api/2fa/setup", { method: "POST" }),
                  setSetup,
                )
              }
            >
              Set up two-factor authentication
            </Button>
          )}
        </Panel>
      </GridBox>
      {setup && (
        <Dialog
          open
          maxWidth="sm"
          fullWidth
          onClose={() => {
            setSetup(null);
            setCode("");
          }}
        >
          <DialogTitle>Set up your authenticator</DialogTitle>
          <DialogContent>
            <Notice value={action.notice} />
            <Typography>
              Scan the QR code in your authenticator app, or enter the setup key
              manually.
            </Typography>
            {setup.qr_data_uri?.startsWith("data:image/png;base64,") && (
              <Box
                component="img"
                src={setup.qr_data_uri}
                alt="Authenticator setup QR code"
                sx={{
                  width: 220,
                  height: 220,
                  display: "block",
                  mx: "auto",
                  my: 2,
                }}
              />
            )}
            <TextField
              fullWidth
              label="Setup key"
              value={setup.secret || ""}
              slotProps={{ input: { readOnly: true } }}
              sx={{ my: 2 }}
            />
            <TextField
              fullWidth
              autoComplete="one-time-code"
              label="Six-digit code"
              value={code}
              onChange={(e) => setCode(e.target.value)}
              slotProps={{ htmlInput: { inputMode: "numeric", maxLength: 6 } }}
            />
          </DialogContent>
          <DialogActions>
            <Button
              disabled={action.busy}
              onClick={() => {
                setSetup(null);
                setCode("");
              }}
            >
              Cancel
            </Button>
            <Button
              variant="contained"
              disabled={action.busy || !/^\d{6}$/.test(code)}
              onClick={() =>
                action.run(
                  () =>
                    api("/api/2fa/enable", { method: "POST", body: { code } }),
                  (result) => {
                    setCodes(result.backup_codes);
                    setSetup(null);
                    setCode("");
                    status.refresh();
                  },
                )
              }
            >
              Enable
            </Button>
          </DialogActions>
        </Dialog>
      )}
      {disable && (
        <FormDialog
          title="Disable two-factor authentication"
          schema={[
            {
              key: "password",
              label: "Current password",
              type: "password",
              required: true,
              wide: true,
            },
          ]}
          initial={{}}
          submitLabel="Disable two-factor authentication"
          onClose={() => setDisable(false)}
          onSubmit={async (v) => {
            const result = await api("/api/2fa/disable", {
              method: "POST",
              body: v,
            });
            status.refresh();
            return result;
          }}
        />
      )}
      {codes && (
        <SecretDialog
          title="Save your backup codes"
          description="Each code can be used once if you lose access to your authenticator. Store them somewhere safe. They will not be shown again."
          value={codes.join("\n")}
          onClose={() => setCodes(null)}
        />
      )}
    </>
  );
}
function Accounts() {
  const session = useContext(Session),
    resource = useResource("/api/admins", 0),
    [editor, setEditor] = useState(null),
    [reset, setReset] = useState(null);
  const fields = [
    { key: "username", required: true },
    { key: "email", type: "email" },
    {
      key: "role",
      options: ["viewer", "operator", "admin"],
      disabled: editor?.is_builtin,
      help: "Viewer: read-only. Operator: stations and backups. Admin: system and user access.",
    },
    ...(!editor?.id
      ? [
          { key: "password", type: "password", required: true },
          { key: "confirm_password", type: "password", required: true },
        ]
      : []),
  ];
  return (
    <Panel
      title="User accounts"
      action={
        <Button
          variant="contained"
          onClick={() => setEditor({ role: "operator" })}
        >
          Add user
        </Button>
      }
    >
      <ResourceState resource={resource} />
      <DataTable
        rows={resource.data || []}
        columns={[
          { key: "username" },
          { key: "role", render: (r) => <Status value={r.role} /> },
          { key: "email" },
          { key: "last_login", render: (r) => date(r.last_login) },
          {
            key: "locked_until",
            label: "Lock status",
            render: (r) =>
              r.locked_until > Date.now() / 1000
                ? `Locked until ${date(r.locked_until)}`
                : "Unlocked",
          },
        ]}
        actions={(r) => (
          <>
            <Button size="small" onClick={() => setEditor(r)}>
              Edit
            </Button>
            <Button size="small" onClick={() => setReset(r)}>
              Reset password
            </Button>
          </>
        )}
      />
      {editor && (
        <FormDialog
          title={editor.id ? "Edit user" : "Add user"}
          schema={fields}
          initial={editor}
          onClose={() => setEditor(null)}
          onSubmit={async (value) => {
            if (!value.id && value.password !== value.confirm_password)
              throw new Error("Passwords do not match.");
            const payload = {
              username: value.username,
              email: value.email || "",
              role: value.role,
              ...(!value.id ? { password: value.password } : {}),
            };
            const r = await api(
              `/api/admins/${value.id ? value.id + "/update" : "create"}`,
              { method: value.id ? "PUT" : "POST", body: payload },
            );
            resource.refresh();
            if (value.id === session.userId) window.location.reload();
            return r;
          }}
        />
      )}
      {reset && (
        <FormDialog
          title={`Reset password for ${reset.username}`}
          schema={[
            {
              key: "password",
              label: "New password",
              type: "password",
              required: true,
            },
            { key: "confirm_password", type: "password", required: true },
          ]}
          initial={{}}
          onClose={() => setReset(null)}
          onSubmit={async (v) => {
            if (v.password !== v.confirm_password)
              throw new Error("Passwords do not match.");
            const r = await api(`/api/admins/${reset.id}/reset_password`, {
              method: "POST",
              body: v,
            });
            resource.refresh();
            return r;
          }}
        >
          <Alert severity="warning" sx={{ mb: 3 }}>
            This changes the user's password and invalidates their other
            sessions.
          </Alert>
        </FormDialog>
      )}
    </Panel>
  );
}
function Tokens() {
  const resource = useResource("/api/tokens", 0),
    [create, setCreate] = useState(false),
    [secret, setSecret] = useState(null),
    [confirm, setConfirm] = useState(null),
    action = useAction();
  return (
    <Panel
      title="API tokens"
      caption="Tokens grant programmatic access. The full token is shown only once."
      action={
        <Button variant="contained" onClick={() => setCreate(true)}>
          Create token
        </Button>
      }
    >
      <Notice value={action.notice} />
      <ResourceState resource={resource} />
      <DataTable
        rows={resource.data || []}
        columns={[
          { key: "name" },
          { key: "token_prefix", label: "Prefix" },
          { key: "scope" },
          {
            key: "is_active",
            label: "Status",
            render: (t) => (
              <Status
                value={
                  t.expired ? "expired" : t.is_active ? "enabled" : "disabled"
                }
              />
            ),
          },
          {
            key: "expires",
            render: (t) => (t.expires ? date(t.expires) : "Never"),
          },
          { key: "last_used", render: (t) => date(t.last_used) },
        ]}
        actions={(t) => (
          <>
            <Button
              size="small"
              disabled={action.busy}
              onClick={() =>
                action.run(
                  () => api(`/api/tokens/${t.id}/toggle`, { method: "POST" }),
                  resource.refresh,
                )
              }
            >
              {t.is_active ? "Disable" : "Enable"}
            </Button>
            <Button size="small" color="error" onClick={() => setConfirm(t)}>
              Revoke
            </Button>
          </>
        )}
      />
      {create && (
        <FormDialog
          title="Create API token"
          schema={[
            { key: "name", required: true },
            {
              key: "scope",
              options: [
                { value: "read", label: "Read only" },
                { value: "full", label: "Full access" },
              ],
            },
            {
              key: "expires_days",
              label: "Expires after (days)",
              type: "number",
              min: 0,
              help: "0 means no expiration.",
            },
          ]}
          initial={{ scope: "read", expires_days: 30 }}
          onClose={() => setCreate(false)}
          onSubmit={async (v) => {
            const r = await api("/api/tokens/create", {
              method: "POST",
              body: v,
            });
            setSecret(r.token);
            resource.refresh();
            return r;
          }}
        />
      )}
      {secret && (
        <SecretDialog
          title="Copy your API token"
          description="Save this token now. It will not be shown again."
          value={secret}
          onClose={() => setSecret(null)}
        />
      )}
      {confirm && (
        <Confirm
          title={`Revoke ${confirm.name}?`}
          description="Applications using this token will lose access immediately."
          onClose={() => setConfirm(null)}
          onConfirm={async () => {
            const r = await api(`/api/tokens/${confirm.id}/delete`, {
              method: "POST",
            });
            resource.refresh();
            return r;
          }}
        />
      )}
    </Panel>
  );
}
function SecretDialog({ title, description, value, onClose }) {
  const [copied, setCopied] = useState(false);
  return (
    <Dialog open fullWidth maxWidth="sm" onClose={onClose}>
      <DialogTitle>{title}</DialogTitle>
      <DialogContent>
        <Alert severity="warning" sx={{ mb: 3 }}>
          {description}
        </Alert>
        <TextField
          fullWidth
          multiline
          label="One-time secret"
          value={value}
          slotProps={{ input: { readOnly: true } }}
        />
      </DialogContent>
      <DialogActions>
        <Button
          onClick={async () => {
            try {
              await navigator.clipboard.writeText(value);
              setCopied(true);
            } catch {
              setCopied(false);
            }
          }}
        >
          {copied ? "Copied" : "Copy"}
        </Button>
        <Button variant="contained" onClick={onClose}>
          I have saved it
        </Button>
      </DialogActions>
    </Dialog>
  );
}
