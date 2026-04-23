import assert from 'node:assert/strict';
import test from 'node:test';

import {
  buildMemoryProviderPayload,
  buildProviderMutation,
  buildWorkspaceHarness,
  buildWorkspaceMutation,
  parseJsonInput,
} from '../../src/lib/adminForms.js';

const actor = {
  participant_id: '00000000-0000-0000-0000-000000000001',
  participant_type: 'user',
  display_name: 'Admin',
};

test('parseJsonInput returns fallback for blank values', () => {
  assert.deepEqual(parseJsonInput('', { ok: true }, 'Metadata'), { ok: true });
});

test('buildWorkspaceMutation requires an organization for workspace creation', () => {
  assert.throws(
    () => buildWorkspaceMutation({
      actor,
      organizationId: '',
      modalMode: 'create',
      formData: {
        name: 'Workspace',
        description: '',
        metadata: '{}',
        harness_summary: '',
        methodology_ontology: '',
        methodology_axiology: '',
        methodology_epistemology: '',
        methodology_principles: '[]',
        methodics: '[]',
        execution_rules: '[]',
      },
    }),
    /Select an organization before creating a workspace\./,
  );
});

test('buildWorkspaceHarness returns null when no harness fields are set', () => {
  const harness = buildWorkspaceHarness({
    harness_summary: '',
    methodology_ontology: '',
    methodology_axiology: '',
    methodology_epistemology: '',
    methodology_principles: '[]',
    methodics: '[]',
    execution_rules: '[]',
  });
  assert.equal(harness, null);
});

test('buildWorkspaceMutation serializes metadata and harness fields', () => {
  const payload = buildWorkspaceMutation({
    actor,
    organizationId: 'org-123',
    modalMode: 'create',
    formData: {
      name: 'Workspace',
      description: 'Workspace for tests.',
      metadata: '{"source":"unit"}',
      harness_summary: 'Operate carefully.',
      methodology_ontology: 'systems',
      methodology_axiology: '',
      methodology_epistemology: '',
      methodology_principles: '["verify-first"]',
      methodics: '["triage"]',
      execution_rules: '["ship-with-tests"]',
    },
  });

  assert.deepEqual(payload.metadata, { source: 'unit' });
  assert.equal(payload.harness.summary, 'Operate carefully.');
  assert.deepEqual(payload.harness.methodology.principles, ['verify-first']);
  assert.deepEqual(payload.harness.methodics, ['triage']);
  assert.deepEqual(payload.harness.execution_rules, ['ship-with-tests']);
});

test('buildWorkspaceMutation raises labeled errors for invalid JSON fields', () => {
  assert.throws(
    () => buildWorkspaceMutation({
      actor,
      organizationId: 'org-123',
      modalMode: 'create',
      formData: {
        name: 'Workspace',
        description: '',
        metadata: '{"broken"',
        harness_summary: '',
        methodology_ontology: '',
        methodology_axiology: '',
        methodology_epistemology: '',
        methodology_principles: '[]',
        methodics: '[]',
        execution_rules: '[]',
      },
    }),
    /Metadata must be valid JSON\./,
  );
});

test('buildProviderMutation builds organization-scoped llm requests', () => {
  const requestConfig = buildProviderMutation({
    actor,
    activeTab: 'llm',
    modalMode: 'create',
    scopeMode: 'organization',
    selectedOrganizationId: 'org-123',
    editingProvider: null,
    llmFormData: {
      engine_id: 'gpt-4o-mini',
      display_name: 'OpenAI GPT-4o Mini',
      description: 'Unit test provider.',
      provider: 'openai',
      endpoint_kind: 'remote',
      url: 'https://api.openai.com/v1',
      default_model: 'gpt-4o-mini',
      capabilities: 'chat, reasoning',
      locality: 'cloud',
      priority: '100',
      enabled: true,
      secret_config: '{"env":{"name":"OPENAI_API_KEY"}}',
      metadata: '{"source":"unit"}',
    },
    memoryFormData: {},
  });

  assert.equal(requestConfig.url, '/v1/organizations/org-123/llm-providers');
  assert.equal(requestConfig.method, 'POST');
  assert.deepEqual(requestConfig.data.capabilities, ['chat', 'reasoning']);
  assert.deepEqual(requestConfig.data.secret_config, { env: { name: 'OPENAI_API_KEY' } });
});

test('buildProviderMutation requires an organization for org-scoped provider creation', () => {
  assert.throws(
    () => buildProviderMutation({
      actor,
      activeTab: 'memory',
      modalMode: 'create',
      scopeMode: 'organization',
      selectedOrganizationId: '',
      editingProvider: null,
      llmFormData: {},
      memoryFormData: {},
    }),
    /Select an organization before creating an org-scoped provider\./,
  );
});

test('buildMemoryProviderPayload raises labeled config errors', () => {
  assert.throws(
    () => buildMemoryProviderPayload(actor, {
      provider_key: 'memory',
      display_name: 'Memory',
      description: 'Broken memory config.',
      provider: 'postgres',
      enabled: true,
      config: '{"broken"',
      secret_config: '{}',
      metadata: '{}',
    }),
    /Config must be valid JSON\./,
  );
});
