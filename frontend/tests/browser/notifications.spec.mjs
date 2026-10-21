import { test, expect } from "@playwright/test";

for (const language of ["en", "ru"]) {
  test(`notification queue shows failed delivery and counts in ${language}`, async ({
    page,
  }) => {
    await page.addInitScript(
      (value) => localStorage.setItem("gnss_language", value),
      language,
    );
    const calls = [];
    page.on("request", (request) => {
      if (request.method() !== "GET") calls.push(request.url());
    });
    await page.route("**/api/system/notify/status", (route) =>
      route.fulfill({
        json: {
          available: true,
          worker_running: true,
          worker_error: false,
          write_failures: 2,
          pending: 17,
          capacity: 200,
          next_attempt_seconds: 60,
          last_success: null,
          last_error: "Telegram rate limit",
          counts: {
            delivered: 0,
            failed: 3,
            expired: 4,
            cancelled: 1,
            overflow: 5,
          },
        },
      }),
    );
    await page.goto("/system_configuration");
    await page
      .getByRole("tab", {
        name: language === "ru" ? "Уведомления" : "Notifications",
        exact: true,
      })
      .click();
    await expect(page.getByText("17 / 200", { exact: true })).toBeVisible();
    await expect(
      page.getByText(
        language === "ru"
          ? "Telegram ограничил частоту отправки"
          : "Telegram rate limit",
        { exact: true },
      ),
    ).toBeVisible();
    await expect(
      page.getByText(
        language === "ru"
          ? "Успешных отправок пока нет"
          : "No successful delivery recorded",
        { exact: true },
      ),
    ).toBeVisible();
    expect(calls).toEqual([]);
  });
}

test("unavailable notification storage is an error, not successful delivery", async ({
  page,
}) => {
  await page.route("**/api/system/notify/status", (route) =>
    route.fulfill({ json: { available: false } }),
  );
  await page.goto("/system_configuration");
  await page.getByRole("tab", { name: "Notifications", exact: true }).click();
  await expect(
    page.getByText(
      "Notification delivery is unavailable. Check the service log and free disk space.",
      { exact: true },
    ),
  ).toBeVisible();
});
