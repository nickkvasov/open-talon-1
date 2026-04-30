import assert from 'node:assert/strict';
import test from 'node:test';

import {
  buildLibraryIndexPayload,
  buildLibraryMutation,
  buildLibraryTextItemPayload,
  buildProjectMutation,
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

test('buildWorkspaceHarness returns default moderation policy when no harness fields are set', () => {
  const harness = buildWorkspaceHarness({
    harness_summary: '',
    methodology_ontology: '',
    methodology_axiology: '',
    methodology_epistemology: '',
    methodology_principles: '[]',
    methodics: '[]',
    execution_rules: '[]',
    moderation_enabled: true,
    moderation_level: 'balanced',
    moderation_topic: '',
    moderation_allowed_adjacent_topics: '[]',
    moderation_blocked_topics: '[]',
    moderation_explain_blocked_messages: true,
  });
  assert.equal(harness.summary, null);
  assert.equal(harness.methodology, null);
  assert.deepEqual(harness.methodics, []);
  assert.deepEqual(harness.execution_rules, []);
  assert.deepEqual(harness.moderation_policy, {
    enabled: true,
    level: 'balanced',
    topic: null,
    allowed_adjacent_topics: [],
    blocked_topics: [],
    explain_blocked_messages: true,
  });
});

test('buildWorkspaceHarness serializes moderation policy controls', () => {
  const harness = buildWorkspaceHarness({
    harness_summary: '',
    methodology_ontology: '',
    methodology_axiology: '',
    methodology_epistemology: '',
    methodology_principles: '[]',
    methodics: '[]',
    execution_rules: '[]',
    moderation_enabled: false,
    moderation_level: 'strict',
    moderation_topic: 'Runtime architecture',
    moderation_allowed_adjacent_topics: '["tests","docs"]',
    moderation_blocked_topics: '["hiring"]',
    moderation_explain_blocked_messages: false,
  });

  assert.deepEqual(harness.moderation_policy, {
    enabled: false,
    level: 'strict',
    topic: 'Runtime architecture',
    allowed_adjacent_topics: ['tests', 'docs'],
    blocked_topics: ['hiring'],
    explain_blocked_messages: false,
  });
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

test('buildProjectMutation serializes creator owner editor viewer access subjects', () => {
  const payload = buildProjectMutation({
    actor,
    formData: {
      slug: 'project-one',
      name: 'Project One',
      description: '',
      owner_user_id: '11111111-1111-1111-1111-111111111111,22222222-2222-2222-2222-222222222222',
      owner_system_agent_id: '',
      editor_user_ids: '33333333-3333-3333-3333-333333333333',
      editor_system_agent_ids: '',
      viewer_user_ids: '',
      viewer_system_agent_ids: '44444444-4444-4444-4444-444444444444',
      metadata: '{"source":"unit"}',
    },
  });

  assert.equal(payload.owner.user_id, '11111111-1111-1111-1111-111111111111');
  assert.deepEqual(payload.owners, [
    { user_id: '11111111-1111-1111-1111-111111111111' },
    { user_id: '22222222-2222-2222-2222-222222222222' },
  ]);
  assert.deepEqual(payload.editors, [
    { user_id: '33333333-3333-3333-3333-333333333333' },
  ]);
  assert.deepEqual(payload.viewers, [
    { system_agent_id: '44444444-4444-4444-4444-444444444444' },
  ]);
  assert.deepEqual(payload.metadata, { source: 'unit' });
});

test('buildLibraryMutation trims optional slug and parses metadata', () => {
  const payload = buildLibraryMutation(actor, {
    slug: ' references ',
    name: 'References',
    description: ' Shared reference store ',
    metadata: '{"owner":"qa"}',
  });

  assert.equal(payload.slug, 'references');
  assert.equal(payload.description, 'Shared reference store');
  assert.deepEqual(payload.metadata, { owner: 'qa' });
});

test('buildLibraryTextItemPayload preserves content and defaults content type', () => {
  const payload = buildLibraryTextItemPayload(actor, {
    title: 'Architecture Note',
    content: '# Note',
    item_kind: 'text',
    logical_name: '',
    source_uri: ' https://example.test/note ',
    content_type: '',
    metadata: '{}',
  });

  assert.equal(payload.content, '# Note');
  assert.equal(payload.content_type, 'text/markdown');
  assert.equal(payload.logical_name, null);
  assert.equal(payload.source_uri, 'https://example.test/note');
});

test('buildLibraryIndexPayload keeps indexing explicit', () => {
  const payload = buildLibraryIndexPayload(actor, ['item-1', 'item-2']);

  assert.deepEqual(payload.item_ids, ['item-1', 'item-2']);
  assert.deepEqual(payload.metadata, {});
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
