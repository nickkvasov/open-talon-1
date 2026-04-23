import { test, expect } from '@playwright/test';

import {
  apiRequest,
  attachBrowserLogging,
  buildAdminActor,
  createOrganizationViaApi,
  ensureCurrentUserOrganizationMembership,
  expectApiOk,
  openAdminPage,
  seedPendingApprovalToolGenerationRequest,
  signInIfNeeded,
  uniqueName,
} from './helpers';

test('tool generation requests can be approved from the admin web', async ({ page }) => {
  attachBrowserLogging(page);
  await signInIfNeeded(page);
  const seed = await seedPendingApprovalToolGenerationRequest(page, {
    requestedScope: 'organization',
    useSeededToolGenerationAgent: true,
  });

  await openAdminPage(page, /tool generation/i, /tool generation/i);
  await page.getByRole('button', { name: new RegExp(seed.toolName.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')) }).click();
  await expect(page.getByRole('heading', { name: seed.toolName, exact: true })).toBeVisible();
  await page.getByPlaceholder(/optional approval or rejection note/i).fill('Approved by Playwright error-path coverage.');
  const approveResponsePromise = page.waitForResponse(
    (response) => response.request().method() === 'POST'
      && response.url().endsWith(`/v1/tool-generation/revisions/${seed.revisionId}/approve`),
  );
  await page.getByRole('button', { name: /^approve$/i }).click();
  const approveResponse = await approveResponsePromise;
  if (!approveResponse.ok()) {
    throw new Error(`Approve failed with ${approveResponse.status()}: ${await approveResponse.text()}`);
  }
  const approveBody = await approveResponse.json();
  expect(approveBody.request.status).toBe('verifying_registry_pull');

  await expect(page.getByText(/#1 · verifying_registry_pull/i)).toBeVisible();
  await expect(page.getByText(/Immutable ref:/i)).toBeVisible();
  await expect(page.getByRole('button', { name: /^approve$/i })).toBeDisabled();
});

test('providers surface unhealthy health checks', async ({ page }) => {
  attachBrowserLogging(page);
  await signInIfNeeded(page);

  const providerName = uniqueName('Playwright Broken LLM');
  const createResponse = await expectApiOk(page, 'POST', '/v1/llm-providers', {
    actor: buildAdminActor(),
    engine_id: uniqueName('playwright-broken-llm'),
    display_name: providerName,
    description: 'Provider created by Playwright to exercise unhealthy health checks.',
    provider: 'openai',
    endpoint_kind: 'remote',
    url: 'not-a-url',
    secret_config: { env: { name: 'MISSING_OPENAI_API_KEY' } },
  });
  const providerId = createResponse.provider_id;

  await openAdminPage(page, /^providers$/i, /infrastructure providers/i);
  const llmCard = page
    .getByText(providerName, { exact: true })
    .locator('xpath=ancestor::div[contains(@class,"rounded-xl")][1]');
  const healthDialogPromise = page.waitForEvent('dialog');
  await llmCard.getByRole('button', { name: /run health check/i }).click();
  const healthDialog = await healthDialogPromise;
  expect(healthDialog.message()).toContain('Provider Status: unhealthy');
  await healthDialog.accept();

  const deleteResponse = await apiRequest(page, 'DELETE', `/v1/llm-providers/${providerId}`, {
    actor: buildAdminActor(),
  });
  expect(deleteResponse.ok).toBe(true);
});

test('non-admin dashboard surfaces permission errors', async ({ page }) => {
  attachBrowserLogging(page);
  await signInIfNeeded(page, { username: 'user1', password: 'user12345' });

  await expect(page.getByRole('heading', { name: /runtime overview/i })).toBeVisible();
  await expect(page.getByText(/request failed with status code 403/i)).toBeVisible();
});

test('non-member workspace detail requests return 404 in authenticated browser sessions', async ({ browser }) => {
  const adminContext = await browser.newContext();
  const adminPage = await adminContext.newPage();
  attachBrowserLogging(adminPage);
  await signInIfNeeded(adminPage);

  const organization = await createOrganizationViaApi(adminPage, uniqueName('playwright-404-org'));
  await ensureCurrentUserOrganizationMembership(adminPage, organization.organization_id);
  const workspace = await expectApiOk(adminPage, 'POST', '/v1/workspaces', {
    actor: buildAdminActor(),
    organization_id: organization.organization_id,
    name: uniqueName('playwright-404-workspace'),
    description: 'Workspace used to verify non-member 404 behavior.',
    metadata: { source: 'playwright' },
  });
  const workspaceId = workspace.workspace.workspace_id;

  const userContext = await browser.newContext();
  const userPage = await userContext.newPage();
  attachBrowserLogging(userPage);
  await signInIfNeeded(userPage, { username: 'user1', password: 'user12345' });

  const response = await apiRequest(userPage, 'GET', `/v1/workspaces/${workspaceId}`);
  expect(response.status).toBe(404);

  await userContext.close();
  await adminContext.close();
});
