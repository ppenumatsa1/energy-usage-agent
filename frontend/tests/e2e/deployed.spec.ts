import { expect, test, type Page } from "@playwright/test";

// End-to-end checks against a deployed environment:
//   E2E_BASE_URL=https://<web> E2E_TOKEN=<user token for the azd env API_SCOPE> npx playwright test deployed
// Interactive Entra sign-in (MFA) cannot be scripted, so the journey test swaps only the sign-in step:
// it serves a dev-mode config and hands the deployed UI a real user token. Everything after that is real:
// the deployed bundle, the /api proxy, app-api (OBO), the Foundry agent and energy-service.
const token = process.env.E2E_TOKEN;
const deployed = Boolean(process.env.E2E_BASE_URL);

test.describe("deployed app", () => {
  test.skip(!deployed, "set E2E_BASE_URL to run against a deployed environment");

  test("real config sends the user to Entra with the right app and scope", async ({ page }) => {
    const config = await (await page.request.get("/config.json")).json();
    expect(config.authMode).toBe("entra");
    expect(config.clientId).toBeTruthy();
    expect(config.apiScope).toMatch(/^api:\/\/.+\/Chat\.Ask$/);

    await page.route(/\/oauth2\/v2\.0\/authorize/, (route) => route.abort());
    await page.goto("/");
    await expect(page).toHaveTitle("Energy Usage Assistant");
    const authorize = page.waitForRequest(/\/oauth2\/v2\.0\/authorize/);
    await page.getByRole("button", { name: /Sign in with your work account/ }).click();
    const url = new URL((await authorize).url());
    expect(url.searchParams.get("client_id")).toBe(config.clientId);
    expect(url.searchParams.get("scope")).toContain(config.apiScope);
  });

  test.describe("signed-in journey", () => {
    test.skip(!token, "set E2E_TOKEN to a real user token");
    test.setTimeout(180_000);

    async function signIn(page: Page) {
      await page.route("**/config.json", (route) =>
        route.fulfill({ json: { authMode: "dev", clientId: "", authority: "", apiScope: "" } }),
      );
      await page.route("**/api/dev/users", (route) => route.fulfill({ json: [{ id: "e2e", label: "E2E user" }] }));
      await page.route("**/api/dev/token", (route) => route.fulfill({ json: { accessToken: token } }));
      await page.goto("/");
      await page.getByRole("button", { name: /E2E user/ }).click();
    }

    async function ask(page: Page, question: string) {
      const box = page.getByRole("textbox", { name: /ask about your energy usage/i });
      await box.fill(question);
      await box.press("Enter");
    }

    test("asks a question and gets text, table, chart and trace", async ({ page }) => {
      await signIn(page);
      await expect(page.getByText(/Demo Customer/).first()).toBeVisible({ timeout: 30_000 });

      await ask(page, "Show my daily usage for the last 7 days");
      await expect(page.getByRole("table")).toBeVisible({ timeout: 90_000 });
      await expect(page.getByText(/kWh/).first()).toBeVisible();
      await expect(page.locator(".result-chart .recharts-surface").first()).toBeVisible({ timeout: 15_000 });

      await page.getByRole("button", { name: /How this was answered/ }).first().click();
      await expect(page.getByText("get_usage").first()).toBeVisible();
      await expect(page.getByText("Numbers from tools").first()).toBeVisible();

      const nav = page.getByRole("navigation", { name: "Conversations" });
      await expect(nav.getByText(/Show my daily usage for the last 7 days/).first()).toBeVisible({ timeout: 30_000 });

      await ask(page, "Write me a poem about the ocean");
      await expect(page.getByText("Out of scope").first()).toBeVisible({ timeout: 90_000 });

      // Clean up: delete the conversation this test created (newest first in the list).
      const mine = nav.getByRole("button", { name: /^Delete conversation Show my daily usage/ });
      const before = await mine.count();
      await mine.first().click();
      await nav.getByRole("button", { name: "Delete", exact: true }).click();
      await expect(mine).toHaveCount(before - 1, { timeout: 30_000 });
    });
  });
});
