import React, { useState, useSyncExternalStore } from "react";
import {
  IconButton,
  ListItemIcon,
  ListItemText,
  ListSubheader,
  Menu,
  MenuItem,
  Tooltip,
} from "@mui/material";
import TextFields from "@mui/icons-material/TextFields";
import Check from "@mui/icons-material/Check";
import { t } from "./i18n";
import {
  fontStack,
  getFonts,
  isInstalled,
  loadFont,
  monoFonts,
  setFont,
  subscribeFonts,
  uiFonts,
} from "./fonts";

function Options({ kind, fonts, selected, installed, onPick }) {
  return fonts.map((font) => {
    const missing = font.local && installed[font.id] === false;
    return (
      <MenuItem
        key={`${kind}-${font.id}`}
        selected={selected === font.id}
        onClick={() => onPick(kind, font.id)}
        role="menuitemradio"
        aria-checked={selected === font.id}
        sx={{ minWidth: 260 }}
      >
        <ListItemIcon>
          {selected === font.id && <Check fontSize="small" />}
        </ListItemIcon>
        <ListItemText
          primary={t(font.label)}
          secondary={
            font.local
              ? missing
                ? t("Not installed on this device")
                : t("Used when installed on this device")
              : null
          }
          slotProps={{
            primary: { sx: { fontFamily: fontStack(kind, font.id) } },
          }}
        />
      </MenuItem>
    );
  });
}

export function FontPicker() {
  const fonts = useSyncExternalStore(subscribeFonts, getFonts);
  const [anchor, setAnchor] = useState(null);
  const [installed, setInstalled] = useState({});
  const open = (event) => {
    setAnchor(event.currentTarget);
    // Previews render each option in its own font.
    [...uiFonts, ...monoFonts].forEach((font) => loadFont(font));
    setInstalled(
      Object.fromEntries(
        [...uiFonts, ...monoFonts]
          .filter((font) => font.local)
          .map((font) => [font.id, isInstalled(font)]),
      ),
    );
  };
  const pick = (kind, id) => setFont(kind, id);
  return (
    <>
      <Tooltip title={t("Fonts")}>
        <IconButton
          aria-label={t("Fonts")}
          aria-haspopup="menu"
          aria-expanded={anchor ? "true" : undefined}
          onClick={open}
        >
          <TextFields fontSize="small" />
        </IconButton>
      </Tooltip>
      <Menu
        anchorEl={anchor}
        open={Boolean(anchor)}
        onClose={() => setAnchor(null)}
        slotProps={{ list: { "aria-label": t("Fonts"), dense: true } }}
      >
        <ListSubheader>{t("Interface font")}</ListSubheader>
        {Options({
          kind: "ui",
          fonts: uiFonts,
          selected: fonts.ui,
          installed,
          onPick: pick,
        })}
        <ListSubheader>{t("Monospace font")}</ListSubheader>
        {Options({
          kind: "mono",
          fonts: monoFonts,
          selected: fonts.mono,
          installed,
          onPick: pick,
        })}
      </Menu>
    </>
  );
}
