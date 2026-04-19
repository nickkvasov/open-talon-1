import { test, expect } from '@playwright/test';
import {
  attachBrowserLogging,
  openAdminPage,
  signInIfNeeded,
  uniqueName,
} from './helpers';

test.describe.configure({ mode: 'serial' });

test.beforeEach(async ({ page }) => {
  attachBrowserLogging(page);
  await signInIfNeeded(page);
});

test('workspaces can be created and deleted', async ({ page }) => {
  const organizationName = uniqueName('playwright-org');
  const organizationSlug = organizationName.toLowerCase().replace(/[^a-z0-9]+/g, '-');
  const workspaceName = uniqueName('playwright-workspace');

  await openAdminPage(page, /^workspaces$/i, /workspace fleet/i);
  const organizationSelect = page.locator('select').first();
  await expect(organizationSelect).toBeVisible();
  let options = await organizationSelect.locator('option').evaluateAll((nodes) =>
    nodes.map((node) => node.value).filter(Boolean)
  );
  if (options.length === 0) {
    await openAdminPage(page, /^organizations$/i, /^organizations$/i);
    const createOrganizationForm = page.locator('form').filter({
      has: page.getByText(/create organization/i),
    });
    await createOrganizationForm.locator('input').nth(0).fill(organizationSlug);
    await createOrganizationForm.locator('input').nth(1).fill(organizationName);
    await createOrganizationForm.locator('textarea').nth(0).fill('Organization created by Playwright.');
    await createOrganizationForm.locator('button[type="submit"]').click();
    await expect(page.getByText(organizationName, { exact: true })).toBeVisible();

    await openAdminPage(page, /^workspaces$/i, /workspace fleet/i);
    options = await organizationSelect.locator('option').evaluateAll((nodes) =>
      nodes.map((node) => node.value).filter(Boolean)
    );
  }
  const selectedValue = await organizationSelect.inputValue();
  if (!selectedValue && options.length > 0) {
    await organizationSelect.selectOption(options[0]);
  }

  await page.getByRole('button', { name: /create workspace/i }).click();
  await expect(page.getByRole('heading', { name: /create workspace/i })).toBeVisible();
  await page.getByPlaceholder(/project talon core/i).fill(workspaceName);
  await page.getByPlaceholder(/what is the scope of this workspace/i).fill('Workspace created by Playwright.');
  await page.getByPlaceholder('{}').fill('{"source":"playwright"}');
  await page.getByRole('button', { name: /^create$/i }).click();

  await expect(page.getByRole('heading', { name: workspaceName, exact: true })).toBeVisible();

  const workspaceCard = page
    .getByRole('heading', { name: workspaceName, exact: true })
    .locator('xpath=ancestor::div[contains(@class,"group")][1]');

  await workspaceCard.hover();
  await workspaceCard.locator('button[type="button"]').click();
  await page.getByRole('button', { name: /^delete$/i }).click();
  await expect(page.getByRole('heading', { name: workspaceName, exact: true })).not.toBeVisible();
});

test('swarm resources can create and delete an agent and tool', async ({ page }) => {
  const agentName = uniqueName('playwright-agent');
  const toolName = uniqueName('playwright_tool');

  await openAdminPage(page, /swarm resources/i, /swarm resources/i);

  await page.getByRole('button', { name: /add agent/i }).click();
  await expect(page.getByRole('heading', { name: /provision new system agent/i })).toBeVisible();
  await page.getByPlaceholder(/code architect/i).fill(agentName);
  await page.getByPlaceholder(/software_engineer/i).fill('playwright_agent');
  await page.getByPlaceholder(/what is this agent specialized for/i).fill('Created in browser automation.');
  await page.getByPlaceholder(/openai/i).fill('openai');
  await page.getByPlaceholder(/gpt-4o/i).fill('gpt-4o-mini');
  await page.getByPlaceholder(/comma-separated keys/i).fill('execute_code,review_code');
  const createAgentResponse = page.waitForResponse(
    (response) =>
      response.request().method() === 'POST' &&
      /\/v1\/agents$/.test(response.url()) &&
      response.ok()
  );
  await page.getByRole('button', { name: /create agent/i }).click();
  await createAgentResponse;

  await expect(page.getByText(agentName, { exact: true })).toBeVisible();

  const agentRow = page
    .getByText(agentName, { exact: true })
    .locator('xpath=ancestor::div[contains(@class,"p-5")][1]');
  const deleteAgentResponse = page.waitForResponse(
    (response) =>
      response.request().method() === 'DELETE' &&
      /\/v1\/agents\//.test(response.url()) &&
      response.ok()
  );
  await agentRow.locator('button[title="Delete Agent"]').click();
  await page.getByRole('button', { name: /^delete$/i }).click();
  await deleteAgentResponse;
  await page.reload();
  await expect(page.getByRole('heading', { name: /swarm resources/i })).toBeVisible();
  await expect(page.getByText(agentName, { exact: true })).not.toBeVisible();

  await page.getByRole('button', { name: /add tool/i }).click();
  await expect(page.getByRole('heading', { name: /define new system tool/i })).toBeVisible();
  await page.getByPlaceholder(/github_search/i).fill(toolName);
  await page.getByPlaceholder(/detailed description for the llm discovery/i).fill('Playwright test tool.');
  await page.getByPlaceholder('https://...').fill('https://example.com/hooks/playwright');
  await page.locator('textarea').filter({ hasNot: page.getByPlaceholder(/detailed description/i) }).last().fill('{\n  "type": "object",\n  "properties": {},\n  "required": []\n}');
  const createToolResponse = page.waitForResponse(
    (response) =>
      response.request().method() === 'POST' &&
      /\/v1\/tools$/.test(response.url()) &&
      response.ok()
  );
  await page.getByRole('button', { name: /register tool/i }).click();
  await createToolResponse;

  await expect(page.getByText(toolName, { exact: true })).toBeVisible();

  const toolRow = page
    .getByText(toolName, { exact: true })
    .locator('xpath=ancestor::div[contains(@class,"p-5")][1]');
  const deleteToolResponse = page.waitForResponse(
    (response) =>
      response.request().method() === 'DELETE' &&
      /\/v1\/tools\//.test(response.url()) &&
      response.ok()
  );
  await toolRow.locator('button[title="Delete Tool"]').click();
  await page.getByRole('button', { name: /^delete$/i }).click();
  await deleteToolResponse;
  await page.reload();
  await expect(page.getByRole('heading', { name: /swarm resources/i })).toBeVisible();
  await expect(page.getByText(toolName, { exact: true })).not.toBeVisible();
});

test('providers support tab switching and memory provider create delete flow', async ({ page }) => {
  const providerKey = uniqueName('playwright-memory');
  const providerName = uniqueName('Playwright Memory Provider');

  await openAdminPage(page, /^providers$/i, /infrastructure providers/i);

  await page.getByRole('button', { name: /memory providers/i }).click();
  await expect(page.getByRole('button', { name: /memory providers/i })).toBeVisible();

  await page.getByRole('button', { name: /add provider/i }).click();
  await expect(page.getByRole('heading', { name: /configure new memory provider/i })).toBeVisible();
  await page.getByPlaceholder(/pg-vector, redis-search/i).fill(providerKey);
  await page.getByPlaceholder(/postgres vector store/i).fill(providerName);
  await page.getByPlaceholder(/brief description of this memory provider/i).fill('Created by Playwright.');
  await page.getByPlaceholder('{ "host": "localhost", "port": 5432 }').fill('{"index":"playwright"}');
  await page.getByPlaceholder('{ "password": "..." }').fill('{"token":"playwright"}');
  const createProviderResponse = page.waitForResponse(
    (response) =>
      response.request().method() === 'POST' &&
      /\/v1\/memory-providers$/.test(response.url()) &&
      response.ok()
  );
  await page.getByRole('button', { name: /create provider/i }).click();
  await createProviderResponse;

  await expect(page.getByText(providerName, { exact: true })).toBeVisible();

  const providerCard = page
    .getByText(providerName, { exact: true })
    .locator('xpath=ancestor::div[contains(@class,"rounded-xl")][1]');
  const deleteProviderResponse = page.waitForResponse(
    (response) =>
      response.request().method() === 'DELETE' &&
      /\/v1\/memory-providers\//.test(response.url()) &&
      response.ok()
  );
  await providerCard.locator('button[title="Delete Provider"]').click();
  await page.getByRole('button', { name: /^delete$/i }).click();
  await deleteProviderResponse;
  await page.reload();
  await expect(page.getByRole('heading', { name: /infrastructure providers/i })).toBeVisible();
  await page.getByRole('button', { name: /memory providers/i }).click();
  await expect(page.getByText(providerName, { exact: true })).not.toBeVisible();
});
