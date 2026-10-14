import React, { useState, useMemo, lazy, Suspense } from "react";
import { createRoot } from "react-dom/client";
import { CacheProvider } from "@emotion/react";
import createCache from "@emotion/cache";
import {
  createTheme,
  ThemeProvider,
  CssBaseline,
  Box,
  Button,
  Drawer,
  Divider,
  IconButton,
  LinearProgress,
  List,
  ListItemButton,
  ListItemIcon,
  ListItemText,
  Stack,
  Toolbar,
  Typography,
  Avatar,
  Alert,
} from "@mui/material";
import DashboardOutlined from "@mui/icons-material/DashboardOutlined";
import CellTower from "@mui/icons-material/CellTower";
import Route from "@mui/icons-material/Route";
import HubOutlined from "@mui/icons-material/HubOutlined";
import Tune from "@mui/icons-material/Tune";
import MonitorHeartOutlined from "@mui/icons-material/MonitorHeartOutlined";
import ReceiptLong from "@mui/icons-material/ReceiptLong";
import BackupOutlined from "@mui/icons-material/BackupOutlined";
import SettingsOutlined from "@mui/icons-material/SettingsOutlined";
import ShieldOutlined from "@mui/icons-material/ShieldOutlined";
import Menu from "@mui/icons-material/Menu";
import DarkModeOutlined from "@mui/icons-material/DarkModeOutlined";
import LightModeOutlined from "@mui/icons-material/LightModeOutlined";
import Logout from "@mui/icons-material/Logout";
import SatelliteAlt from "@mui/icons-material/SatelliteAlt";
import { csrfToken } from "./api";
import { Session } from "./session";
import {
  Dashboard,
  Diagnostics,
  Rovers,
  Mountpoints,
  Logs,
  Rtcm,
} from "./pages/Core";
const Stations = lazy(() => import("./pages/Stations"));
const System = lazy(() => import("./pages/System"));
const Security = lazy(() => import("./pages/Security"));
const Login = lazy(() => import("./pages/Login"));

const boot = JSON.parse(
  document.getElementById("gnss-bootstrap")?.textContent || "{}",
);
const navigation = [
  [
    "OPERATIONS",
    [
      ["Overview", "/dashboard", DashboardOutlined],
      ["Base stations", "/base_stations", CellTower],
      ["Rovers", "/rovers", Route],
      ["Mountpoints", "/mountpoints", HubOutlined],
      ["RTCM messages", "/rtcm_settings", Tune],
    ],
  ],
  [
    "MAINTENANCE",
    [
      ["Diagnostics", "/diagnostics", MonitorHeartOutlined],
      ["Logs", "/logs", ReceiptLong],
      ["Backups", "/backups", BackupOutlined],
    ],
  ],
  [
    "MANAGEMENT",
    [
      ["System settings", "/system_configuration", SettingsOutlined],
      ["Account & access", "/user_settings", ShieldOutlined],
    ],
  ],
];
const path = window.location.pathname;
function Content() {
  if (boot.errorPage)
    return (
      <Alert severity="error">
        {boot.error || "This page is unavailable."}{" "}
        <Button href="/dashboard">Back to overview</Button>
      </Alert>
    );
  if (path === "/dashboard" || path === "/") return <Dashboard />;
  if (path.startsWith("/base_stations")) return <Stations />;
  if (path === "/diagnostics") return <Diagnostics />;
  if (path === "/rovers") return <Rovers />;
  if (path === "/mountpoints") return <Mountpoints />;
  if (path === "/rtcm_settings") return <Rtcm />;
  if (path === "/logs") return <Logs />;
  if (["/system_configuration", "/backups"].includes(path)) return <System />;
  if (path === "/user_settings") return <Security />;
  return (
    <Alert severity="info">
      Page not found. <Button href="/dashboard">Open overview</Button>
    </Alert>
  );
}
class ErrorBoundary extends React.Component {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  render() {
    return this.state.failed ? (
      <Alert severity="error">
        Unable to display this page.{" "}
        <Button onClick={() => location.reload()}>Reload</Button>
      </Alert>
    ) : (
      this.props.children
    );
  }
}
function App() {
  const [mode, setMode] = useState(() => {
    try {
      return localStorage.getItem("gnss_theme") === "dark" ? "dark" : "light";
    } catch {
      return "light";
    }
  });
  const [mobile, setMobile] = useState(false);
  const theme = useMemo(
    () =>
      createTheme({
        palette: {
          mode,
          primary: { main: mode === "dark" ? "#83cbb1" : "#216d56" },
          background: {
            default: mode === "dark" ? "#111b1a" : "#f5f7f6",
            paper: mode === "dark" ? "#1a2725" : "#ffffff",
          },
          text: {
            primary: mode === "dark" ? "#e5eeeb" : "#20332c",
            secondary: mode === "dark" ? "#a1b4ad" : "#6b7b73",
          },
          divider: mode === "dark" ? "#30433c" : "#e3e9e5",
          success: { main: "#318465" },
        },
        typography: {
          fontFamily: 'Inter, "Segoe UI", sans-serif',
          h3: { fontWeight: 650, fontSize: "2.25rem" },
          h4: { fontWeight: 650, fontSize: "1.85rem", letterSpacing: "-.04em" },
          h6: { fontWeight: 650, fontSize: "1rem" },
          overline: {
            fontSize: ".65rem",
            fontWeight: 750,
            letterSpacing: ".14em",
          },
          button: { textTransform: "none", fontWeight: 600 },
        },
        shape: { borderRadius: 12 },
        components: {
          MuiButton: {
            defaultProps: { disableElevation: true },
            styleOverrides: { root: { borderRadius: 8 } },
          },
          MuiPaper: { styleOverrides: { root: { backgroundImage: "none" } } },
          MuiTextField: { defaultProps: { size: "small" } },
          MuiTableCell: {
            styleOverrides: {
              head: {
                fontSize: ".72rem",
                color: mode === "dark" ? "#a1b4ad" : "#6b7b73",
                fontWeight: 650,
                whiteSpace: "nowrap",
              },
              root: { padding: "16px 12px", fontFamily: "inherit" },
            },
          },
          MuiChip: {
            styleOverrides: {
              root: { borderRadius: 6, fontSize: ".7rem", fontWeight: 600 },
            },
          },
          MuiDialogActions: { styleOverrides: { root: { padding: 20 } } },
        },
      }),
    [mode],
  );
  const toggle = () =>
    setMode((old) => {
      const next = old === "light" ? "dark" : "light";
      try {
        localStorage.setItem("gnss_theme", next);
      } catch {}
      return next;
    });
  const nav = (
    <Box
      sx={{ height: "100%", display: "flex", flexDirection: "column", p: 2 }}
    >
      <Stack
        direction="row"
        spacing={1.5}
        alignItems="center"
        sx={{ p: 1, pt: 2, pb: 4 }}
      >
        <Box
          sx={{
            p: 1,
            bgcolor: "primary.main",
            color: "background.paper",
            borderRadius: 2,
            display: "flex",
          }}
        >
          <SatelliteAlt />
        </Box>
        <Box>
          <Typography fontWeight={750}>GNSS Caster</Typography>
          <Typography variant="caption" color="text.secondary">
            Correction control
          </Typography>
        </Box>
      </Stack>
      {navigation.map(([group, items]) => (
        <Box key={group} sx={{ mb: 2 }}>
          <Typography
            variant="overline"
            color="text.secondary"
            sx={{ px: 1.5 }}
          >
            {group}
          </Typography>
          <List dense>
            {items.map(([name, href, Icon]) => (
              <ListItemButton
                component="a"
                href={href}
                key={href}
                selected={
                  path === href ||
                  (href === "/base_stations" && path.startsWith(href))
                }
                sx={{
                  borderRadius: 2,
                  mb: 0.5,
                  py: 1.1,
                  "&.Mui-selected": {
                    bgcolor: "action.selected",
                    color: "primary.main",
                  },
                }}
              >
                <ListItemIcon sx={{ minWidth: 36, color: "inherit" }}>
                  <Icon fontSize="small" />
                </ListItemIcon>
                <ListItemText
                  primary={name}
                  primaryTypographyProps={{
                    fontSize: ".85rem",
                    fontWeight: 550,
                  }}
                />
              </ListItemButton>
            ))}
          </List>
        </Box>
      ))}
      <Box sx={{ mt: "auto", p: 1.5 }}>
        <Typography variant="caption" color="text.secondary">
          GNSS Caster · {boot.version || "Development"}
        </Typography>
      </Box>
    </Box>
  );
  const isLogin = path.startsWith("/login");
  return (
    <ThemeProvider theme={theme}>
      <CssBaseline />
      <Session.Provider
        value={{
          ...boot,
          canEdit: ["admin", "operator"].includes(boot.role),
          isAdmin: boot.role === "admin",
        }}
      >
        <ErrorBoundary>
          {isLogin ? (
            <Suspense fallback={<LinearProgress />}>
              <Login boot={boot} />
            </Suspense>
          ) : (
            <Box sx={{ display: "flex", minHeight: "100vh" }}>
              <Box
                component="a"
                href="#main"
                sx={{
                  position: "absolute",
                  top: -100,
                  zIndex: 1500,
                  "&:focus": {
                    top: 8,
                    left: 8,
                    p: 2,
                    bgcolor: "background.paper",
                  },
                }}
              >
                Skip to content
              </Box>
              <Box
                component="nav"
                aria-label="Main navigation"
                sx={{ width: { md: 238 }, flexShrink: 0 }}
              >
                <Drawer
                  variant="permanent"
                  sx={{
                    display: { xs: "none", md: "block" },
                    "& .MuiDrawer-paper": {
                      width: 238,
                      boxSizing: "border-box",
                    },
                  }}
                >
                  {nav}
                </Drawer>
                <Drawer
                  open={mobile}
                  onClose={() => setMobile(false)}
                  sx={{ "& .MuiDrawer-paper": { width: 260 } }}
                >
                  {nav}
                </Drawer>
              </Box>
              <Box sx={{ flex: 1, minWidth: 0 }}>
                <Toolbar
                  sx={{
                    bgcolor: "background.paper",
                    borderBottom: "1px solid",
                    borderColor: "divider",
                    px: { xs: 2, md: 4 },
                    gap: 1.5,
                  }}
                >
                  <IconButton
                    aria-label="Open navigation"
                    onClick={() => setMobile(true)}
                    sx={{ display: { md: "none" } }}
                  >
                    <Menu />
                  </IconButton>
                  <Typography
                    variant="body2"
                    color="text.secondary"
                    sx={{ flex: 1 }}
                  >
                    Station workspace
                  </Typography>
                  <IconButton
                    aria-label={`Switch to ${mode === "light" ? "dark" : "light"} theme`}
                    onClick={toggle}
                  >
                    {mode === "light" ? (
                      <DarkModeOutlined fontSize="small" />
                    ) : (
                      <LightModeOutlined fontSize="small" />
                    )}
                  </IconButton>
                  <Divider orientation="vertical" flexItem sx={{ my: 2 }} />
                  <Avatar
                    sx={{
                      width: 30,
                      height: 30,
                      fontSize: ".8rem",
                      bgcolor: "primary.main",
                    }}
                  >
                    {(boot.username || "G")[0].toUpperCase()}
                  </Avatar>
                  <Box sx={{ display: { xs: "none", sm: "block" } }}>
                    <Typography variant="body2" fontWeight={600}>
                      {boot.username || "GNSS Caster"}
                    </Typography>
                    <Typography variant="caption" color="text.secondary">
                      {boot.role || "Read only"}
                    </Typography>
                  </Box>
                  <Box component="form" method="post" action="/logout">
                    <input
                      type="hidden"
                      name="csrf_token"
                      value={csrfToken()}
                    />
                    <IconButton aria-label="Sign out" type="submit">
                      <Logout fontSize="small" />
                    </IconButton>
                  </Box>
                </Toolbar>
                <Box
                  component="main"
                  id="main"
                  tabIndex={-1}
                  sx={{
                    p: { xs: 2, sm: 3, lg: 4 },
                    maxWidth: 1560,
                    mx: "auto",
                  }}
                >
                  {boot.preview && (
                    <Alert severity="info" sx={{ mb: 3 }}>
                      Local preview · Sample data. The live caster is not
                      connected.
                    </Alert>
                  )}
                  {boot.mustChangePassword && (
                    <Alert severity="warning" sx={{ mb: 3 }}>
                      Change your temporary password.{" "}
                      <Button href="/user_settings">Account settings</Button>
                    </Alert>
                  )}
                  {boot.messages?.map(([severity, message], i) => (
                    <Alert
                      key={i}
                      severity={
                        ["error", "warning", "success", "info"].includes(
                          severity,
                        )
                          ? severity
                          : "info"
                      }
                      sx={{ mb: 2 }}
                    >
                      {message}
                    </Alert>
                  ))}
                  <Suspense fallback={<LinearProgress />}>
                    <Content />
                  </Suspense>
                </Box>
              </Box>
            </Box>
          )}
        </ErrorBoundary>
      </Session.Provider>
    </ThemeProvider>
  );
}
const cache = createCache({
  key: "gnss",
  nonce: document.querySelector('meta[name="csp-nonce"]')?.content,
});
createRoot(document.getElementById("root")).render(
  <CacheProvider value={cache}>
    <App />
  </CacheProvider>,
);
