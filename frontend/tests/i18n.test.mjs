import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { createRequire } from "node:module";
import { setLanguage, getLanguage, t, serverMessage } from "../src/i18n.js";
import ru from "../src/locales/ru.json" with { type: "json" };

test("language selection falls back to English and preserves interpolation values", () => {
  setLanguage("ru");
  assert.equal(t("Overview"), "Обзор");
  assert.equal(
    t("Delete {0}?", ["Overview <img>"]),
    "Удалить «Overview <img>»?",
  );
  assert.equal(t("untranslated diagnostic"), "untranslated diagnostic");
  assert.equal(t("constructor"), "constructor");
  assert.equal(t("toString"), "toString");
  assert.equal(
    serverMessage(
      "0/1 receivers connected; Bluetooth recovery: waiting_for_connection (attempt 2)",
    ),
    "Подключено приёмников: 0 из 1; Восстановление Bluetooth: ожидание подключения (попытка 2)",
  );
  assert.equal(
    serverMessage("Driver text <original>"),
    "Driver text <original>",
  );
  setLanguage("unsupported");
  assert.equal(getLanguage(), "en");
  assert.equal(t("Overview"), "Overview");
});

test("every explicit UI translation has a Russian entry with matching placeholders", () => {
  const require = createRequire(import.meta.resolve("@vitejs/plugin-react"));
  const { parseSync, traverse } = require("@babel/core");
  function check(directory) {
    for (const entry of readdirSync(directory, { withFileTypes: true })) {
      const path = join(directory, entry.name);
      if (entry.isDirectory()) check(path);
      else if (/\.(jsx|js)$/.test(entry.name)) {
        const source = readFileSync(path, "utf8");
        traverse(
          parseSync(source, {
            filename: path,
            configFile: false,
            babelrc: false,
            parserOpts: { plugins: ["jsx", "importAttributes"] },
          }),
          {
            CallExpression(call) {
              const { node } = call;
              if (node.callee.name === "t") {
                assert.equal(
                  call.scope.getBinding("t")?.kind,
                  entry.name === "i18n.js" ? "hoisted" : "module",
                  `Translation function is shadowed (${entry.name})`,
                );
              }
              if (
                node.callee.name !== "t" ||
                node.arguments[0]?.type !== "StringLiteral"
              )
                return;
              const key = node.arguments[0].value;
              assert.ok(
                Object.hasOwn(ru, key),
                `Missing translation: ${key} (${entry.name})`,
              );
            },
          },
        );
      }
    }
  }
  check(fileURLToPath(new URL("../src", import.meta.url)));
  for (const [key, value] of Object.entries(ru)) {
    assert.ok(value.trim(), key);
    assert.deepEqual(
      [...key.matchAll(/\{\d+\}/g)].map((m) => m[0]).sort(),
      [...value.matchAll(/\{\d+\}/g)].map((m) => m[0]).sort(),
      key,
    );
  }
});
