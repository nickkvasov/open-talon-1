import { buildWorkspaceHarness, parseJsonInput } from '../../lib/adminForms.js';

const editableStatuses = new Set([
  'researching',
  'ready_for_draft',
  'drafted',
  'pending_review',
]);

export const fullMethodologyKnowledgeComponents = [
  'research_plan',
  'source_bibliography',
  'methodology_basis',
  'methodology_principles',
  'methodics_inventory',
  'participants_and_roles',
  'tools_and_methods',
  'information_assets',
  'libraries_and_dossiers',
  'quality_evaluation',
  'contradictions',
  'gaps',
  'synthesis',
];

export const blankCreateForm = {
  title: '',
  topic: '',
  target_goal: '',
  tasks: '',
  source_policy: 'hybrid',
  library_ids: [],
  metadata: '{}',
};

export const blankResearchForm = {
  instructions: '',
  max_search_turns: 5,
  required_components: [...fullMethodologyKnowledgeComponents],
  require_admin_ready_approval: true,
  metadata: '{}',
};

export function parseTasks(raw) {
  if (Array.isArray(raw)) {
    return raw.map((item) => String(item).trim()).filter(Boolean);
  }
  if (typeof raw !== 'string' || !raw.trim()) {
    return [];
  }
  return raw
    .split(/\r?\n/)
    .map((item) => item.trim())
    .filter(Boolean);
}

export function buildMethodologyCreatePayload(actor, formData) {
  return {
    actor,
    title: formData.title.trim(),
    topic: formData.topic.trim(),
    target_goal: formData.target_goal.trim() || null,
    tasks: parseTasks(formData.tasks),
    source_policy: formData.source_policy || 'hybrid',
    library_ids: formData.library_ids || [],
    metadata: parseJsonInput(formData.metadata, {}, 'Metadata'),
  };
}

export function buildMethodologyResearchRequestPayload(actor, formData) {
  const maxSearchTurns = Number.parseInt(formData.max_search_turns, 10);
  return {
    actor,
    instructions: formData.instructions.trim(),
    max_search_turns: Number.isFinite(maxSearchTurns) ? maxSearchTurns : 5,
    required_components: formData.required_components?.length
      ? formData.required_components
      : [...fullMethodologyKnowledgeComponents],
    require_admin_ready_approval: formData.require_admin_ready_approval !== false,
    metadata: parseJsonInput(formData.metadata, {}, 'Research metadata'),
  };
}

export function buildMethodologyDraftPayload(actor, formData) {
  return {
    actor,
    cited_output: formData.cited_output,
    harness_draft: buildWorkspaceHarness(formData),
    metadata: parseJsonInput(formData.metadata, {}, 'Metadata'),
  };
}

export function buildMethodologyVersionPayload(actor, baseVersionId, formData) {
  return {
    ...buildMethodologyDraftPayload(actor, formData),
    base_version_id: baseVersionId,
    reason: formData.reason.trim() || null,
  };
}

export function buildMethodologyReviewPayload(actor, reason) {
  return {
    actor,
    reason: reason.trim() || null,
    metadata: {},
  };
}

export function buildMethodologyApplyPayload({
  actor,
  workspaceId,
  versionId,
  preserveModerationPolicy,
}) {
  return {
    actor,
    workspace_id: workspaceId,
    version_id: versionId || null,
    preserve_moderation_policy: preserveModerationPolicy !== false,
    metadata: {},
  };
}

export function buildMethodologyArchivePayload(actor) {
  return {
    actor,
    metadata: {},
  };
}

export function buildDossierLifecyclePayload({
  actor,
  targetStatus,
  summary = '',
  contradictions = [],
  gaps = [],
  reason = '',
  metadata = {},
}) {
  return {
    actor,
    target_status: targetStatus,
    summary: summary?.trim() || null,
    contradictions,
    gaps,
    reason: reason?.trim() || null,
    metadata,
  };
}

export function buildDossierSourceUpdatePayload(actor, source, nextStatus) {
  return {
    actor,
    status: nextStatus,
    metadata: {
      ...(source?.metadata || {}),
      admin_curated: true,
    },
  };
}

export function buildInteractionAnswerPayload(actor, requestDetail, content) {
  return {
    actor,
    content: content.trim(),
    question_ids: (requestDetail?.questions || []).map((question) => question.question_id),
    metadata: {
      answered_from: 'methodology_research_console',
      interaction_request_id: requestDetail?.request?.request_id,
    },
  };
}

export function knowledgeCoverageFromState(state) {
  const components = state?.knowledge_components || [];
  const order = new Map(
    fullMethodologyKnowledgeComponents.map((component, index) => [component, index]),
  );
  return [...components].sort((left, right) => {
    const leftOrder = order.has(left.component) ? order.get(left.component) : 1000;
    const rightOrder = order.has(right.component) ? order.get(right.component) : 1000;
    if (leftOrder !== rightOrder) return leftOrder - rightOrder;
    return left.component.localeCompare(right.component);
  });
}

export function isVersionEditable(version, blueprint) {
  return Boolean(
    version
    && blueprint?.status !== 'archived'
    && editableStatuses.has(version.status),
  );
}

export function requiresNewVersion(version, blueprint) {
  return Boolean(
    version
    && blueprint?.status !== 'archived'
    && version.status === 'approved',
  );
}

export function draftFormFromVersion(version = null) {
  const harness = version?.harness_draft || {};
  const methodology = harness.methodology || {};
  const moderation = harness.moderation_policy || {};
  return {
    cited_output: version?.cited_output || '',
    harness_summary: harness.summary || '',
    methodology_ontology: methodology.ontology || '',
    methodology_axiology: methodology.axiology || '',
    methodology_epistemology: methodology.epistemology || '',
    methodology_principles: JSON.stringify(methodology.principles || [], null, 2),
    methodics: JSON.stringify(harness.methodics || [], null, 2),
    execution_rules: JSON.stringify(harness.execution_rules || [], null, 2),
    moderation_enabled: moderation.enabled ?? true,
    moderation_level: moderation.level || 'balanced',
    moderation_topic: moderation.topic || '',
    moderation_allowed_adjacent_topics: JSON.stringify(
      moderation.allowed_adjacent_topics || [],
      null,
      2,
    ),
    moderation_blocked_topics: JSON.stringify(moderation.blocked_topics || [], null, 2),
    moderation_explain_blocked_messages: moderation.explain_blocked_messages ?? true,
    metadata: JSON.stringify(version?.metadata || {}, null, 2),
    reason: '',
  };
}
