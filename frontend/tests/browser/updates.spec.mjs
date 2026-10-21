import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

const status = () => ({
  current_version: "3.3.0",
  job: { status: "idle" },
  release: {
    checked_at: 1792000000,
    candidate: {
      version: "3.4.0",
      tag: "v3.4.0",
      sha256: "a".repeat(64),
      available: true,
      url: "https://github.com/stepm65/GNSS-Caster/releases/tag/v3.4.0",
      notes: '<img src=x onerror="window.releaseXss=true">',
    },
  },
});
async function open(page, state = status(), language = "en") {
  await page.addInitScript(
    (language) => localStorage.setItem("gnss_language", language),
    language,
  );
  await page.route("**/api/system/updates/status", (route) =>
    route.fulfill({ json: state }),
  );
  await page.goto("/system_configuration");
  await page
    .getByRole("tab", {
      name: language === "ru" ? "Обновления" : "Updates",
      exact: true,
    })
    .click();
}

test("update requires password and explicit confirmation, sends CSRF once, keeps notes as text", async ({
  page,
}) => {
  const state = status(),
    sent = [];
  await page.route("**/api/system/updates/install", async (route) => {
    sent.push({
      data: route.request().postDataJSON(),
      headers: route.request().headers(),
    });
    state.job = {
      status: "installing",
      started_at: 1792000100,
      message: "Installing; web interface may reconnect",
    };
    await route.fulfill({ status: 202, json: state.job });
  });
  await open(page, state);
  await expect(
    page.getByText(state.release.candidate.notes, { exact: true }),
  ).toBeVisible();
  expect(await page.evaluate(() => window.releaseXss)).toBeUndefined();
  await page
    .getByRole("button", { name: "Install version 3.4.0", exact: true })
    .click();
  const submit = page.getByRole("button", {
    name: "Install update",
    exact: true,
  });
  await expect(submit).toBeDisabled();
  await page.getByLabel("Type UPDATE to confirm").fill("UPDATE");
  await expect(submit).toBeDisabled();
  await page
    .getByLabel("Current password", { exact: true })
    .fill("mock-password-only");
  await submit.click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "Install version 3.4.0", exact: true }),
  ).toBeDisabled();
  expect(sent).toHaveLength(1);
  expect(sent[0].data).toEqual({
    tag: "v3.4.0",
    sha256: "a".repeat(64),
    confirm: "UPDATE",
    password: "mock-password-only",
  });
  expect(sent[0].headers["x-csrf-token"]).toBeTruthy();
  expect(
    await page.evaluate(() => JSON.stringify([localStorage, sessionStorage])),
  ).not.toContain("mock-password-only");
});

test("failed request clears password without retrying installation", async ({
  page,
}) => {
  let requests = 0;
  await page.route("**/api/system/updates/install", (route) => {
    requests++;
    return route.fulfill({
      status: 409,
      json: { error: "Disconnect all rovers before updating" },
    });
  });
  await open(page);
  await page
    .getByRole("button", { name: "Install version 3.4.0", exact: true })
    .click();
  await page.getByLabel("Type UPDATE to confirm").fill("UPDATE");
  await page
    .getByLabel("Current password", { exact: true })
    .fill("mock-password-only");
  await page
    .getByRole("button", { name: "Install update", exact: true })
    .click();
  await expect(
    page.getByRole("dialog").getByText("Disconnect all rovers before updating"),
  ).toBeVisible();
  await expect(
    page.getByLabel("Current password", { exact: true }),
  ).toHaveValue("");
  await expect(
    page.getByRole("button", { name: "Install update", exact: true }),
  ).toBeDisabled();
  expect(requests).toBe(1);
});

test("status survives reload, disconnection and confirmed rollback", async ({
  page,
}) => {
  const state = status();
  state.job = {
    status: "installing",
    started_at: 1792000100,
    message: "Installing; web interface may reconnect",
  };
  await open(page, state);
  await page.reload();
  await page.getByRole("tab", { name: "Updates", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Check for updates", exact: true }),
  ).toBeDisabled();
  await page.route("**/api/system/updates/status", (route) => route.abort());
  await expect(
    page.getByText(
      "Waiting for the service to reconnect. Do not repeat installation.",
    ),
  ).toBeVisible({ timeout: 15000 });
  state.job = {
    ...state.job,
    status: "rolled_back",
    message: "Update failed; previous version restored",
    snapshot: "/var/backups/gnss-caster/mock-snapshot",
  };
  await page.unroute("**/api/system/updates/status");
  await page.route("**/api/system/updates/status", (route) =>
    route.fulfill({ json: state }),
  );
  await expect(
    page.getByText("Update failed; previous version restored", { exact: true }),
  ).toBeVisible({ timeout: 15000 });
  await expect(page.getByText(/Rollback snapshot:/)).toBeVisible();
});

test("release checks are explicit and non-admins cannot open updates", async ({
  page,
}) => {
  let checks = 0;
  const state = { ...status(), release: null };
  await page.route("**/api/system/updates/check", (route) => {
    checks++;
    state.release = { checked_at: 1792000000, candidate: null };
    return route.fulfill({ json: state.release });
  });
  await open(page, state);
  expect(checks).toBe(0);
  await page
    .getByRole("button", { name: "Check for updates", exact: true })
    .click();
  await expect(
    page.getByText("No published stable release is available yet."),
  ).toBeVisible();
  expect(checks).toBe(1);
  for (const role of ["viewer", "operator"]) {
    await page.goto(`/system_configuration?role=${role}`);
    await expect(
      page.getByRole("heading", { name: "System settings", exact: true }),
    ).toBeVisible();
    await expect(
      page.getByRole("tab", { name: "Updates", exact: true }),
    ).toHaveCount(0);
  }
});

test("Russian mobile update confirmation remains readable and keyboard accessible", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await open(page, status(), "ru");
  await page
    .getByRole("button", { name: "Установить версию 3.4.0", exact: true })
    .click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await page
    .getByLabel("Текущий пароль", { exact: true })
    .fill("mock-password-only");
  await page.keyboard.press("Tab");
  await expect(
    page.getByLabel("Введите UPDATE для подтверждения"),
  ).toBeFocused();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
    .analyze();
  expect(
    results.violations.map((v) => ({
      id: v.id,
      nodes: v.nodes.map((n) => ({
        target: n.target,
        reason: n.failureSummary,
      })),
    })),
  ).toEqual([]);
  await page.screenshot({
    path: "../validation/ui/updates-mobile-ru.png",
    fullPage: true,
  });
});

test("unfinished maintenance shows recovery instructions and blocks installation", async ({ page }) => {
  const state = status();
  state.recovery = [{
    id: "rollback-fixture",
    recovery_command: "sudo python3 -I /var/lib/gnss-caster-maintenance/recovery.py recover rollback-fixture --confirm",
  }];
  await open(page, state);
  await expect(page.getByRole("button", { name: "Install version 3.4.0" })).toBeDisabled();
  await expect(page.getByText(state.recovery[0].recovery_command, { exact: true })).toBeVisible();
});

test("key cabinet pages pass automated accessibility checks", async ({
  page,
}) => {
  for (const path of [
    "/login",
    "/dashboard",
    "/backups",
    "/diagnostics",
    "/system_configuration",
  ]) {
    await page.goto(path);
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    const results = await new AxeBuilder({ page })
      .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
      .analyze();
    expect(
      results.violations.map((v) => ({
        id: v.id,
        nodes: v.nodes.map((n) => ({
          target: n.target,
          reason: n.failureSummary,
        })),
      })),
      path,
    ).toEqual([]);
  }
});
