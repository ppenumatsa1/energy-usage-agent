import { expect, test } from "@playwright/test";

// Minimal smoke test. Requires the app (and, for dev auth, the app API) to be running.
test("shows the sign-in screen", async ({ page }) => {
  await page.goto("/");
  await expect(page).toHaveTitle("Energy Usage Assistant");
  await expect(
    page.getByRole("heading", { name: /Dev sign-in|Energy Usage Assistant/ }).first(),
  ).toBeVisible();
});
