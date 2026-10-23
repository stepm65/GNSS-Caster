import { test, expect } from "@playwright/test";

const pages = [
  ["/dashboard", "Обзор"],
  ["/base_stations", "Базовые станции"],
  ["/base_stations/1", "DIY-GNSS-MINI-88"],
  ["/rovers", "Роверы"],
  ["/mountpoints", "Точки подключения"],
  ["/rtcm_settings", "Сообщения RTCM"],
  ["/logs", "Журнал событий"],
  ["/diagnostics", "Диагностика"],
  ["/backups", "Резервные копии и восстановление"],
  ["/system_configuration", "Системные настройки"],
  ["/user_settings", "Учётная запись и доступ"],
  ["/login", "Добро пожаловать"],
  ["/login/2fa", "Подтвердите вход"],
];

test("Russian nested tabs and edit dialogs render without losing translations", async ({
  page,
}) => {
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.addInitScript(() => localStorage.setItem("gnss_language", "ru"));
  for (const path of [
    "/user_settings",
    "/system_configuration",
    "/base_stations/1",
  ]) {
    await page.goto(path);
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    const tabs = page.getByRole("tab");
    for (let index = 0; index < (await tabs.count()); index++) {
      await tabs.nth(index).click();
      await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
      await expect(
        page.getByText("Не удалось отобразить страницу.", { exact: true }),
      ).toHaveCount(0);
    }
  }
  await page.goto("/base_stations");
  await page
    .getByRole("button", { name: "Изменить", exact: true })
    .first()
    .click();
  await expect(
    page.getByRole("dialog").getByRole("button", { name: "Сохранить станцию" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Отмена", exact: true }).click();
  await page.goto("/rovers");
  await page
    .getByRole("button", { name: "Изменить", exact: true })
    .first()
    .click();
  await expect(
    page
      .getByRole("dialog")
      .getByRole("button", { name: "Сохранить изменения" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Отмена", exact: true }).click();
  await page.goto("/dashboard");
  await expect(page.getByText("Передача", { exact: true })).toBeVisible();
  await page.screenshot({
    path: "../validation/ui/overview-desktop-ru.png",
    fullPage: true,
  });
  await page.goto("/system_configuration");
  await page.getByRole("tab", { name: "Уведомления", exact: true }).click();
  await expect(
    page.getByRole("combobox", { name: "Язык Telegram-бота" }),
  ).toBeVisible();
  await page.screenshot({
    path: "../validation/ui/telegram-settings-ru.png",
    fullPage: true,
  });
  expect(errors).toEqual([]);
});
for (const [path, title] of pages)
  test(`Russian page ${path}`, async ({ page }) => {
    const errors = [];
    page.on("pageerror", (e) => errors.push(e.message));
    await page.addInitScript(() => localStorage.setItem("gnss_language", "ru"));
    await page.goto(path);
    await expect(
      page.getByRole("heading", { name: title, exact: true }),
    ).toBeVisible();
    await expect(page.locator("html")).toHaveAttribute("lang", "ru");
    await expect(
      page.getByRole("combobox", { name: "Язык интерфейса" }),
    ).toBeVisible();
    expect(errors).toEqual([]);
  });

test("changing interface language preserves a draft and persists across navigation", async ({
  page,
}) => {
  await page.goto("/system_configuration");
  await page.getByLabel("System Name").fill("My test caster");
  await page.getByRole("combobox", { name: "Interface language" }).click();
  await page.getByRole("option", { name: "Русский", exact: true }).click();
  await expect(page.getByLabel("Имя системы")).toHaveValue("My test caster");
  // Save is explicit; reset the draft before navigating away.
  await page.getByLabel("Имя системы").fill("GNSS Caster");
  page.on("dialog", (dialog) => dialog.accept());
  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("lang", "ru");
  await page
    .getByRole("link", { name: "Резервные копии", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Резервные копии и восстановление" }),
  ).toBeVisible();
  await page.getByRole("combobox", { name: "Язык интерфейса" }).click();
  await page.getByRole("option", { name: "English", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Backups & restore" }),
  ).toBeVisible();
});

test("Telegram language saves independently from browser language", async ({
  page,
}) => {
  let payload;
  await page.addInitScript(() => localStorage.setItem("gnss_language", "ru"));
  await page.route("**/api/system/settings/update", (route) => {
    payload = route.request().postDataJSON();
    expect(route.request().headers()["x-csrf-token"]).toBe("preview-csrf");
    return route.fulfill({
      json: { message: "System settings updated", applied: {} },
    });
  });
  await page.goto("/system_configuration");
  await page.getByRole("tab", { name: "Уведомления", exact: true }).click();
  await expect(
    page.getByRole("combobox", { name: "Язык Telegram-бота" }),
  ).toHaveText("English");
  await page.getByRole("combobox", { name: "Язык Telegram-бота" }).click();
  await page.getByRole("option", { name: "Русский", exact: true }).click();
  await page.getByRole("button", { name: "Сохранить уведомления" }).click();
  await expect.poll(() => payload).toEqual({ telegram_language: "ru" });
  await expect(page.locator("html")).toHaveAttribute("lang", "ru");
});

test("Russian mobile pages fit and restore still needs the literal confirmation word", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.addInitScript(() => localStorage.setItem("gnss_language", "ru"));
  await page.goto("/dashboard");
  await expect(page.getByText("Передача", { exact: true })).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBeTruthy();
  await page.screenshot({
    path: "../validation/ui/overview-mobile-ru.png",
    fullPage: true,
  });
  await page.goto("/backups");
  await page
    .getByRole("button", { name: "Восстановить", exact: true })
    .first()
    .click();
  await expect(
    page.getByRole("dialog").getByText(/Код из архива не устанавливается/),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Подтвердить", exact: true }),
  ).toBeDisabled();
  await page
    .getByLabel("Введите RESTORE для подтверждения")
    .fill("ВОССТАНОВИТЬ");
  await expect(
    page.getByRole("button", { name: "Подтвердить", exact: true }),
  ).toBeDisabled();
  await page.getByLabel("Введите RESTORE для подтверждения").fill("RESTORE");
  await expect(
    page.getByRole("button", { name: "Подтвердить", exact: true }),
  ).toBeEnabled();
});
