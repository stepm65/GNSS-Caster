import { test, expect } from "@playwright/test";

const bodyFont = (page) =>
  page.evaluate(() => getComputedStyle(document.body).fontFamily);

test("bundled fonts are the default and load without network fonts", async ({
  page,
}) => {
  const remote = [];
  page.on("request", (request) => {
    const url = request.url();
    if (/fonts\.(googleapis|gstatic)|\.woff2?(\?|$)/.test(url))
      remote.push(url);
  });
  await page.goto("/dashboard");
  await expect(page.getByRole("heading", { name: "Overview" })).toBeVisible();
  expect(await bodyFont(page)).toMatch(/^"Exo 2"/);
  await expect
    .poll(() =>
      page.evaluate(() =>
        [...document.fonts]
          .filter((face) => face.status === "loaded")
          .map((face) => face.family.replaceAll('"', "")),
      ),
    )
    .toEqual(expect.arrayContaining(["Exo 2", "JetBrains Mono"]));
  expect(remote).toEqual([]);
});

test("font choices apply at once and persist per browser", async ({ page }) => {
  await page.goto("/dashboard");
  await page.getByRole("button", { name: "Fonts" }).click();
  const menu = page.getByRole("menu", { name: "Fonts" });
  await expect(menu.getByText("Interface font")).toBeVisible();
  await expect(menu.getByText("Monospace font")).toBeVisible();
  // SF Mono is never bundled; the Linux test browser does not have it.
  await expect(
    menu.getByRole("menuitemradio", { name: /^SF Mono/ }),
  ).toContainText("Not installed on this device");
  await expect(menu.getByRole("menuitemradio")).toHaveCount(6);
  await expect(menu).not.toContainText("Anthropic");
  await menu.getByRole("menuitemradio", { name: /^Jura/ }).click();
  await expect.poll(() => bodyFont(page)).toMatch(/^"?Jura"?,/);
  // The menu stays open so both fonts can be chosen in one visit.
  await menu.getByRole("menuitemradio", { name: /^SF Mono/ }).click();
  await page.keyboard.press("Escape");
  await expect(menu).toBeHidden();
  await page.reload();
  expect(await bodyFont(page)).toMatch(/^"?Jura"?,/);
  const mono = await page.evaluate(() => {
    const code = document.createElement("code");
    document.body.append(code);
    const family = getComputedStyle(code).fontFamily;
    code.remove();
    return family;
  });
  expect(mono).toMatch(/^"SF Mono"/);

  await page.getByRole("button", { name: "Fonts" }).click();
  const items = page
    .getByRole("menu", { name: "Fonts" })
    .getByRole("menuitemradio");
  await expect(items.filter({ hasText: "Jura" })).toHaveAttribute(
    "aria-checked",
    "true",
  );
  await expect(items.filter({ hasText: "SF Mono" })).toHaveAttribute(
    "aria-checked",
    "true",
  );
});

test("Russian interface translates the font menu", async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem("gnss_language", "ru"));
  await page.goto("/dashboard");
  await page.getByRole("button", { name: "Шрифты" }).click();
  const menu = page.getByRole("menu", { name: "Шрифты" });
  await expect(menu.getByText("Шрифт интерфейса")).toBeVisible();
  await expect(menu.getByText("Моноширинный шрифт")).toBeVisible();
  await expect(
    menu.getByRole("menuitemradio", { name: /Системный/ }).first(),
  ).toBeVisible();
});
