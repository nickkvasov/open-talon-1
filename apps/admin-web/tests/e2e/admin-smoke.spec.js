import { test, expect } from '@playwright/test';
import { attachBrowserLogging, openAdminPage, signInIfNeeded } from './helpers';

test('admin portal smoke flow works in a real browser', async ({ page }) => {
  attachBrowserLogging(page);

  await signInIfNeeded(page);
  await expect(page.getByRole('heading', { name: /runtime overview/i })).toBeVisible();
  await expect(page.getByText(/total token usage/i)).toBeVisible();
  await expect(page.getByText(/active queues/i)).toBeVisible();
  await expect(page.getByText(/failed executions \(24h\)/i)).toBeVisible();

  await openAdminPage(page, /identity & users/i, /identity & users/i);
  await expect(page.getByRole('link', { name: /open keycloak admin console/i })).toBeVisible();

  await openAdminPage(page, /swarm resources/i, /swarm resources/i);
  await expect(page.getByRole('heading', { name: /system agents/i })).toBeVisible();
  await expect(page.getByRole('heading', { name: /system tools/i })).toBeVisible();

  await openAdminPage(page, /^workspaces$/i, /workspace fleet/i);
  await expect(page.getByRole('button', { name: /create workspace/i })).toBeVisible();

  await openAdminPage(page, /^providers$/i, /infrastructure providers/i);
  await expect(page.getByRole('button', { name: /llm providers/i })).toBeVisible();
  await expect(page.getByRole('button', { name: /memory providers/i })).toBeVisible();

  await openAdminPage(page, /tool generation/i, /tool generation/i);
  await expect(page.getByRole('combobox')).toBeVisible();

  await openAdminPage(page, /api keys/i, /api keys management/i);

  const keyName = `playwright-smoke-${Date.now()}`;
  await page.getByRole('button', { name: /new api key/i }).click();
  await page.getByLabel(/key name/i).fill(keyName);
  await page.getByRole('button', { name: /^generate$/i }).click();

  await expect(page.getByText(/api key created successfully/i)).toBeVisible();
  await expect(page.getByText(keyName)).toBeVisible();

  const row = page.locator('tr', { hasText: keyName });
  await row.getByRole('button', { name: /revoke key/i }).click();
  await page.getByRole('button', { name: /^delete$/i }).click();
  await expect(page.getByText(keyName)).not.toBeVisible();
});

test('seeded agent profiles are visible in swarm resources', async ({ page }) => {
  attachBrowserLogging(page);

  await signInIfNeeded(page);
  await openAdminPage(page, /swarm resources/i, /swarm resources/i);

  const researcherProfile = page.getByTestId('system-agent-profile-researcher');
  await expect(researcherProfile).toBeVisible();
  await expect(researcherProfile).toContainText('Seeded profile');
  await expect(researcherProfile).toContainText('methodology_research_dossier_specialist');
  await expect(researcherProfile).toContainText(
    'dossier knowledge storage over retained data and indexed information',
  );

  const conductorProfile = page.getByTestId('system-agent-profile-conductor');
  await expect(conductorProfile).toContainText('workspace_methodics_execution_specialist');
});
