import { createServer } from 'node:http';

import { test, expect } from '@playwright/test';
import {
  apiRequest,
  attachBrowserLogging,
  buildAdminActor,
  createOrganizationViaApi,
  ensureCurrentUserOrganizationMembership,
  expectApiOk,
  openAdminPage,
  signInIfNeeded,
  uniqueName,
} from './helpers';

test.describe.configure({ mode: 'serial' });

test.beforeEach(async ({ page }) => {
  attachBrowserLogging(page);
  await signInIfNeeded(page);
});

test('system plugins can be registered, synced, and attached to a workspace', async ({ page }) => {
  const mcpServer = await startMcpFixture();
  const pluginKey = uniqueName('playwright_plugin').replace(/[^a-z0-9_]+/gi, '_').toLowerCase();
  const pluginName = uniqueName('Playwright System Plugin');
  const prefix = `${pluginKey}__`;
  let pluginId = null;

  try {
    await openAdminPage(page, /swarm resources/i, /swarm resources/i);
    await expect(page.getByRole('heading', { name: /system plugins/i })).toBeVisible();

    await page.locator('button[title="Add System Plugin"]').click();
    await expect(page.getByRole('heading', { name: /register system plugin/i })).toBeVisible();
    await expect(page.getByText(/external plugin capabilities are backed by mcp/i)).toBeVisible();

    await page.getByPlaceholder('web_search').fill(pluginKey);
    await page.getByPlaceholder('Web Search').fill(pluginName);
    await page
      .getByRole('heading', { name: /register system plugin/i })
      .locator('xpath=ancestor::div[contains(@class,"fixed")][1]')
      .locator('textarea')
      .first()
      .fill('Playwright MCP fixture for System Plugin sync coverage.');
    await page.getByPlaceholder('https://mcp.example.com/mcp').fill(mcpServer.url);

    const createResponsePromise = page.waitForResponse(
      (response) =>
        response.request().method() === 'POST' &&
        /\/v1\/system-plugins$/.test(response.url()) &&
        response.ok()
    );
    await page.getByRole('button', { name: /register plugin/i }).click();
    const createResponse = await createResponsePromise;
    const plugin = await createResponse.json();
    pluginId = plugin.plugin_id;

    await expect(page.getByText(pluginName, { exact: true })).toBeVisible();
    await expect(page.getByText(pluginKey, { exact: true })).toBeVisible();

    const pluginRow = systemPluginRow(page, pluginName);
    const syncResponsePromise = page.waitForResponse(
      (response) =>
        response.request().method() === 'POST' &&
        response.url().includes(`/v1/system-plugins/${pluginId}/sync`) &&
        response.ok()
    );
    await pluginRow.locator('button[title="Sync Plugin Capabilities"]').click();
    await syncResponsePromise;

    await waitForSystemPluginSync(page, pluginId);
    await page.reload();
    await expect(page.getByRole('heading', { name: /swarm resources/i })).toBeVisible();
    await expect(systemPluginRow(page, pluginName).getByText(/sync completed/i)).toBeVisible();

    const tools = await expectApiOk(page, 'GET', `/v1/system-plugins/${pluginId}/tools`);
    const resources = await expectApiOk(page, 'GET', `/v1/system-plugins/${pluginId}/resources`);
    const prompts = await expectApiOk(page, 'GET', `/v1/system-plugins/${pluginId}/prompts`);
    expect(tools.map((tool) => tool.name)).toEqual(['search']);
    expect(resources.map((resource) => resource.name)).toEqual(['Search fixture docs']);
    expect(prompts.map((prompt) => prompt.name)).toEqual(['search_brief']);

    const organization = await createOrganizationViaApi(page, uniqueName('playwright-plugin-org'));
    await ensureCurrentUserOrganizationMembership(page, organization.organization_id);
    const workspaceResponse = await expectApiOk(page, 'POST', '/v1/workspaces', {
      actor: buildAdminActor(),
      organization_id: organization.organization_id,
      name: uniqueName('playwright-plugin-workspace'),
      description: 'Workspace for System Plugin attachment coverage.',
      metadata: { source: 'playwright' },
    });
    const workspaceId = workspaceResponse.workspace.workspace_id;

    const attachment = await expectApiOk(
      page,
      'PUT',
      `/v1/workspaces/${workspaceId}/system-plugins/${pluginId}`,
      {
        actor: buildAdminActor(),
        enabled: true,
        tools_enabled: true,
        resources_enabled: true,
        prompts_enabled: true,
        name_prefix: prefix,
        tool_allowlist: ['search'],
        resource_allowlist: ['docs://playwright/system-plugin'],
        prompt_allowlist: ['search_brief'],
        metadata: { source: 'playwright', allow_asset_persistence: false },
      },
    );
    expect(attachment.plugin_id).toBe(pluginId);
    expect(attachment.plugin_key).toBe(pluginKey);
    expect(attachment.name_prefix).toBe(prefix);

    const workspacePlugins = await expectApiOk(
      page,
      'GET',
      `/v1/workspaces/${workspaceId}/system-plugins`,
    );
    expect(workspacePlugins.map((item) => item.plugin_id)).toContain(pluginId);

    const workspaceTools = await expectApiOk(
      page,
      'GET',
      `/v1/workspaces/${workspaceId}/plugin-capabilities/tools`,
    );
    expect(workspaceTools).toEqual([
      expect.objectContaining({
        plugin_id: pluginId,
        plugin_key: pluginKey,
        kind: 'tool',
        exposed_name: `${prefix}search`,
        remote_name: 'search',
        enabled: true,
      }),
    ]);

    const workspaceResources = await expectApiOk(
      page,
      'GET',
      `/v1/workspaces/${workspaceId}/plugin-capabilities/resources`,
    );
    expect(workspaceResources).toEqual([
      expect.objectContaining({
        plugin_id: pluginId,
        kind: 'resource',
        exposed_name: `${prefix}Search fixture docs`,
        remote_name: 'Search fixture docs',
        uri: 'docs://playwright/system-plugin',
        enabled: true,
      }),
    ]);

    const workspacePrompts = await expectApiOk(
      page,
      'GET',
      `/v1/workspaces/${workspaceId}/plugin-capabilities/prompts`,
    );
    expect(workspacePrompts).toEqual([
      expect.objectContaining({
        plugin_id: pluginId,
        kind: 'prompt',
        exposed_name: `${prefix}search_brief`,
        remote_name: 'search_brief',
        enabled: true,
      }),
    ]);

    const deleteResponsePromise = page.waitForResponse(
      (response) =>
        response.request().method() === 'DELETE' &&
        response.url().includes(`/v1/system-plugins/${pluginId}`) &&
        response.ok()
    );
    await systemPluginRow(page, pluginName).locator('button[title="Delete System Plugin"]').click();
    await page.getByRole('button', { name: /^delete$/i }).click();
    await deleteResponsePromise;
    await page.reload();
    await expect(page.getByText(pluginName, { exact: true })).not.toBeVisible();
    pluginId = null;
  } finally {
    if (pluginId) {
      await cleanupSystemPlugin(page, pluginId);
    }
    await mcpServer.close();
  }
});

function systemPluginRow(page, pluginName) {
  return page
    .getByText(pluginName, { exact: true })
    .locator('xpath=ancestor::div[contains(@class,"p-5")][1]');
}

async function waitForSystemPluginSync(page, pluginId) {
  const deadline = Date.now() + 45_000;
  let latestStatus = null;
  let latestError = null;
  while (Date.now() < deadline) {
    const plugin = await expectApiOk(page, 'GET', `/v1/system-plugins/${pluginId}`);
    latestStatus = plugin.last_sync_status;
    latestError = plugin.last_sync_error;
    if (latestStatus === 'completed') {
      return plugin;
    }
    if (latestStatus === 'failed') {
      throw new Error(`System Plugin sync failed: ${latestError || 'unknown error'}`);
    }
    await page.waitForTimeout(1_000);
  }
  throw new Error(`Timed out waiting for System Plugin sync, latest status: ${latestStatus || 'unknown'}`);
}

async function cleanupSystemPlugin(page, pluginId) {
  await apiRequest(page, 'DELETE', `/v1/system-plugins/${pluginId}`, {
    actor: buildAdminActor(),
  }).catch(() => null);
}

async function startMcpFixture() {
  const server = createServer(async (request, response) => {
    const rawBody = await readRequestBody(request);
    const payload = rawBody ? JSON.parse(rawBody) : {};
    const result = resultForMcpMethod(payload.method);
    const body = JSON.stringify({
      jsonrpc: '2.0',
      id: payload.id,
      result,
    });
    response.writeHead(200, {
      'Content-Type': 'application/json',
      'MCP-Session-Id': 'playwright-system-plugin-session',
      'Content-Length': Buffer.byteLength(body),
    });
    response.end(body);
  });

  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  const address = server.address();
  if (!address || typeof address === 'string') {
    throw new Error('Unable to start Playwright MCP fixture.');
  }
  return {
    url: `http://127.0.0.1:${address.port}/mcp`,
    close: () => new Promise((resolve) => server.close(resolve)),
  };
}

function readRequestBody(request) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    request.on('data', (chunk) => chunks.push(chunk));
    request.on('end', () => resolve(Buffer.concat(chunks).toString('utf8')));
    request.on('error', reject);
  });
}

function resultForMcpMethod(method) {
  if (method === 'initialize') {
    return {
      protocolVersion: '2025-11-25',
      serverInfo: { name: 'playwright-system-plugin-mcp', version: '1.0.0' },
      capabilities: {
        tools: { listChanged: true },
        resources: { listChanged: true, subscribe: false },
        prompts: { listChanged: true },
      },
    };
  }
  if (method === 'tools/list') {
    return {
      tools: [
        {
          name: 'search',
          title: 'Search',
          description: 'Search fixture content.',
          inputSchema: {
            type: 'object',
            properties: { query: { type: 'string' } },
            required: ['query'],
          },
          outputSchema: {
            type: 'object',
            properties: { results: { type: 'array' } },
          },
        },
      ],
    };
  }
  if (method === 'resources/list') {
    return {
      resources: [
        {
          uri: 'docs://playwright/system-plugin',
          name: 'Search fixture docs',
          description: 'Documentation resource discovered from the Playwright fixture.',
          mimeType: 'text/markdown',
        },
      ],
    };
  }
  if (method === 'prompts/list') {
    return {
      prompts: [
        {
          name: 'search_brief',
          description: 'Brief a search task.',
          arguments: [
            {
              name: 'query',
              description: 'Search query',
              required: true,
            },
          ],
        },
      ],
    };
  }
  return {};
}
