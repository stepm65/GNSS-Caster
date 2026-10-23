import { test, expect } from "@playwright/test";
import { fixture } from "../fixtures.mjs";

const pages = [
  ["/dashboard", "Overview"],
  ["/base_stations", "Base stations"],
  ["/base_stations/1", "DIY-GNSS-MINI-88"],
  ["/rovers", "Rovers"],
  ["/mountpoints", "Mountpoints"],
  ["/rtcm_settings", "RTCM messages"],
  ["/logs", "Event logs"],
  ["/diagnostics", "Diagnostics"],
  ["/backups", "Backups & restore"],
  ["/system_configuration", "System settings"],
  ["/user_settings", "Account & access"],
  ["/login", "Welcome back"],
  ["/login/2fa", "Verify it’s you"],
];

for (const [path, title] of pages)
  test(`renders ${path} without script errors`, async ({ page }) => {
    const errors = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await page.goto(path);
    await expect(
      page.getByRole("heading", { name: title, exact: true }),
    ).toBeVisible();
    await expect(page.getByText("Loading GNSS Caster…")).toHaveCount(0);
    expect(errors).toEqual([]);
  });

test("overview keeps detailed diagnostics on a separate page", async ({
  page,
}) => {
  await page.goto("/dashboard");
  await expect(page.getByText("Streaming", { exact: true })).toBeVisible();
  await expect(page.getByText("Database responds to a read query")).toHaveCount(
    0,
  );
  await page.getByRole("link", { name: "Open diagnostics" }).click();
  await expect(
    page.getByText("Database responds to a read query"),
  ).toBeVisible();
});

test("mobile navigation and light/dark theme persist", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/dashboard");
  await expect(page.getByRole("heading", { name: "Overview" })).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBeTruthy();
  await page.getByRole("button", { name: "Switch to dark theme" }).click();
  await page.reload();
  await expect(
    page.getByRole("button", { name: "Switch to light theme" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Open navigation" }).click();
  await page.getByRole("link", { name: "Backups", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Backups & restore" }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBeTruthy();
});

test("viewer sees data but cannot open mutation controls", async ({ page }) => {
  await page.goto("/base_stations?role=viewer");
  await expect(
    page.getByRole("heading", { name: "Base stations" }),
  ).toBeVisible();
  await expect(page.getByRole("button", { name: "Add station" })).toHaveCount(
    0,
  );
  await expect(
    page.getByRole("button", { name: "Connect", exact: true }),
  ).toHaveCount(0);
  await page.goto("/user_settings?role=viewer");
  await expect(page.getByRole("tab", { name: "API tokens" })).toHaveCount(0);
});

test("station connection uses the managed endpoint without scanning", async ({
  page,
}) => {
  const writes = [],
    scans = [];
  await page.route("**/api/bluetooth/connect", (route) => {
    writes.push(route.request());
    return route.fulfill({
      json: {
        success: true,
        managed_station: true,
        connection_state: "connecting",
        message: "Connection attempt requested",
      },
    });
  });
  page.on("request", (r) => {
    if (r.url().includes("/api/bluetooth/scan")) scans.push(r.url());
  });
  await page.goto("/base_stations");
  await page.getByRole("button", { name: "Connect", exact: true }).click();
  await expect(page.getByText("Connection attempt requested")).toBeVisible();
  expect(writes).toHaveLength(1);
  expect(writes[0].postDataJSON()).toEqual({ mac: "AA:BB:CC:DD:EE:88" });
  expect(writes[0].headers()["x-csrf-token"]).toBe("preview-csrf");
  expect(scans).toHaveLength(0);
});

test("station edit keeps all existing connection and position values", async ({
  page,
}) => {
  let payload;
  await page.route("**/api/base_stations/1/update", (route) => {
    payload = route.request().postDataJSON();
    return route.fulfill({ json: { message: "Saved" } });
  });
  await page.goto("/base_stations");
  await page.getByRole("button", { name: "Edit", exact: true }).click();
  await expect(page.getByLabel("Station name")).toHaveValue("DIY-GNSS-MINI-88");
  await page.getByRole("tab", { name: "Position & antenna" }).click();
  await expect(page.getByLabel("Latitude (°)")).toHaveValue("55.0281");
  await page.getByRole("button", { name: "Save station" }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  expect(payload.receiver_brand).toBe("unicore");
  expect(payload.manual_lat).toBe(55.0281);
  expect(payload.add_antenna_height).toBe(true);
  expect(payload).not.toHaveProperty("gnss_port");
});

test("rover edit preserves allowed mounts and sends no replacement password", async ({
  page,
}) => {
  let payload;
  await page.route("**/api/rovers/1/update", (route) => {
    payload = route.request().postDataJSON();
    return route.fulfill({ json: { message: "Saved" } });
  });
  await page.goto("/rovers");
  await page.getByRole("button", { name: "Edit", exact: true }).click();
  await page.getByRole("button", { name: "Save changes" }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  expect(payload.mountpoints).toEqual(["BASE88"]);
  expect(payload.password).toBe("");
  expect(payload.expires).toBe(0);
});

test("RTCM draft only saves after explicit action", async ({ page }) => {
  let payload,
    calls = 0;
  await page.route("**/api/rtcm/settings/update", (route) => {
    calls++;
    payload = route.request().postDataJSON();
    return route.fulfill({ json: { message: "Saved" } });
  });
  await page.goto("/rtcm_settings");
  await page.getByRole("checkbox", { name: "Message 1019" }).check();
  expect(calls).toBe(0);
  await page.getByRole("button", { name: "Save changes" }).click();
  await expect.poll(() => calls).toBe(1);
  expect(payload.settings["1019"]).toBe(true);
});

test("secret settings are omitted unless explicitly replaced", async ({
  page,
}) => {
  let payload;
  await page.route("**/api/system/settings/update", (route) => {
    payload = route.request().postDataJSON();
    return route.fulfill({
      json: { message: "System settings updated", applied: {} },
    });
  });
  await page.goto("/system_configuration");
  await page.getByRole("tab", { name: "Notifications", exact: true }).click();
  await expect(page.getByLabel("Telegram bot token")).toHaveValue("");
  await page.getByLabel("Notification chat ID").fill("-100987654");
  await page.getByRole("button", { name: "Save notifications" }).click();
  await expect.poll(() => payload).toBeTruthy();
  expect(payload).toEqual({ telegram_chat_id: "-100987654" });
});

test("field work protection is saved explicitly in general settings", async ({ page }) => {
  let payload;
  await page.route("**/api/system/settings/update", (route) => {
    payload = route.request().postDataJSON();
    return route.fulfill({ json: { message: "System settings updated", applied: {} } });
  });
  await page.goto("/system_configuration");
  await page.getByLabel("Field work in progress — block maintenance").check();
  await page.getByRole("button", { name: "Save general", exact: true }).click();
  await expect.poll(() => payload).toEqual({ field_work_active: true });
});

test("uploaded backup requires separate confirmation before restore", async ({
  page,
}) => {
  let restores = 0,
    uploadCsrf;
  await page.route("**/api/system/backups/upload", (route) => {
    uploadCsrf = route.request().headers()["x-csrf-token"];
    return route.fulfill({
      status: 201,
      json: { filename: "backup_from_telegram.tar.gz.enc", encrypted: true },
    });
  });
  await page.route("**/api/system/backups/restore", (route) => {
    restores++;
    expect(route.request().postDataJSON()).toEqual({
      filename: "backup_from_telegram.tar.gz.enc",
      passphrase: "archive-passphrase",
    });
    return route.fulfill({
      status: 202,
      json: {
        message: "Restore started",
        job: { unit_name: "gnss-caster-restore-test.service" },
      },
    });
  });
  await page.goto("/backups");
  await page.getByLabel("Choose backup file").setInputFiles({
    name: "telegram.tar.gz.enc",
    mimeType: "application/octet-stream",
    buffer: Buffer.from("test-archive"),
  });
  await expect(page.getByRole("dialog")).toBeVisible();
  await expect(
    page.getByRole("dialog").getByText(/keeps the installed program version/),
  ).toBeVisible();
  expect(restores).toBe(0);
  expect(uploadCsrf).toBe("preview-csrf");
  await expect(
    page.getByRole("button", { name: "Confirm", exact: true }),
  ).toBeDisabled();
  await page.getByLabel("Backup passphrase").fill("archive-passphrase");
  await page.getByLabel("Type RESTORE to confirm").fill("RESTORE");
  await page.getByRole("button", { name: "Confirm", exact: true }).click();
  await expect.poll(() => restores).toBe(1);
  await expect(
    page.getByText("Maintenance job completed successfully"),
  ).toBeVisible();
});

test("failed API requests never display a healthy overview", async ({
  page,
}) => {
  await page.route("**/api/diagnostics", (route) =>
    route.fulfill({
      status: 503,
      json: { error: "Receiver diagnostics unavailable" },
    }),
  );
  await page.goto("/dashboard");
  await expect(
    page.getByText("Receiver diagnostics unavailable"),
  ).toBeVisible();
  await expect(page.getByText("Unknown", { exact: true })).toBeVisible();
});

test("expired session gives a sign-in action", async ({ page }) => {
  await page.route("**/api/rovers", (route) =>
    route.fulfill({ status: 401, json: { error: "Login required" } }),
  );
  await page.goto("/rovers");
  await expect(
    page.getByText("Your session has expired. Sign in again."),
  ).toBeVisible();
  await expect(
    page.getByRole("link", { name: "Sign in", exact: true }),
  ).toBeVisible();
});

test("login and 2FA retain native POST and CSRF fields", async ({ page }) => {
  for (const path of ["/login", "/login/2fa"]) {
    await page.goto(path);
    await expect(page.locator("form")).toHaveAttribute("method", "post");
    await expect(page.locator("form")).toHaveAttribute("action", path);
    await expect(page.locator("input[name=csrf_token]")).toHaveValue(
      "preview-csrf",
    );
  }
});

test("station history tabs use actual API response shapes", async ({
  page,
}) => {
  await page.goto("/base_stations/1");
  await page.getByRole("tab", { name: "Command history" }).click();
  await expect(
    page.getByRole("cell", { name: "mode base", exact: true }),
  ).toBeVisible();
  await page.getByRole("tab", { name: "Config versions" }).click();
  await page.getByRole("button", { name: "View changes" }).click();
  await expect(page.getByRole("heading", { name: "Version 2" })).toBeVisible();
});

test("receiver console closes its stream when leaving the tab", async ({
  page,
}) => {
  await page.addInitScript(() => {
    window.streams = [];
    window.EventSource = class {
      constructor(url) {
        this.url = url;
        window.streams.push(this);
      }
      close() {
        this.closed = true;
      }
    };
  });
  await page.goto("/base_stations/1");
  await page.getByRole("tab", { name: "Receiver console" }).click();
  await page.getByRole("button", { name: "Start", exact: true }).click();
  await expect.poll(() => page.evaluate(() => window.streams.length)).toBe(1);
  await page.getByRole("tab", { name: "Telemetry", exact: true }).click();
  expect(await page.evaluate(() => window.streams[0].closed)).toBeTruthy();
});

test("2FA setup returns backup codes only after verification", async ({
  page,
}) => {
  await page.route("**/api/2fa/setup", (route) =>
    route.fulfill({ json: { secret: "TESTONLY234567", qr_data_uri: "" } }),
  );
  await page.route("**/api/2fa/enable", (route) => {
    expect(route.request().postDataJSON()).toEqual({ code: "123456" });
    return route.fulfill({
      json: { message: "2FA enabled", backup_codes: ["aabbccdd", "11223344"] },
    });
  });
  await page.goto("/user_settings");
  await page
    .getByRole("button", {
      name: "Set up two-factor authentication",
      exact: true,
    })
    .click();
  await expect(page.getByLabel("Setup key")).toHaveValue("TESTONLY234567");
  await page.getByLabel("Six-digit code").fill("123456");
  await page.getByRole("button", { name: "Enable", exact: true }).click();
  await expect(page.getByLabel("One-time secret")).toHaveValue(
    "aabbccdd\n11223344",
  );
});

test("API token creation displays the returned secret without persisting it", async ({
  page,
}) => {
  await page.route("**/api/tokens/create", (route) => {
    expect(route.request().postDataJSON()).toEqual({
      name: "Field status",
      scope: "read",
      expires_days: 30,
    });
    return route.fulfill({
      status: 201,
      json: { token: "gnss_test_only_token", message: "Token created" },
    });
  });
  await page.goto("/user_settings");
  await page.getByRole("tab", { name: "API tokens" }).click();
  await page.getByRole("button", { name: "Create token", exact: true }).click();
  await page
    .getByRole("dialog")
    .getByRole("textbox", { name: "Name", exact: true })
    .fill("Field status");
  await page.getByRole("button", { name: "Save changes", exact: true }).click();
  await expect(page.getByLabel("One-time secret")).toHaveValue(
    "gnss_test_only_token",
  );
  expect(
    await page.evaluate(() =>
      JSON.stringify({ ...localStorage, ...sessionStorage }),
    ),
  ).not.toContain("gnss_test_only_token");
});

test("a page opened in a background tab loads non-polling settings", async ({
  page,
}) => {
  await page.addInitScript(() => {
    Object.defineProperty(document, "hidden", {
      configurable: true,
      get: () => true,
    });
  });
  await page.goto("/rtcm_settings");
  await expect(
    page.getByRole("checkbox", { name: "Message 1019" }),
  ).toBeVisible();
});

test("capture desktop and mobile preview", async ({ page }) => {
  await page.goto("/dashboard");
  await expect(page.getByText("Streaming", { exact: true })).toBeVisible();
  await page.screenshot({
    path: "../validation/ui/overview-desktop.png",
    fullPage: true,
  });
  await page.goto("/diagnostics");
  await expect(
    page.getByText("Database responds to a read query"),
  ).toBeVisible();
  await page.screenshot({
    path: "../validation/ui/diagnostics-desktop.png",
    fullPage: true,
  });
  await page.goto("/backups");
  await expect(
    page.getByRole("cell", {
      name: "backup_20261013_120000.tar.gz",
      exact: true,
    }),
  ).toBeVisible();
  await page.screenshot({
    path: "../validation/ui/backups-desktop.png",
    fullPage: true,
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/dashboard");
  await expect(page.getByText("Streaming", { exact: true })).toBeVisible();
  await page.screenshot({
    path: "../validation/ui/overview-mobile.png",
    fullPage: true,
  });
});
