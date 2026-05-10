import { test, expect } from '@playwright/test';
import {
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

const fullMethodologyKnowledgeComponents = [
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

test.beforeEach(async ({ page }) => {
  attachBrowserLogging(page);
  page.on('dialog', (dialog) => dialog.accept());
  await signInIfNeeded(page);
});

test('methodologies can create and edit a B2C market research methodology', async ({ page }) => {
  const organization = await createOrganizationViaApi(
    page,
    uniqueName('playwright-b2c-methodology-org'),
  );
  await ensureCurrentUserOrganizationMembership(page, organization.organization_id);
  const workspace = await expectApiOk(page, 'POST', '/v1/workspaces', {
    actor: buildAdminActor(),
    organization_id: organization.organization_id,
    name: uniqueName('playwright-b2c-methodology-workspace'),
    description: 'Workspace created by Playwright for B2C methodology apply coverage.',
    metadata: { source: 'playwright', scenario: 'b2c_market_research' },
  });
  const workspaceId = workspace.workspace.workspace_id;
  const title = uniqueName('playwright-b2c-market-research-methodology');

  await openAdminPage(page, /^methodologies$/i, /^methodologies$/i);
  await page.locator('select').first().selectOption({ label: organization.name });

  const createForm = page.locator('form').filter({
    has: page.getByText(/request methodology/i),
  });
  await createForm.getByPlaceholder(/evidence-backed onboarding/i).fill(title);
  await createForm.getByPlaceholder(/what should researcher investigate/i).fill(
    'Create a B2C market research methodology for evaluating subscription wellness app demand.',
  );
  await createForm.getByPlaceholder(/reusable workspace methodology/i).fill(
    'Reusable B2C consumer research harness for launch readiness decisions.',
  );
  await createForm.getByPlaceholder(/discover source evidence/i).fill(
    [
      'Run internet search turn 1 for broad B2C market research methodology',
      'Run internet search turn 2 for purchase-intent and willingness-to-pay methodics',
      'Collect cited methodology sources into a dossier',
      'Draft B2C survey, diary-study, and interview methodics with participants and assets',
    ].join('\n'),
  );

  const createResponse = page.waitForResponse(
    (response) =>
      response.request().method() === 'POST' &&
      /\/methodology\/blueprints$/.test(response.url()) &&
      response.ok(),
  );
  await createForm.getByRole('button', { name: /create blueprint/i }).click();
  const createdDetail = await (await createResponse).json();
  const blueprintId = createdDetail.blueprint.blueprint_id;
  const dossierId = createdDetail.dossier.dossier_id;
  const dossierThreadId = createdDetail.dossier.thread_id;
  const versionId = createdDetail.versions[0].version_id;

  const researchSection = page
    .getByText(/research console/i)
    .locator('xpath=ancestor::section[1]');
  await researchSection.getByPlaceholder(/ask researcher/i).fill(
    [
      'Run two internet search turns for B2C subscription wellness app market research.',
      'Persist source bibliography and full methodology knowledge components.',
      'Ask for clarification if the target respondent profile is ambiguous.',
    ].join('\n'),
  );
  const researchRequestResponse = page.waitForResponse(
    (response) =>
      response.request().method() === 'POST' &&
      /\/research-requests$/.test(response.url()) &&
      response.ok(),
  );
  await researchSection.getByRole('button', { name: /request research/i }).click();
  await researchRequestResponse;

  await expectApiOk(page, 'POST', `/v1/threads/${dossierThreadId}/requests`, {
    actor: buildAdminActor(),
    requests: [
      {
        title: 'Confirm B2C respondent profile',
        summary: 'Researcher needs respondent scope before final readiness.',
        questions: [
          {
            prompt: 'Should the B2C research prioritize US wellness subscribers?',
            kind: 'clarification',
            expected_format: 'short text',
          },
        ],
        completion_rule: { mode: 'minimum_answers', minimum_answers: 1 },
        metadata: {
          dossier_id: dossierId,
          source: 'playwright',
          desired_responder_types: ['user'],
        },
      },
    ],
  });

  const sourceOne = await expectApiOk(
    page,
    'POST',
    `/v1/organizations/${organization.organization_id}/dossiers/${dossierId}/sources`,
    {
      actor: buildAdminActor(),
      source_kind: 'webpage',
      status: 'included',
      title: 'B2C market research segmentation source',
      source_uri: 'https://example.test/b2c-segmentation-methodology',
      citation_id: 'S1',
      quality_notes: 'Representative source for search turn 1.',
      fetch_metadata: {
        internet_search: true,
        search_turn: 1,
        search_query: 'B2C market research methodology consumer segmentation purchase intent',
      },
      metadata: { knowledge_component: 'source_bibliography' },
    },
  );
  await expectApiOk(
    page,
    'POST',
    `/v1/organizations/${organization.organization_id}/dossiers/${dossierId}/sources`,
    {
      actor: buildAdminActor(),
      source_kind: 'webpage',
      status: 'included',
      title: 'B2C willingness-to-pay methodics source',
      source_uri: 'https://example.test/b2c-wtp-diary-study-methodology',
      citation_id: 'S2',
      quality_notes: 'Representative source for search turn 2.',
      fetch_metadata: {
        internet_search: true,
        search_turn: 2,
        search_query: 'B2C willingness to pay survey diary study purchase intent methodology',
      },
    },
  );
  for (const component of fullMethodologyKnowledgeComponents) {
    await expectApiOk(
      page,
      'POST',
      `/v1/organizations/${organization.organization_id}/dossiers/${dossierId}/notes`,
      {
        actor: buildAdminActor(),
        note_kind: component === 'gaps'
          ? 'gap'
          : component === 'contradictions'
            ? 'contradiction'
            : component === 'synthesis'
              ? 'synthesis'
              : component === 'source_bibliography'
                ? 'source'
                : 'other',
        status: 'active',
        slug: `playwright-${component}`,
        title: `B2C ${component.replaceAll('_', ' ')}`,
        summary: `B2C market research coverage for ${component}.`,
        body: (
          `Knowledge component ${component} includes required steps, participants, `
          + 'tools, information assets, supporting libraries, and dossier references.'
        ),
        source_id: component === 'source_bibliography' ? sourceOne.source_id : null,
        citation_ids: component === 'source_bibliography' ? ['S1'] : [],
        metadata: {
          knowledge_component: component,
          scenario: 'b2c_market_research',
        },
      },
    );
  }

  for (const targetStatus of ['collecting', 'synthesizing']) {
    await expectApiOk(
      page,
      'POST',
      `/v1/organizations/${organization.organization_id}/dossiers/${dossierId}/lifecycle`,
      {
        actor: buildAdminActor(),
        target_status: targetStatus,
        summary: `Playwright B2C dossier moved to ${targetStatus}.`,
        metadata: { source: 'playwright', scenario: 'b2c_market_research' },
      },
    );
  }

  await researchSection.getByRole('button', { name: /refresh/i }).click();
  await expect(researchSection.getByText(/turn 1/i)).toBeVisible();
  await expect(researchSection.getByText(/source bibliography/i).first()).toBeVisible();
  await expect(researchSection.getByText(/confirm b2c respondent profile/i)).toBeVisible();

  await researchSection.getByPlaceholder(/answer or approval note/i).fill(
    'Prioritize US wellness subscribers, with secondary notes for adjacent English-speaking markets.',
  );
  const answerResponse = page.waitForResponse(
    (response) =>
      response.request().method() === 'POST' &&
      /\/requests\/[^/]+\/answers$/.test(response.url()) &&
      response.ok(),
  );
  await researchSection.getByRole('button', { name: /^answer$/i }).click();
  await answerResponse;

  const readyResponse = page.waitForResponse(
    (response) =>
      response.request().method() === 'POST' &&
      /\/dossiers\/[^/]+\/lifecycle$/.test(response.url()) &&
      response.ok(),
  );
  await researchSection.getByRole('button', { name: /mark ready/i }).click();
  await readyResponse;

  await expectApiOk(
    page,
    'POST',
    `/v1/organizations/${organization.organization_id}/methodology/blueprints/${blueprintId}/versions/${versionId}/draft`,
    {
      actor: buildAdminActor(),
      cited_output: (
        '# B2C market research methodology\n\n'
        + 'Use consumer segment evidence [S1] before recommending launch channels.'
      ),
      harness_draft: {
        summary: 'B2C market research methodology draft.',
        methodology: {
          ontology: 'Consumers, needs, segments, channels, objections, and purchase triggers.',
          axiology: 'Prioritize evidence that reduces launch and positioning risk.',
          epistemology: 'Triangulate qualitative jobs-to-be-done with quantitative demand signals.',
          principles: [
            'Separate stated preference from observed buying intent.',
            'Keep launch recommendations tied to cited consumer evidence.',
          ],
        },
        methodics: [
          {
            name: 'Map consumer segments',
            goal: 'Identify high-intent B2C buyer segments and adoption barriers.',
            steps: [
              {
                instruction: (
                  'Researcher runs broad and refined internet search queries, then records '
                  + 'selected B2C methodology sources in the dossier.'
                ),
                recommended_tool_patterns: [
                  'web_search.search',
                  'dossiers.sources.create',
                ],
                expected_artifacts: ['search query log', 'source bibliography'],
                verification: [
                  'two internet search turns are represented',
                  'selected source URLs are HTTP or HTTPS',
                ],
              },
              {
                instruction: (
                  'Product lead, Researcher, Methodologist, Analyst, and consumer respondents '
                  + 'turn collected sources into validation assets.'
                ),
                recommended_tool_patterns: ['survey', 'spreadsheet', 'workspace.participants'],
                expected_artifacts: [
                  'participant responsibility matrix',
                  'interview guide',
                  'diary-study log',
                  'survey dataset',
                  'willingness-to-pay matrix',
                ],
                verification: ['each required participant and asset is named'],
              },
            ],
            success_criteria: [
              'At least one segment has cited need, trigger, and objection evidence.',
            ],
          },
        ],
        execution_rules: [
          {
            name: 'No uncited channel bets',
            instruction: 'Do not recommend acquisition channels without cited consumer evidence.',
          },
        ],
        metadata: {
          source: 'playwright',
          scenario: 'b2c_market_research',
          internet_search_turns: [
            {
              turn: 1,
              query: 'B2C market research methodology consumer segmentation purchase intent',
            },
            {
              turn: 2,
              query: 'B2C willingness to pay survey diary study purchase intent methodology',
            },
          ],
          participants: [
            'Researcher',
            'Methodologist',
            'Analyst',
            'Product lead',
            'Consumer respondents',
          ],
          tools: ['web_search.search', 'survey', 'spreadsheet', 'dossiers.navigate'],
          information_assets: [
            'source bibliography',
            'interview guide',
            'diary-study log',
            'survey dataset',
            'willingness-to-pay matrix',
            'segment scorecard',
          ],
        },
      },
    },
  );

  await page.getByRole('button', { name: /refresh/i }).first().click();
  await expect(page.getByText(title, { exact: true })).toBeVisible();

  const draftSection = page
    .getByText(/draft editor/i)
    .locator('xpath=ancestor::section[1]');
  await draftSection.locator('textarea').first().fill(
    '# B2C market research methodology\n\n'
      + 'Edited draft adds a purchase-intent validation checkpoint tied to [S1].',
  );
  await draftSection.locator('input').first().fill('Edited B2C market research methodology draft.');
  const saveDraftResponse = page.waitForResponse(
    (response) =>
      response.request().method() === 'POST' &&
      /\/draft$/.test(response.url()) &&
      response.ok(),
  );
  await draftSection.getByRole('button', { name: /save draft/i }).click();
  await saveDraftResponse;

  const approveResponse = page.waitForResponse(
    (response) =>
      response.request().method() === 'POST' &&
      /\/approve$/.test(response.url()) &&
      response.ok(),
  );
  await page.getByPlaceholder(/optional approval or rejection note/i).fill(
    'Approved initial B2C market research methodology.',
  );
  await page.getByRole('button', { name: /^approve$/i }).click();
  await approveResponse;
  await expect(draftSection.getByRole('button', { name: /create edited version/i })).toBeEnabled();

  await draftSection.locator('textarea').first().fill(
    '# Edited B2C market research methodology\n\n'
      + 'Add a diary-study signal, survey quantification, and willingness-to-pay screen before '
      + 'channel recommendations [S1].',
  );
  await draftSection.locator('input').first().fill('Human-edited B2C market research methodology.');
  await draftSection.getByPlaceholder(/why this edit is needed/i).fill(
    'Human editor added segmentation, survey quantification, and pricing validation.',
  );
  const createVersionResponse = page.waitForResponse(
    (response) =>
      response.request().method() === 'POST' &&
      /\/methodology\/blueprints\/[^/]+\/versions$/.test(response.url()) &&
      response.ok(),
  );
  await draftSection.getByRole('button', { name: /create edited version/i }).click();
  await createVersionResponse;
  await expect(draftSection.getByText(/version 2 - pending_review/i)).toBeVisible();

  const approveEditedResponse = page.waitForResponse(
    (response) =>
      response.request().method() === 'POST' &&
      /\/approve$/.test(response.url()) &&
      response.ok(),
  );
  await page.getByPlaceholder(/optional approval or rejection note/i).fill(
    'Approved human-edited B2C market research methodology.',
  );
  await page.getByRole('button', { name: /^approve$/i }).click();
  await approveEditedResponse;

  const applyResponse = page.waitForResponse(
    (response) =>
      response.request().method() === 'POST' &&
      /\/apply$/.test(response.url()) &&
      response.ok(),
  );
  await page.locator('select').filter({ hasText: /select workspace/i }).selectOption(workspaceId);
  await page.getByRole('button', { name: /^apply$/i }).click();
  await applyResponse;

  const archiveResponse = page.waitForResponse(
    (response) =>
      response.request().method() === 'DELETE' &&
      /\/methodology\/blueprints\//.test(response.url()) &&
      response.ok(),
  );
  await page.getByRole('button', { name: /^archive$/i }).click();
  await archiveResponse;
  await expect(page.getByText(title, { exact: true })).toBeVisible();
  await expect(
    page.locator('button').filter({ hasText: title }).getByText(/^archived$/).first(),
  ).toBeVisible();
});
