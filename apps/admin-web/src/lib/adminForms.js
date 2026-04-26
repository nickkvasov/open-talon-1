export function parseJsonInput(raw, fallback, label) {
  if (typeof raw !== 'string' || !raw.trim()) {
    return fallback;
  }
  try {
    return JSON.parse(raw);
  } catch {
    throw new Error(`${label} must be valid JSON.`);
  }
}

export function buildWorkspaceHarness(formData) {
  const principles = parseJsonInput(
    formData.methodology_principles,
    [],
    'Methodology principles',
  );
  const methodics = parseJsonInput(formData.methodics, [], 'Methodics');
  const executionRules = parseJsonInput(
    formData.execution_rules,
    [],
    'Execution rules',
  );
  const allowedAdjacentTopics = parseJsonInput(
    formData.moderation_allowed_adjacent_topics,
    [],
    'Allowed adjacent topics',
  );
  const blockedTopics = parseJsonInput(
    formData.moderation_blocked_topics,
    [],
    'Blocked topics',
  );
  const methodology = {
    ontology: formData.methodology_ontology || null,
    axiology: formData.methodology_axiology || null,
    epistemology: formData.methodology_epistemology || null,
    principles,
  };
  const hasMethodology = Boolean(
    methodology.ontology
    || methodology.axiology
    || methodology.epistemology
    || methodology.principles.length,
  );
  return {
    version: 1,
    summary: formData.harness_summary.trim() || null,
    methodology: hasMethodology ? methodology : null,
    methodics,
    execution_rules: executionRules,
    moderation_policy: {
      enabled: formData.moderation_enabled !== false,
      level: formData.moderation_level || 'balanced',
      topic: (formData.moderation_topic || '').trim() || null,
      allowed_adjacent_topics: allowedAdjacentTopics,
      blocked_topics: blockedTopics,
      explain_blocked_messages: formData.moderation_explain_blocked_messages !== false,
    },
    metadata: {},
  };
}

export function buildWorkspaceMutation({
  actor,
  organizationId,
  projectId,
  formData,
  modalMode,
}) {
  if (modalMode === 'create' && !organizationId) {
    throw new Error('Select an organization before creating a workspace.');
  }
  return {
    actor,
    organization_id: organizationId || null,
    project_id: modalMode === 'create' ? (projectId || null) : undefined,
    name: formData.name,
    description: formData.description,
    metadata: parseJsonInput(formData.metadata, {}, 'Metadata'),
    harness: buildWorkspaceHarness(formData),
  };
}

export function buildProjectMutation({
  actor,
  formData,
}) {
  const ownerSubjects = [
    ...subjectRefsFromCsv(formData.owner_user_id, 'user_id'),
    ...subjectRefsFromCsv(formData.owner_system_agent_id, 'system_agent_id'),
  ];
  const editors = [
    ...subjectRefsFromCsv(formData.editor_user_ids, 'user_id'),
    ...subjectRefsFromCsv(formData.editor_system_agent_ids, 'system_agent_id'),
  ];
  const viewers = [
    ...subjectRefsFromCsv(formData.viewer_user_ids, 'user_id'),
    ...subjectRefsFromCsv(formData.viewer_system_agent_ids, 'system_agent_id'),
  ];
  const payload = {
    actor,
    slug: formData.slug,
    name: formData.name,
    description: formData.description,
    metadata: parseJsonInput(formData.metadata, {}, 'Metadata'),
  };
  if (ownerSubjects.length) {
    payload.owner = ownerSubjects[0];
    payload.owners = ownerSubjects;
  }
  if (editors.length) {
    payload.editors = editors;
  }
  if (viewers.length) {
    payload.viewers = viewers;
  }
  return payload;
}

function subjectRefsFromCsv(raw, key) {
  if (typeof raw !== 'string' || !raw.trim()) {
    return [];
  }
  return raw
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean)
    .map((value) => ({ [key]: value }));
}

function parseIntegerInput(raw, label) {
  const value = Number.parseInt(raw, 10);
  if (Number.isNaN(value)) {
    throw new Error(`${label} must be a whole number.`);
  }
  return value;
}

export function buildLlmProviderPayload(actor, formData) {
  return {
    actor,
    engine_id: formData.engine_id,
    display_name: formData.display_name,
    description: formData.description,
    provider: formData.provider,
    endpoint_kind: formData.endpoint_kind,
    url: formData.url || null,
    default_model: formData.default_model || null,
    capabilities: formData.capabilities.split(',').map((item) => item.trim()).filter(Boolean),
    locality: formData.locality,
    priority: parseIntegerInput(formData.priority, 'Priority'),
    enabled: formData.enabled,
    secret_config: parseJsonInput(formData.secret_config, {}, 'Secret config'),
    metadata: parseJsonInput(formData.metadata, {}, 'Metadata'),
  };
}

export function buildMemoryProviderPayload(actor, formData) {
  return {
    actor,
    provider_key: formData.provider_key,
    display_name: formData.display_name,
    description: formData.description,
    provider: formData.provider,
    enabled: formData.enabled,
    config: parseJsonInput(formData.config, {}, 'Config'),
    secret_config: parseJsonInput(formData.secret_config, {}, 'Secret config'),
    metadata: parseJsonInput(formData.metadata, {}, 'Metadata'),
  };
}

export function buildProviderMutation({
  actor,
  activeTab,
  modalMode,
  scopeMode,
  selectedOrganizationId,
  editingProvider,
  llmFormData,
  memoryFormData,
}) {
  if (modalMode === 'create' && scopeMode === 'organization' && !selectedOrganizationId) {
    throw new Error('Select an organization before creating an org-scoped provider.');
  }
  if (activeTab === 'llm') {
    return {
      url: modalMode === 'edit'
        ? `/v1/llm-providers/${editingProvider.provider_id}`
        : scopeMode === 'organization'
          ? `/v1/organizations/${selectedOrganizationId}/llm-providers`
          : '/v1/llm-providers',
      method: modalMode === 'edit' ? 'PATCH' : 'POST',
      data: buildLlmProviderPayload(actor, llmFormData),
    };
  }
  return {
    url: modalMode === 'edit'
      ? `/v1/memory-providers/${editingProvider.provider_id}`
      : scopeMode === 'organization'
        ? `/v1/organizations/${selectedOrganizationId}/memory-providers`
        : '/v1/memory-providers',
    method: modalMode === 'edit' ? 'PATCH' : 'POST',
    data: buildMemoryProviderPayload(actor, memoryFormData),
  };
}
