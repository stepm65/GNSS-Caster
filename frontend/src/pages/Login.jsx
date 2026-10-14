import { t } from "../i18n";
import { LanguagePicker } from "../LanguagePicker";
import React, { useState } from "react";
import {
  Alert,
  Box,
  Button,
  Paper,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import SatelliteAlt from "@mui/icons-material/SatelliteAlt";
import { csrfToken } from "../api";
export default function Login({ boot }) {
  const twoFactor = location.pathname === "/login/2fa",
    [busy, setBusy] = useState(false);
  return (
    <Box
      sx={{
        minHeight: "100vh",
        display: "grid",
        gridTemplateColumns: {
          xs: "1fr",
          md: "1fr 1fr",
        },
      }}
    >
      <Box
        sx={{
          display: {
            xs: "none",
            md: "flex",
          },
          bgcolor: "#183d30",
          color: "#eff7f1",
          p: 7,
          flexDirection: "column",
          justifyContent: "space-between",
        }}
      >
        <Stack direction="row" spacing={2} alignItems="center">
          <SatelliteAlt />
          <Typography fontWeight={700}>{t("GNSS Caster")}</Typography>
        </Stack>
        <Box>
          <Typography
            variant="overline"
            sx={{
              color: "#95c5ae",
            }}
          >
            {t("FROM BASE TO FIELD")}
          </Typography>
          <Typography
            sx={{
              fontSize: {
                md: 44,
                lg: 56,
              },
              fontWeight: 600,
              lineHeight: 1.12,
              letterSpacing: "-.04em",
              mt: 2,
              maxWidth: 500,
            }}
          >
            {t("Precision starts")}
            <br />
            {t("with a connection.")}
          </Typography>
          <Typography
            sx={{
              mt: 3,
              color: "#bdd4c8",
              maxWidth: 390,
            }}
          >
            {t(
              "Manage your base stations, correction streams and rover access in one place.",
            )}
          </Typography>
          <Box
            sx={{
              mt: 8,
              width: "80%",
              height: 140,
              borderTop: "1px solid #416651",
              borderBottom: "1px solid #416651",
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
            }}
          >
            {["BASE", "CASTER", "ROVER"].map((v, i) => (
              <React.Fragment key={t(v)}>
                {i > 0 && (
                  <Box
                    sx={{
                      flex: 1,
                      height: 1,
                      mx: 2,
                      bgcolor: "#628d75",
                    }}
                  />
                )}
                <Typography
                  variant="overline"
                  sx={{
                    color: "#bdd4c8",
                  }}
                >
                  {t(v)}
                </Typography>
              </React.Fragment>
            ))}
          </Box>
        </Box>
        <Typography
          variant="caption"
          sx={{
            color: "#95b4a2",
          }}
        >
          {t("GNSS Caster \xB7 ")}
          {boot.version}
        </Typography>
      </Box>
      <Box
        sx={{
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          p: 3,
        }}
      >
        <Box
          sx={{
            width: "100%",
            maxWidth: 380,
          }}
        >
          <Box sx={{ mb: 3 }}>
            <LanguagePicker />
          </Box>
          <Box
            sx={{
              color: "primary.main",
              mb: 4,
            }}
          >
            <SatelliteAlt
              sx={{
                fontSize: 36,
              }}
            />
          </Box>
          <Typography variant="h4">
            {twoFactor ? t("Verify it\u2019s you") : t("Welcome back")}
          </Typography>
          <Typography
            color="text.secondary"
            sx={{
              mt: 1,
              mb: 4,
            }}
          >
            {twoFactor
              ? t("Enter an authenticator code or a one-time backup code.")
              : t("Sign in to your station workspace.")}
          </Typography>
          {boot.error && (
            <Alert
              severity="error"
              sx={{
                mb: 3,
              }}
            >
              {t(boot.error)}
            </Alert>
          )}
          {boot.showPasswordNotice && (
            <Alert
              severity="info"
              sx={{
                mb: 3,
              }}
            >
              {t(
                "You will need to update your temporary password after signing in.",
              )}
            </Alert>
          )}
          <Box
            component="form"
            method="post"
            action={twoFactor ? "/login/2fa" : "/login"}
            onSubmit={() => setBusy(true)}
          >
            <input type="hidden" name="csrf_token" value={csrfToken()} />
            <Stack spacing={2.5}>
              {twoFactor ? (
                <TextField
                  autoFocus
                  fullWidth
                  name="code"
                  label={t("Verification or backup code")}
                  autoComplete="one-time-code"
                  required
                  slotProps={{
                    htmlInput: {
                      maxLength: 9,
                    },
                  }}
                />
              ) : (
                <>
                  <TextField
                    autoFocus
                    fullWidth
                    name="username"
                    label={t("Username")}
                    autoComplete="username"
                    required
                  />
                  <TextField
                    fullWidth
                    name="password"
                    label={t("Password")}
                    type="password"
                    autoComplete="current-password"
                    required
                  />
                </>
              )}
              <Button
                size="large"
                variant="contained"
                type="submit"
                disabled={busy}
              >
                {busy
                  ? t("Signing in\u2026")
                  : twoFactor
                    ? t("Verify & sign in")
                    : t("Sign in")}
              </Button>
              {twoFactor && (
                <Button href="/login">{t("Back to sign in")}</Button>
              )}
            </Stack>
          </Box>
        </Box>
      </Box>
    </Box>
  );
}
