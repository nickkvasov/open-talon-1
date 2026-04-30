import { test, expect } from '@playwright/test';
import {
  attachBrowserLogging,
  buildAdminActor,
  createOrganizationViaApi,
  ensureCurrentUserOrganizationMembership,
  expectApiOk,
  getCurrentUser,
  openAdminPage,
  seedPendingApprovalToolGenerationRequest,
  signInIfNeeded,
  uniqueName,
} from './helpers';

test.describe.configure({ mode: 'serial' });

test.beforeEach(async ({ page }) => {
  attachBrowserLogging(page);
  await signInIfNeeded(page);
});

test('organizations can be created and memberships can be added and removed', async ({
  page,
  browser,
  baseURL,
}) => {
  const organizationName = uniqueName('playwright-org-admin');
  const organizationSlug = organizationName.toLowerCase().replace(/[^a-z0-9]+/g, '-');
  const secondaryContext = await browser.newContext({ baseURL });
  const secondaryPage = await secondaryContext.newPage();
  attachBrowserLogging(secondaryPage);
  await signInIfNeeded(secondaryPage, {
    username: process.env.ADMIN_WEB_E2E_SECONDARY_USERNAME || 'user1',
    password: process.env.ADMIN_WEB_E2E_SECONDARY_PASSWORD || 'user12345',
  });
  const secondaryUser = await getCurrentUser(secondaryPage);
  await secondaryContext.close();

  await openAdminPage(page, /^organizations$/i, /^organizations$/i);

  const createOrganizationForm = page.locator('form').filter({
    has: page.getByText(/create organization/i),
  });
  const membershipForm = page.locator('form').filter({
    has: page.getByRole('button', { name: /add member/i }),
  });
  await createOrganizationForm.locator('input').nth(0).fill(organizationSlug);
  await createOrganizationForm.locator('input').nth(1).fill(organizationName);
  await createOrganizationForm.locator('textarea').nth(0).fill('Organization created by Playwright.');
  await createOrganizationForm.locator('button[type="submit"]').click();

  const organizationButton = page.getByRole('button', { name: new RegExp(organizationName, 'i') });
  await expect(organizationButton).toBeVisible();
  await organizationButton.click();

  await membershipForm.locator('input').first().fill(secondaryUser.user_id);
  await membershipForm.locator('select').selectOption('member');
  await membershipForm.locator('button[type="submit"]').click();

  const membershipRow = page.getByText(secondaryUser.user_id, { exact: true }).locator('xpath=ancestor::div[contains(@class,"px-4")][1]');
  await expect(membershipRow).toBeVisible();
  await membershipRow.locator('button').click();
  await expect(page.getByText(secondaryUser.user_id, { exact: true })).not.toBeVisible();
});

test('workspaces support editing and role override management', async ({ page }) => {
  const workspaceName = uniqueName('playwright-workspace-detail');
  const updatedWorkspaceName = `${workspaceName}-updated`;
  const roleName = uniqueName('reviewer').replace(/[^a-z0-9_]+/gi, '_').toLowerCase();
  const organization = await createOrganizationViaApi(page, uniqueName('playwright-workspace-org'));
  await ensureCurrentUserOrganizationMembership(page, organization.organization_id);

  await expectApiOk(page, 'POST', '/v1/workspaces', {
    actor: buildAdminActor(),
    organization_id: organization.organization_id,
    name: workspaceName,
    description: 'Workspace created by Playwright for detail coverage.',
    metadata: { source: 'playwright' },
  });

  await openAdminPage(page, /^workspaces$/i, /workspace fleet/i);
  await page.locator('select').first().selectOption({ label: organization.name });

  let workspaceCard = page
    .getByRole('heading', { name: workspaceName, exact: true })
    .locator('xpath=ancestor::div[contains(@class,"group")][1]');
  await workspaceCard.hover();
  await workspaceCard.locator('button').first().click();
  await expect(page.getByRole('heading', { name: /update workspace/i })).toBeVisible();
  await page.getByPlaceholder(/project talon core/i).fill(updatedWorkspaceName);
  await page.getByPlaceholder(/what is the scope of this workspace/i).fill('Updated by Playwright.');
  await page.getByRole('button', { name: /^update$/i }).click();

  await expect(page.getByRole('heading', { name: updatedWorkspaceName, exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: /add role override/i })).toBeVisible();
  await page.getByRole('button', { name: /add role override/i }).click();
  await page.getByPlaceholder(/unique role identifier/i).fill(roleName);
  await page.getByPlaceholder(/natural language definition or system policy rules/i).fill(
    'Reviews rollout safety and production risk before release.',
  );
  await page.getByRole('button', { name: /commit definition/i }).click();
  await expect(page.getByText(roleName, { exact: true })).toBeVisible();

  const roleCard = page
    .getByText(roleName, { exact: true })
    .locator('xpath=ancestor::div[contains(@class,"group")][1]');
  await roleCard.locator('button[type="button"]').click();
  await page.getByRole('button', { name: /^delete$/i }).click();
  await expect(page.getByText(roleName, { exact: true })).not.toBeVisible();

  const detailModal = page
    .getByRole('heading', { name: updatedWorkspaceName, exact: true })
    .locator('xpath=ancestor::div[contains(@class,"fixed")][1]');
  await detailModal.locator('button').first().click();
  await expect(page.getByRole('button', { name: /create workspace/i })).toBeVisible();
});

test('swarm resources support editing global resources and creating organization scoped resources', async ({ page }) => {
  const agentName = uniqueName('playwright-agent-edit');
  const updatedAgentName = uniqueName('playwright-agent-updated');
  const toolName = uniqueName('playwright_tool_edit');
  const updatedToolName = uniqueName('playwright_tool_updated');
  const organization = await createOrganizationViaApi(page, uniqueName('playwright-swarm-org'));

  await expectApiOk(page, 'POST', '/v1/agents', {
    actor: buildAdminActor(),
    display_name: agentName,
    description: 'Created by Playwright for edit coverage.',
    role: 'software_engineer',
    capabilities: ['execute_code'],
    endpoint: { kind: 'local', model: 'gpt-4o-mini', provider: 'openai' },
    system_prompt: 'Review and edit code carefully.',
    interaction_contract: {
      instructions: [],
      completion_criteria: [],
      response_contract: { content_type: 'text/markdown', json_mode: false },
    },
  });
  await expectApiOk(page, 'POST', '/v1/tools', {
    actor: buildAdminActor(),
    name: toolName,
    description: 'Created by Playwright for edit coverage.',
    parameter_contract: { strategy: 'strict' },
    input_schema: {
      type: 'object',
      properties: {},
      required: [],
    },
    execution: {
      strategy: 'webhook',
      config: { url: 'https://example.com/hooks/playwright' },
    },
  });

  await openAdminPage(page, /swarm resources/i, /swarm resources/i);

  let agentRow = page
    .getByText(agentName, { exact: true })
    .locator('xpath=ancestor::div[contains(@class,"p-5")][1]');
  await agentRow.locator('button[title="Edit Agent"]').click();
  await expect(page.getByRole('heading', { name: /update system agent/i })).toBeVisible();
  await page.getByPlaceholder(/code architect/i).fill(updatedAgentName);
  await page.getByRole('button', { name: /update agent/i }).click();
  await expect(page.getByText(updatedAgentName, { exact: true })).toBeVisible();

  let toolRow = page
    .getByText(toolName, { exact: true })
    .locator('xpath=ancestor::div[contains(@class,"p-5")][1]');
  await toolRow.locator('button[title="Edit Tool"]').click();
  await expect(page.getByRole('heading', { name: /update system tool/i })).toBeVisible();
  await page.getByPlaceholder(/github_search/i).fill(updatedToolName);
  await page.getByRole('button', { name: /update tool/i }).click();
  await expect(page.getByText(updatedToolName, { exact: true })).toBeVisible();

  await page.getByRole('button', { name: /^organization$/i }).click();
  await page.locator('select').first().selectOption({ label: organization.name });

  const orgAgentName = uniqueName('playwright-org-agent');
  const orgToolName = uniqueName('playwright_org_tool');

  await page.getByRole('button', { name: /add agent/i }).click();
  await page.getByPlaceholder(/code architect/i).fill(orgAgentName);
  await page.getByPlaceholder(/software_engineer/i).fill('playwright_org_agent');
  await page.getByPlaceholder(/what is this agent specialized for/i).fill('Organization-scoped agent created by Playwright.');
  await page.getByPlaceholder(/openai/i).fill('openai');
  await page.getByPlaceholder(/gpt-4o/i).fill('gpt-4o-mini');
  await page.getByPlaceholder(/comma-separated keys/i).fill('execute_code');
  await page.getByRole('button', { name: /create agent/i }).click();
  await expect(page.getByText(orgAgentName, { exact: true })).toBeVisible();

  await page.getByRole('button', { name: /add tool/i }).click();
  await page.getByPlaceholder(/github_search/i).fill(orgToolName);
  await page.getByPlaceholder(/detailed description for the llm discovery/i).fill('Organization-scoped tool created by Playwright.');
  await page.getByPlaceholder('https://...').fill('https://example.com/hooks/playwright-org');
  await page.locator('textarea').filter({ hasNot: page.getByPlaceholder(/detailed description/i) }).last().fill('{\n  "type": "object",\n  "properties": {},\n  "required": []\n}');
  await page.getByRole('button', { name: /register tool/i }).click();
  await expect(page.getByText(orgToolName, { exact: true })).toBeVisible();
});

test('providers support llm editing, health checks, and organization scoped memory providers', async ({ page }) => {
  const llmName = uniqueName('Playwright LLM Provider');
  const updatedLlmName = `${llmName} Updated`;
  const llmKey = uniqueName('playwright-llm');
  const organization = await createOrganizationViaApi(page, uniqueName('playwright-provider-org'));

  await openAdminPage(page, /^providers$/i, /infrastructure providers/i);

  await page.getByRole('button', { name: /add provider/i }).click();
  await expect(page.getByRole('heading', { name: /configure new llm provider/i })).toBeVisible();
  await page.getByPlaceholder(/gpt-4, claude-3/i).fill(llmKey);
  await page.getByPlaceholder(/openai gpt-4/i).fill(llmName);
  await page.getByPlaceholder(/brief description of this provider/i).fill('Global LLM provider created by Playwright.');
  await page.getByPlaceholder(/https:\/\/api\.openai\.com\/v1/i).fill('http://127.0.0.1:8000/healthz');
  await page.getByPlaceholder(/gpt-4o/i).fill('gpt-4o-mini');
  await page.getByPlaceholder(/chat, vision, tool_use/i).fill('chat, reasoning');
  await page.getByRole('button', { name: /create provider/i }).click();
  await expect(page.getByText(llmName, { exact: true })).toBeVisible();

  let llmCard = page
    .getByText(llmName, { exact: true })
    .locator('xpath=ancestor::div[contains(@class,"rounded-xl")][1]');
  const llmHealthDialog = page.waitForEvent('dialog');
  await llmCard.getByRole('button', { name: /run health check/i }).click();
  const llmDialog = await llmHealthDialog;
  expect(llmDialog.message()).toContain('Provider Status:');
  await llmDialog.accept();

  await llmCard.locator('button[title="Edit Provider"]').click();
  await page.getByPlaceholder(/openai gpt-4/i).fill(updatedLlmName);
  await page.getByRole('button', { name: /update provider/i }).click();
  await expect(page.getByText(updatedLlmName, { exact: true })).toBeVisible();

  llmCard = page
    .getByText(updatedLlmName, { exact: true })
    .locator('xpath=ancestor::div[contains(@class,"rounded-xl")][1]');
  await llmCard.locator('button[title="Delete Provider"]').click();
  await page.getByRole('button', { name: /^delete$/i }).click();
  await expect(page.getByText(updatedLlmName, { exact: true })).not.toBeVisible();

  await page.getByRole('button', { name: /memory providers/i }).click();
  await page.getByRole('button', { name: /^organization$/i }).click();
  await page.locator('select').first().selectOption({ label: organization.name });

  const memoryName = uniqueName('Playwright Memory Provider');
  const updatedMemoryName = `${memoryName} Updated`;
  const memoryKey = uniqueName('playwright-memory-org');

  await page.getByRole('button', { name: /add provider/i }).click();
  await expect(page.getByRole('heading', { name: /configure new memory provider/i })).toBeVisible();
  await page.getByPlaceholder(/pg-vector, redis-search/i).fill(memoryKey);
  await page.getByPlaceholder(/postgres vector store/i).fill(memoryName);
  await page.getByPlaceholder(/brief description of this memory provider/i).fill('Organization memory provider created by Playwright.');
  await page.getByPlaceholder('{ "host": "localhost", "port": 5432 }').fill('{"database":"app_db"}');
  await page.getByPlaceholder('{ "password": "..." }').fill('{}');
  await page.getByRole('button', { name: /create provider/i }).click();
  await expect(page.getByText(memoryName, { exact: true })).toBeVisible();

  let memoryCard = page
    .getByText(memoryName, { exact: true })
    .locator('xpath=ancestor::div[contains(@class,"rounded-xl")][1]');
  const memoryHealthDialog = page.waitForEvent('dialog');
  await memoryCard.getByRole('button', { name: /run health check/i }).click();
  const memoryDialog = await memoryHealthDialog;
  expect(memoryDialog.message()).toContain('Provider Status: healthy');
  await memoryDialog.accept();

  await memoryCard.locator('button[title="Edit Provider"]').click();
  await page.getByPlaceholder(/postgres vector store/i).fill(updatedMemoryName);
  await page.getByRole('button', { name: /update provider/i }).click();
  await expect(page.getByText(updatedMemoryName, { exact: true })).toBeVisible();

  memoryCard = page
    .getByText(updatedMemoryName, { exact: true })
    .locator('xpath=ancestor::div[contains(@class,"rounded-xl")][1]');
  await memoryCard.locator('button[title="Delete Provider"]').click();
  await page.getByRole('button', { name: /^delete$/i }).click();
  await expect(page.getByText(updatedMemoryName, { exact: true })).not.toBeVisible();
});

test('tool generation requests can be reviewed and rejected from the admin web', async ({ page }) => {
  const seed = await seedPendingApprovalToolGenerationRequest(page);
  const requestRowName = new RegExp(seed.toolName.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'));

  await openAdminPage(page, /tool generation/i, /tool generation/i);
  await page.getByRole('button', { name: requestRowName }).click();
  await expect(page.getByRole('heading', { name: seed.toolName, exact: true })).toBeVisible();
  await page.getByPlaceholder(/optional approval or rejection note/i).fill('Rejected by Playwright coverage test.');
  await page.getByRole('button', { name: /^reject$/i }).click();
  await expect(page.getByRole('heading', { name: seed.toolName, exact: true })).toBeVisible();
  await expect(page.getByText(/#1 · rejected/i)).toBeVisible();

  await page.locator('select').first().selectOption('rejected');
  await expect(page.getByRole('button', { name: requestRowName })).toBeVisible();
});
