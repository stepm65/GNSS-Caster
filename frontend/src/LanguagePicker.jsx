import React, { useSyncExternalStore } from "react";
import { MenuItem, TextField } from "@mui/material";
import { getLanguage, setLanguage, subscribeLanguage, t } from "./i18n";

export function LanguagePicker() {
  const language = useSyncExternalStore(subscribeLanguage, getLanguage);
  return (
    <TextField
      select
      size="small"
      label={t("Interface language")}
      value={language}
      onChange={(event) => setLanguage(event.target.value)}
      sx={{ minWidth: 150 }}
    >
      <MenuItem value="en">English</MenuItem>
      <MenuItem value="ru">Русский</MenuItem>
    </TextField>
  );
}
