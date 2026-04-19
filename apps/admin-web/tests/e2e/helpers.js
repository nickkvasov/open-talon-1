import { expect } from '@playwright/test';

const username = process.env.ADMIN_WEB_E2E_USERNAME || 'admin';
const password = process.env.ADMIN_WEB_E2E_PASSWORD || 'admin123';

export function attachBrowserLogging(page) {
  page.on('requestfailed', (request) => {
    console.log(`requestfailed ${request.method()} ${request.url()} :: ${request.failure()?.errorText}`);
  });
  page.on('console', (message) => {
    if (message.type() === 'error') {
      console.log(`console.${message.type()} ${message.text()}`);
    }
  });
}

export async function signInIfNeeded(page) {
  await page.goto('/');

  const signInButton = page.getByRole('button', { name: /sign in with keycloak/i });
  const runtimeOverviewHeading = page.getByRole('heading', { name: /runtime overview/i });
  await Promise.race([
    signInButton.waitFor({ state: 'visible', timeout: 5000 }).catch(() => null),
    runtimeOverviewHeading.waitFor({ state: 'visible', timeout: 5000 }).catch(() => null),
  ]);

  if (await signInButton.isVisible().catch(() => false)) {
    await signInButton.click();
    await page.waitForURL(/realms\/open-talon/i);
    await page.locator('input[name="username"]').fill(username);
    await page.locator('input[name="password"]').fill(password);
    await page.locator('button[type="submit"], input[type="submit"]').click();
  }

  await expect(runtimeOverviewHeading).toBeVisible();
}

export async function openAdminPage(page, linkName, headingName) {
  await page.getByRole('link', { name: linkName }).click();
  await expect(page.getByRole('heading', { name: headingName })).toBeVisible();
}

export function uniqueName(prefix) {
  return `${prefix}-${Date.now()}`;
}
