import React, { useSyncExternalStore } from "react";
import { ToggleButton, ToggleButtonGroup } from "@mui/material";
import { getLanguage, setLanguage, subscribeLanguage, t } from "./i18n";

// Segmented RU | EN switch, as in the AmneziaWG 3.1 console: both languages
// are visible and one click switches. Names are announced in full.
const languages = [
  ["ru", "RU", "Русский"],
  ["en", "EN", "English"],
];

export function LanguagePicker() {
  const language = useSyncExternalStore(subscribeLanguage, getLanguage);
  return (
    <ToggleButtonGroup
      exclusive
      size="small"
      value={language}
      onChange={(event, value) => value && setLanguage(value)}
      aria-label={t("Interface language")}
      sx={{
        p: "2px",
        gap: "2px",
        borderRadius: 999,
        border: 1,
        borderColor: "divider",
        bgcolor: "background.paper",
        "& .MuiToggleButtonGroup-grouped": {
          border: 0,
          borderRadius: "999px !important",
          m: 0,
          px: 1.25,
          py: 0.5,
          minWidth: 40,
          fontSize: ".72rem",
          fontWeight: 700,
          letterSpacing: ".04em",
          lineHeight: 1.4,
          color: "text.secondary",
        },
        "& .MuiToggleButtonGroup-grouped.Mui-selected, & .MuiToggleButtonGroup-grouped.Mui-selected:hover":
          {
            bgcolor: "primary.main",
            color: "primary.contrastText",
          },
      }}
    >
      {languages.map(([value, short, name]) => (
        <ToggleButton key={value} value={value} aria-label={name} lang={value}>
          {short}
        </ToggleButton>
      ))}
    </ToggleButtonGroup>
  );
}
