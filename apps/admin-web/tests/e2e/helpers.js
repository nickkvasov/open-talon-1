import { expect } from '@playwright/test';

const defaultUsername = process.env.ADMIN_WEB_E2E_USERNAME || 'admin';
const defaultPassword = process.env.ADMIN_WEB_E2E_PASSWORD || 'admin123';
const gatewayUrl = process.env.ADMIN_WEB_E2E_GATEWAY_URL || 'http://127.0.0.1:8000';
const seededToolGenerationAgentId = '44444444-4444-4444-4444-444444444444';

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

export async function signInIfNeeded(page, credentials = {}) {
  const username = credentials.username || defaultUsername;
  const password = credentials.password || defaultPassword;
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
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

export function buildAdminActor() {
  return {
    participant_id: '00000000-0000-0000-0000-000000000001',
    participant_type: 'user',
    display_name: 'Admin',
  };
}

export async function getAccessToken(page) {
  return await page.evaluate(() => {
    for (const store of [window.localStorage, window.sessionStorage]) {
      for (let index = 0; index < store.length; index += 1) {
        const key = store.key(index);
        if (!key || !key.startsWith('oidc.user:')) {
          continue;
        }
        const raw = store.getItem(key);
        if (!raw) {
          continue;
        }
        try {
          const parsed = JSON.parse(raw);
          if (parsed?.access_token) {
            return parsed.access_token;
          }
        } catch {
          // Ignore unrelated storage entries.
        }
      }
    }
    return null;
  });
}

export async function apiRequest(page, method, path, body) {
  const token = await getAccessToken(page);
  const response = await page.request.fetch(`${gatewayUrl}${path}`, {
    method,
    headers: {
      ...(body === undefined ? {} : { 'Content-Type': 'application/json' }),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    data: body,
  });
  const contentType = response.headers()['content-type'] || '';
  const payload = contentType.includes('application/json')
    ? await response.json()
    : await response.text();
  return {
    ok: response.ok(),
    status: response.status(),
    data: payload,
  };
}

export async function expectApiOk(page, method, path, body) {
  const response = await apiRequest(page, method, path, body);
  expect(response.ok, `${method} ${path} failed with ${response.status}`).toBe(true);
  return response.data;
}

export async function getCurrentUser(page) {
  return await expectApiOk(page, 'GET', '/v1/me');
}

export async function ensureCurrentUserOrganizationMembership(page, organizationId, role = 'owner') {
  const currentUser = await getCurrentUser(page);
  const response = await apiRequest(page, 'POST', `/v1/organizations/${organizationId}/members`, {
    actor: buildAdminActor(),
    user_id: currentUser.user_id,
    role,
    metadata: { source: 'playwright' },
  });
  if (response.status === 200 || response.status === 409) {
    return currentUser;
  }
  expect(response.ok, `failed to add current user to organization ${organizationId}`).toBe(true);
  return currentUser;
}

export async function createOrganizationViaApi(page, name = uniqueName('playwright-org')) {
  const slug = name.toLowerCase().replace(/[^a-z0-9]+/g, '-');
  const organization = await expectApiOk(page, 'POST', '/v1/organizations', {
    actor: buildAdminActor(),
    slug,
    name,
    description: 'Organization created by Playwright.',
    metadata: { source: 'playwright' },
  });
  return organization;
}

export async function seedPendingApprovalToolGenerationRequest(
  page,
  {
    organizationId = null,
    requestedScope = 'global',
    toolName = uniqueName('playwright-generated-tool'),
    useSeededToolGenerationAgent = false,
  } = {},
) {
  const resolvedOrganizationId = organizationId || (
    await createOrganizationViaApi(page, uniqueName('playwright-tool-org'))
  ).organization_id;
  await ensureCurrentUserOrganizationMembership(page, resolvedOrganizationId);
  const workspace = await expectApiOk(page, 'POST', '/v1/workspaces', {
    actor: buildAdminActor(),
    organization_id: resolvedOrganizationId,
    name: uniqueName('playwright-tooling-workspace'),
    description: 'Workspace created by Playwright to seed tool-generation review.',
    metadata: { source: 'playwright' },
  });
  const workspaceId = workspace.workspace.workspace_id;

  const thread = await expectApiOk(page, 'POST', `/v1/workspaces/${workspaceId}/threads`, {
    actor: buildAdminActor(),
    title: uniqueName('playwright-tooling-thread'),
  });
  const threadId = thread.thread.thread_id;

  let agentId = seededToolGenerationAgentId;
  if (!useSeededToolGenerationAgent) {
    const agent = await expectApiOk(page, 'POST', '/v1/agents', {
      actor: buildAdminActor(),
      display_name: uniqueName('Playwright Tinker'),
      description: 'Builds tools on demand and submits them for approval.',
      role: 'tool_generation_agent',
      capabilities: ['tool_generation'],
      endpoint: { kind: 'local', model: 'gemma4:latest' },
      system_prompt: 'Build tools carefully.',
      definition: { tool_generation_agent: true },
      metadata: { tool_generation_agent: true },
    });
    agentId = agent.agent_id;
  }

  await expectApiOk(page, 'POST', `/v1/workspaces/${workspaceId}/agents`, {
    actor: buildAdminActor(),
    agent_id: agentId,
  });

  await expectApiOk(page, 'POST', `/v1/threads/${threadId}/messages`, {
    actor: buildAdminActor(),
    content: `Tinker, please create ${toolName}.`,
    visibility: 'workspace',
    target_system_agent_id: agentId,
    ...(requestedScope === 'organization' ? { target_tool_scope: 'organization' } : {}),
    metadata: { target_tool_name: toolName },
  });

  const requests = await expectApiOk(page, 'GET', `/v1/threads/${threadId}/tool-generation/requests`);
  const requestId = requests[0].request.request_id;

  const revision = await expectApiOk(
    page,
    'POST',
    `/v1/tool-generation/requests/${requestId}/revisions`,
    {
      actor: buildAdminActor(),
      status: 'pending_approval',
      manifest: {
        name: toolName,
        description: `Generated tool for ${toolName}.`,
        parameter_contract: {
          parameters: [
            {
              name: 'value',
              type: 'integer',
              description: 'Integer input.',
              required: true,
            },
          ],
        },
        input_schema: {
          type: 'object',
          properties: {
            value: { type: 'integer' },
          },
          required: ['value'],
          additionalProperties: false,
        },
        execution: {
          backend_kind: 'docker',
          handler_ref: `registry.example/${toolName}:latest`,
          trust_level: 'sandboxed',
        },
        build_context_path: `/tmp/${toolName}`,
        smoke_test: {
          command: ['python', '/app/run.py'],
          input_payload: { value: 1 },
          expected_output_schema: {
            type: 'object',
            properties: {
              value: { type: 'integer' },
            },
            required: ['value'],
          },
        },
        trust_rationale: 'Pure computation without network or workspace access.',
        dependency_summary: ['python'],
        network_access: 'none',
        workspace_access: 'none',
      },
      validation_report: {
        summary: `Validation completed for ${toolName}.`,
      },
      image_ref: `registry.example/${toolName}:latest`,
      image_digest: `sha256:${'a'.repeat(64)}`,
    },
  );

  return {
    workspaceId,
    threadId,
    agentId,
    requestId,
    revisionId: revision.revisions[0].revision_id,
    toolName,
  };
}
