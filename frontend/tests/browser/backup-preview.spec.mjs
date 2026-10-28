import { test, expect } from "@playwright/test";
import { backupPreview } from "../backup-preview.mjs";

async function openRestore(page) {
  await page.goto("/backups");
  await page
    .getByRole("button", { name: "Restore", exact: true })
    .first()
    .click();
}

test("incompatible preview shows the reason and cannot be confirmed", async ({
  page,
}) => {
  await page.route("**/api/system/backups/preview", (route) =>
    route.fulfill({
      json: {
        ...backupPreview,
        compatible: false,
        source_version: "3.5.0",
        reasons: ["This backup was created by a newer application version."],
      },
    }),
  );
  await openRestore(page);
  await expect(
    page.getByText("This backup was created by a newer application version.", {
      exact: true,
    }),
  ).toBeVisible();
  await page.getByLabel("Type RESTORE to confirm").fill("RESTORE");
  await expect(
    page.getByRole("button", { name: "Confirm", exact: true }),
  ).toBeDisabled();
});

test("legacy preview shows what changes and requires acknowledgement", async ({
  page,
}) => {
  await page.route("**/api/system/backups/preview", (route) =>
    route.fulfill({
      json: {
        ...backupPreview,
        legacy: true,
        source_version: null,
        created_at: null,
        warnings: [
          "Legacy backup: application version and data contract are not recorded.",
        ],
      },
    }),
  );
  await openRestore(page);
  await expect(
    page.getByText(
      "Legacy backup: application version and data contract are not recorded.",
      { exact: true },
    ),
  ).toBeVisible();
  await expect(page.getByText("Keep installed", { exact: true })).toHaveCount(
    2,
  );
  await expect(
    page.getByText("Restore from backup", { exact: true }),
  ).toHaveCount(2);
  await page.getByLabel("Type RESTORE to confirm").fill("RESTORE");
  await expect(
    page.getByRole("button", { name: "Confirm", exact: true }),
  ).toBeDisabled();
  await page
    .getByRole("checkbox", {
      name: "I understand the limitations of this legacy backup.",
    })
    .check();
  await expect(
    page.getByRole("button", { name: "Confirm", exact: true }),
  ).toBeEnabled();
  await page.screenshot({
    path: test.info().outputPath("restore-preview.png"),
  });
});

test("failed preview stays disabled and changed archive requires fresh inspection", async ({
  page,
}) => {
  let inspections = 0;
  await page.route("**/api/system/backups/preview", (route) => {
    inspections++;
    return route.fulfill(
      inspections === 1
        ? {
            status: 400,
            json: { error: "Backup component sizes or checksums do not match" },
          }
        : { json: backupPreview },
    );
  });
  await page.route("**/api/system/backups/restore", (route) =>
    route.fulfill({
      status: 409,
      json: {
        error:
          "Backup changed since preview; inspect it again before restoring",
      },
    }),
  );
  await openRestore(page);
  await expect(
    page.getByText("Backup component sizes or checksums do not match", {
      exact: true,
    }),
  ).toBeVisible();
  await page.getByLabel("Type RESTORE to confirm").fill("RESTORE");
  await expect(
    page.getByRole("button", { name: "Confirm", exact: true }),
  ).toBeDisabled();
  await page
    .getByRole("button", { name: "Inspect backup", exact: true })
    .click();
  await expect(
    page.getByText("Compatible with this installation", { exact: true }),
  ).toBeVisible();
  await page.getByLabel("Type RESTORE to confirm").fill("RESTORE");
  await page.getByRole("button", { name: "Confirm", exact: true }).click();
  await expect(
    page.getByText(
      "Backup changed since preview; inspect it again before restoring",
      { exact: true },
    ),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Confirm", exact: true }),
  ).toBeDisabled();
  await expect(page.getByLabel("Type RESTORE to confirm")).toHaveValue("");
});
