import assert from 'node:assert/strict';
import test from 'node:test';

import {
  blankResearchForm,
  buildDossierLifecyclePayload,
  buildDossierSourceUpdatePayload,
  buildInteractionAnswerPayload,
  buildMethodologyApplyPayload,
  buildMethodologyArchivePayload,
  buildMethodologyCreatePayload,
  buildMethodologyDraftPayload,
  buildMethodologyResearchRequestPayload,
  buildMethodologyReviewPayload,
  buildMethodologyVersionPayload,
  draftFormFromVersion,
  fullMethodologyKnowledgeComponents,
  isVersionEditable,
  knowledgeCoverageFromState,
  parseTasks,
  requiresNewVersion,
} from '../../src/features/methodologies/forms.js';

const actor = {
  participant_id: '00000000-0000-0000-0000-000000000001',
  participant_type: 'user',
  display_name: 'Admin',
};

test('parseTasks accepts newline input and removes blanks', () => {
  assert.deepEqual(parseTasks('Discover evidence\n\nSynthesize methodics\n '), [
    'Discover evidence',
    'Synthesize methodics',
  ]);
});

test('buildMethodologyCreatePayload serializes source policy, tasks, libraries, and metadata', () => {
  const payload = buildMethodologyCreatePayload(actor, {
    title: ' Evidence-backed onboarding ',
    topic: ' Onboarding methodology ',
    target_goal: ' Reusable workspace harness ',
    tasks: 'Discover\nSynthesize',
    source_policy: 'hybrid',
    library_ids: ['library-1'],
    metadata: '{"source":"unit"}',
  });

  assert.equal(payload.title, 'Evidence-backed onboarding');
  assert.equal(payload.topic, 'Onboarding methodology');
  assert.equal(payload.target_goal, 'Reusable workspace harness');
  assert.deepEqual(payload.tasks, ['Discover', 'Synthesize']);
  assert.deepEqual(payload.library_ids, ['library-1']);
  assert.deepEqual(payload.metadata, { source: 'unit' });
});

test('buildMethodologyDraftPayload builds a WorkspaceHarness-compatible draft', () => {
  const payload = buildMethodologyDraftPayload(actor, {
    cited_output: '# Draft\n\nClaim [S1]',
    harness_summary: 'Evidence-backed onboarding.',
    methodology_ontology: 'People and artifacts.',
    methodology_axiology: '',
    methodology_epistemology: '',
    methodology_principles: '["cite evidence"]',
    methodics: '[{"name":"Onboard","goal":"Start well","steps":[],"success_criteria":[]}]',
    execution_rules: '[{"name":"Citations","instruction":"Cite source claims."}]',
    moderation_enabled: true,
    moderation_level: 'balanced',
    moderation_topic: '',
    moderation_allowed_adjacent_topics: '[]',
    moderation_blocked_topics: '[]',
    moderation_explain_blocked_messages: true,
    metadata: '{"edited":true}',
  });

  assert.equal(payload.cited_output, '# Draft\n\nClaim [S1]');
  assert.equal(payload.harness_draft.summary, 'Evidence-backed onboarding.');
  assert.equal(payload.harness_draft.methodology.ontology, 'People and artifacts.');
  assert.deepEqual(payload.harness_draft.methodology.principles, ['cite evidence']);
  assert.equal(payload.harness_draft.methodics[0].name, 'Onboard');
  assert.deepEqual(payload.metadata, { edited: true });
});

test('buildMethodologyVersionPayload includes base version and revision reason', () => {
  const payload = buildMethodologyVersionPayload(actor, 'version-1', {
    cited_output: '# Revised',
    harness_summary: 'Revised methodology.',
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
    metadata: '{}',
    reason: 'Human edit',
  });

  assert.equal(payload.base_version_id, 'version-1');
  assert.equal(payload.reason, 'Human edit');
});

test('buildMethodologyResearchRequestPayload keeps Researcher work explicit', () => {
  const payload = buildMethodologyResearchRequestPayload(actor, {
    ...blankResearchForm,
    instructions: ' Search B2C demand signals and fill coverage ',
    max_search_turns: '7',
    required_components: ['research_plan', 'synthesis'],
    require_admin_ready_approval: true,
    metadata: '{"priority":"high"}',
  });

  assert.equal(payload.instructions, 'Search B2C demand signals and fill coverage');
  assert.equal(payload.max_search_turns, 7);
  assert.deepEqual(payload.required_components, ['research_plan', 'synthesis']);
  assert.equal(payload.require_admin_ready_approval, true);
  assert.deepEqual(payload.metadata, { priority: 'high' });
});

test('review, apply, archive payload builders keep lifecycle actions explicit', () => {
  assert.deepEqual(buildMethodologyReviewPayload(actor, ' Accept '), {
    actor,
    reason: 'Accept',
    metadata: {},
  });
  assert.deepEqual(buildMethodologyApplyPayload({
    actor,
    workspaceId: 'workspace-1',
    versionId: 'version-2',
    preserveModerationPolicy: false,
  }), {
    actor,
    workspace_id: 'workspace-1',
    version_id: 'version-2',
    preserve_moderation_policy: false,
    metadata: {},
  });
  assert.deepEqual(buildMethodologyArchivePayload(actor), {
    actor,
    metadata: {},
  });
});

test('dossier console payload builders serialize curation and answers', () => {
  assert.deepEqual(buildDossierLifecyclePayload({
    actor,
    targetStatus: 'ready',
    summary: ' Ready ',
    reason: ' Admin approval ',
    metadata: { approved: true },
  }), {
    actor,
    target_status: 'ready',
    summary: 'Ready',
    contradictions: [],
    gaps: [],
    reason: 'Admin approval',
    metadata: { approved: true },
  });

  assert.deepEqual(buildDossierSourceUpdatePayload(
    actor,
    { metadata: { search_turn: 1 } },
    'included',
  ), {
    actor,
    status: 'included',
    metadata: { search_turn: 1, admin_curated: true },
  });

  const answerPayload = buildInteractionAnswerPayload(actor, {
    request: { request_id: 'request-1' },
    questions: [{ question_id: 'question-1' }, { question_id: 'question-2' }],
  }, ' Clarified audience ');
  assert.equal(answerPayload.content, 'Clarified audience');
  assert.deepEqual(answerPayload.question_ids, ['question-1', 'question-2']);
  assert.equal(answerPayload.metadata.answered_from, 'methodology_research_console');
});

test('knowledgeCoverageFromState keeps required methodology components ordered', () => {
  const coverage = knowledgeCoverageFromState({
    knowledge_components: [
      { component: 'synthesis', present: true, item_count: 1 },
      { component: 'research_plan', present: false, item_count: 0 },
      { component: 'extra_component', present: true, item_count: 1 },
    ],
  });

  assert.equal(coverage[0].component, 'research_plan');
  assert.equal(coverage[1].component, 'synthesis');
  assert.equal(coverage[coverage.length - 1].component, 'extra_component');
  assert.equal(fullMethodologyKnowledgeComponents.includes('libraries_and_dossiers'), true);
});

test('draftFormFromVersion hydrates harness fields and lifecycle helpers classify versions', () => {
  const form = draftFormFromVersion({
    status: 'approved',
    cited_output: '# Approved',
    harness_draft: {
      summary: 'Approved methodology.',
      methodology: { principles: ['verify'] },
      methodics: [],
      execution_rules: [],
      moderation_policy: { enabled: false, level: 'strict' },
      metadata: {},
    },
    metadata: { base: true },
  });

  assert.equal(form.cited_output, '# Approved');
  assert.equal(form.harness_summary, 'Approved methodology.');
  assert.equal(form.moderation_enabled, false);
  assert.equal(requiresNewVersion({ status: 'approved' }, { status: 'active' }), true);
  assert.equal(isVersionEditable({ status: 'pending_review' }, { status: 'draft' }), true);
  assert.equal(isVersionEditable({ status: 'pending_review' }, { status: 'archived' }), false);
});
