import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { AlertTriangle, BookOpenCheck, RefreshCw } from 'lucide-react';

import { useApi } from '../../api/useApi';
import { buildAdminActor } from '../../config/adminActor';
import {
  archiveMethodologyBlueprint,
  answerInteractionRequest,
  applyMethodologyBlueprint,
  createMethodologyBlueprint,
  createMethodologyBlueprintVersion,
  createMethodologyResearchRequest,
  getMethodologyBlueprint,
  getDossierNotebook,
  getMethodologyResearchState,
  listMethodologyBlueprints,
  reviewMethodologyBlueprintVersion,
  submitMethodologyBlueprintDraft,
  transitionDossierLifecycle,
  updateDossierSource,
} from './api';
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
  blankCreateForm,
  draftFormFromVersion,
  isVersionEditable,
  requiresNewVersion,
} from './forms';
import BlueprintList from './components/BlueprintList';
import CreateBlueprintForm from './components/CreateBlueprintForm';
import DossierSummary from './components/DossierSummary';
import DraftEditor from './components/DraftEditor';
import ResearchConsole from './components/ResearchConsole';
import ReviewControls from './components/ReviewControls';

function errorMessage(error, fallback) {
  const detail = error?.response?.data?.detail;
  if (typeof detail === 'string') return detail;
  return error?.message || fallback;
}

function statusClass(status) {
  if (status === 'approved') return 'bg-emerald-100 text-emerald-800';
  if (status === 'pending_review') return 'bg-violet-100 text-violet-800';
  if (status === 'rejected' || status === 'failed') return 'bg-rose-100 text-rose-800';
  return 'bg-slate-100 text-slate-700';
}

export default function MethodologiesPage() {
  const api = useApi();
  const actor = useMemo(() => buildAdminActor(), []);
  const [organizations, setOrganizations] = useState([]);
  const [selectedOrganizationId, setSelectedOrganizationId] = useState('');
  const [libraries, setLibraries] = useState([]);
  const [workspaces, setWorkspaces] = useState([]);
  const [blueprints, setBlueprints] = useState([]);
  const [selectedBlueprintId, setSelectedBlueprintId] = useState('');
  const [detail, setDetail] = useState(null);
  const [selectedVersionId, setSelectedVersionId] = useState('');
  const [notebook, setNotebook] = useState(null);
  const [researchState, setResearchState] = useState(null);
  const [statusFilter, setStatusFilter] = useState('active_review');
  const [createForm, setCreateForm] = useState(blankCreateForm);
  const [researchForm, setResearchForm] = useState(blankResearchForm);
  const [draftForm, setDraftForm] = useState(draftFormFromVersion());
  const [reviewReason, setReviewReason] = useState('');
  const [applyWorkspaceId, setApplyWorkspaceId] = useState('');
  const [preserveModerationPolicy, setPreserveModerationPolicy] = useState(true);
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [researchLoading, setResearchLoading] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');

  const selectedVersion = useMemo(() => {
    if (!detail?.versions?.length) return null;
    return detail.versions.find((version) => version.version_id === selectedVersionId)
      || detail.versions[0];
  }, [detail, selectedVersionId]);

  const refreshBlueprints = useCallback(async () => {
    if (!selectedOrganizationId) {
      setBlueprints([]);
      setSelectedBlueprintId('');
      setLoading(false);
      return;
    }
    try {
      setLoading(true);
      const nextBlueprints = await listMethodologyBlueprints(
        api,
        selectedOrganizationId,
        statusFilter,
      );
      setBlueprints(nextBlueprints);
      setSelectedBlueprintId((current) => (
        nextBlueprints.some((blueprint) => blueprint.blueprint_id === current)
          ? current
          : nextBlueprints[0]?.blueprint_id || ''
      ));
      setError('');
    } catch (err) {
      setError(errorMessage(err, 'Failed to load methodology blueprints'));
    } finally {
      setLoading(false);
    }
  }, [api, selectedOrganizationId, statusFilter]);

  const refreshDetail = useCallback(async (blueprintId = selectedBlueprintId) => {
    if (!selectedOrganizationId || !blueprintId) {
      setDetail(null);
      return;
    }
    try {
      setDetailLoading(true);
      const nextDetail = await getMethodologyBlueprint(
        api,
        selectedOrganizationId,
        blueprintId,
      );
      setDetail(nextDetail);
      setSelectedVersionId((current) => (
        nextDetail.versions?.some((version) => version.version_id === current)
          ? current
          : nextDetail.versions?.[0]?.version_id || ''
      ));
      setError('');
    } catch (err) {
      setDetail(null);
      setError(errorMessage(err, 'Failed to load methodology detail'));
    } finally {
      setDetailLoading(false);
    }
  }, [api, selectedBlueprintId, selectedOrganizationId]);

  const refreshResearchState = useCallback(async (blueprintId = selectedBlueprintId) => {
    if (!selectedOrganizationId || !blueprintId) {
      setResearchState(null);
      return;
    }
    try {
      setResearchLoading(true);
      const nextState = await getMethodologyResearchState(
        api,
        selectedOrganizationId,
        blueprintId,
      );
      setResearchState(nextState);
    } catch (err) {
      setResearchState(null);
      setError(errorMessage(err, 'Failed to load methodology research state'));
    } finally {
      setResearchLoading(false);
    }
  }, [api, selectedBlueprintId, selectedOrganizationId]);

  useEffect(() => {
    const loadOrganizations = async () => {
      try {
        const response = await api.get('/v1/organizations');
        const nextOrganizations = response.data || [];
        setOrganizations(nextOrganizations);
        setSelectedOrganizationId((current) => (
          nextOrganizations.some((organization) => organization.organization_id === current)
            ? current
            : nextOrganizations[0]?.organization_id || ''
        ));
      } catch (err) {
        setError(errorMessage(err, 'Failed to load organizations'));
      }
    };
    void loadOrganizations();
  }, [api]);

  useEffect(() => {
    const loadContext = async () => {
      if (!selectedOrganizationId) {
        setLibraries([]);
        setWorkspaces([]);
        return;
      }
      try {
        const [organizationLibraries, projectsResponse, workspacesResponse] = await Promise.all([
          api.get(`/v1/organizations/${selectedOrganizationId}/libraries`),
          api.get(`/v1/organizations/${selectedOrganizationId}/projects`),
          api.get('/v1/workspaces', { params: { organization_id: selectedOrganizationId } }),
        ]);
        const projectLibraries = await Promise.all(
          (projectsResponse.data || []).map((project) => (
            api
              .get(`/v1/organizations/${selectedOrganizationId}/projects/${project.project_id}/libraries`)
              .then((response) => response.data || [])
              .catch(() => [])
          )),
        );
        setLibraries([
          ...(organizationLibraries.data || []),
          ...projectLibraries.flat(),
        ]);
        setWorkspaces((workspacesResponse.data || []).map((item) => item.workspace || item));
        setApplyWorkspaceId('');
      } catch (err) {
        setError(errorMessage(err, 'Failed to load organization context'));
      }
    };
    void loadContext();
  }, [api, selectedOrganizationId]);

  useEffect(() => {
    void refreshBlueprints();
  }, [refreshBlueprints]);

  useEffect(() => {
    void refreshDetail();
  }, [refreshDetail]);

  useEffect(() => {
    void refreshResearchState();
  }, [refreshResearchState]);

  useEffect(() => {
    setDraftForm(draftFormFromVersion(selectedVersion));
    setReviewReason('');
  }, [selectedVersion]);

  useEffect(() => {
    const loadNotebook = async () => {
      if (!selectedOrganizationId || !detail?.dossier?.dossier_id) {
        setNotebook(null);
        return;
      }
      try {
        const nextNotebook = await getDossierNotebook(
          api,
          selectedOrganizationId,
          detail.dossier.dossier_id,
        );
        setNotebook(nextNotebook);
      } catch {
        setNotebook(null);
      }
    };
    void loadNotebook();
  }, [api, detail?.dossier?.dossier_id, selectedOrganizationId]);

  const handleCreate = async (event) => {
    event.preventDefault();
    if (!selectedOrganizationId) return;
    try {
      setSubmitting(true);
      const nextDetail = await createMethodologyBlueprint(
        api,
        selectedOrganizationId,
        buildMethodologyCreatePayload(actor, createForm),
      );
      setCreateForm(blankCreateForm);
      setSelectedBlueprintId(nextDetail.blueprint.blueprint_id);
      setDetail(nextDetail);
      await refreshResearchState(nextDetail.blueprint.blueprint_id);
      await refreshBlueprints();
    } catch (err) {
      setError(errorMessage(err, 'Failed to create methodology blueprint'));
    } finally {
      setSubmitting(false);
    }
  };

  const handleRequestResearch = async (event) => {
    event.preventDefault();
    if (!selectedOrganizationId || !detail) return;
    try {
      setSubmitting(true);
      const nextState = await createMethodologyResearchRequest(
        api,
        selectedOrganizationId,
        detail.blueprint.blueprint_id,
        buildMethodologyResearchRequestPayload(actor, researchForm),
      );
      setResearchState(nextState);
      setResearchForm({ ...researchForm, instructions: '' });
      await refreshDetail(detail.blueprint.blueprint_id);
      await refreshBlueprints();
    } catch (err) {
      setError(errorMessage(err, 'Failed to request methodology research'));
    } finally {
      setSubmitting(false);
    }
  };

  const handleMarkResearchReady = async () => {
    if (!selectedOrganizationId || !researchState?.dossier) return;
    try {
      setSubmitting(true);
      await transitionDossierLifecycle(
        api,
        selectedOrganizationId,
        researchState.dossier.dossier_id,
        buildDossierLifecyclePayload({
          actor,
          targetStatus: 'ready',
          summary: researchState.dossier.summary || 'Admin approved dossier readiness.',
          reason: 'admin_research_console_ready_approval',
          metadata: {
            admin_ready_approved: true,
            approved_from: 'methodology_research_console',
          },
        }),
      );
      await refreshDetail(detail.blueprint.blueprint_id);
      await refreshResearchState(detail.blueprint.blueprint_id);
      await refreshBlueprints();
    } catch (err) {
      setError(errorMessage(err, 'Failed to mark dossier ready'));
    } finally {
      setSubmitting(false);
    }
  };

  const handleSourceStatusChange = async (source, nextStatus) => {
    if (!selectedOrganizationId || !researchState?.dossier) return;
    try {
      setSubmitting(true);
      await updateDossierSource(
        api,
        selectedOrganizationId,
        researchState.dossier.dossier_id,
        source.source_id,
        buildDossierSourceUpdatePayload(actor, source, nextStatus),
      );
      await refreshDetail(detail.blueprint.blueprint_id);
      await refreshResearchState(detail.blueprint.blueprint_id);
    } catch (err) {
      setError(errorMessage(err, 'Failed to update dossier source'));
    } finally {
      setSubmitting(false);
    }
  };

  const handleAnswerInteraction = async (requestDetail, content) => {
    if (!requestDetail?.request?.request_id) return;
    try {
      setSubmitting(true);
      await answerInteractionRequest(
        api,
        requestDetail.request.request_id,
        buildInteractionAnswerPayload(actor, requestDetail, content),
      );
      await refreshResearchState(detail.blueprint.blueprint_id);
    } catch (err) {
      setError(errorMessage(err, 'Failed to answer Researcher request'));
    } finally {
      setSubmitting(false);
    }
  };

  const handleSaveDraft = async () => {
    if (!selectedOrganizationId || !detail || !selectedVersion) return;
    try {
      setSubmitting(true);
      const nextDetail = await submitMethodologyBlueprintDraft(
        api,
        selectedOrganizationId,
        detail.blueprint.blueprint_id,
        selectedVersion.version_id,
        buildMethodologyDraftPayload(actor, draftForm),
      );
      setDetail(nextDetail);
      await refreshBlueprints();
    } catch (err) {
      setError(errorMessage(err, 'Failed to save methodology draft'));
    } finally {
      setSubmitting(false);
    }
  };

  const handleCreateVersion = async () => {
    if (!selectedOrganizationId || !detail || !selectedVersion) return;
    try {
      setSubmitting(true);
      const nextDetail = await createMethodologyBlueprintVersion(
        api,
        selectedOrganizationId,
        detail.blueprint.blueprint_id,
        buildMethodologyVersionPayload(actor, selectedVersion.version_id, draftForm),
      );
      setDetail(nextDetail);
      setSelectedVersionId(nextDetail.versions?.[0]?.version_id || '');
      await refreshBlueprints();
    } catch (err) {
      setError(errorMessage(err, 'Failed to create edited methodology version'));
    } finally {
      setSubmitting(false);
    }
  };

  const handleReview = async (approved) => {
    if (!selectedOrganizationId || !detail || !selectedVersion) return;
    try {
      setSubmitting(true);
      const nextDetail = await reviewMethodologyBlueprintVersion({
        api,
        organizationId: selectedOrganizationId,
        blueprintId: detail.blueprint.blueprint_id,
        versionId: selectedVersion.version_id,
        approved,
        payload: buildMethodologyReviewPayload(actor, reviewReason),
      });
      setDetail(nextDetail);
      setReviewReason('');
      await refreshBlueprints();
    } catch (err) {
      setError(errorMessage(err, 'Failed to review methodology version'));
    } finally {
      setSubmitting(false);
    }
  };

  const handleApply = async () => {
    if (!selectedOrganizationId || !detail || !selectedVersion || !applyWorkspaceId) return;
    try {
      setSubmitting(true);
      await applyMethodologyBlueprint(
        api,
        selectedOrganizationId,
        detail.blueprint.blueprint_id,
        buildMethodologyApplyPayload({
          actor,
          workspaceId: applyWorkspaceId,
          versionId: selectedVersion.version_id,
          preserveModerationPolicy,
        }),
      );
      setError('');
      window.alert('Methodology applied to workspace.');
    } catch (err) {
      setError(errorMessage(err, 'Failed to apply methodology blueprint'));
    } finally {
      setSubmitting(false);
    }
  };

  const handleArchive = async () => {
    if (!selectedOrganizationId || !detail) return;
    if (!window.confirm('Archive this methodology? It will remain readable but cannot be applied or edited.')) {
      return;
    }
    try {
      setSubmitting(true);
      await archiveMethodologyBlueprint(
        api,
        selectedOrganizationId,
        detail.blueprint.blueprint_id,
        buildMethodologyArchivePayload(actor),
      );
      setStatusFilter('archived');
      await refreshBlueprints();
      await refreshDetail(detail.blueprint.blueprint_id);
    } catch (err) {
      setError(errorMessage(err, 'Failed to archive methodology blueprint'));
    } finally {
      setSubmitting(false);
    }
  };

  const canEditVersion = isVersionEditable(selectedVersion, detail?.blueprint);
  const canCreateVersion = requiresNewVersion(selectedVersion, detail?.blueprint);

  return (
    <div className="p-6 space-y-6">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <h1 className="flex items-center gap-3 text-2xl font-semibold text-slate-900 dark:text-slate-100">
            <BookOpenCheck className="h-6 w-6 text-blue-500" />
            Methodologies
          </h1>
          <p className="mt-1 text-sm text-slate-600 dark:text-slate-400">
            Create, review, apply, and archive organization methodology blueprints.
          </p>
        </div>
        <div className="flex flex-wrap gap-3">
          <select
            value={selectedOrganizationId}
            onChange={(event) => setSelectedOrganizationId(event.target.value)}
            className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-900"
          >
            <option value="">Organization</option>
            {organizations.map((organization) => (
              <option key={organization.organization_id} value={organization.organization_id}>
                {organization.name}
              </option>
            ))}
          </select>
          <select
            value={statusFilter}
            onChange={(event) => setStatusFilter(event.target.value)}
            className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-900"
          >
            <option value="active_review">Active review</option>
            <option value="draft">Draft</option>
            <option value="active">Active</option>
            <option value="archived">Archived</option>
            <option value="">All statuses</option>
          </select>
          <button
            type="button"
            onClick={() => void refreshBlueprints()}
            className="inline-flex items-center gap-2 rounded-lg border border-slate-200 px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-900"
          >
            <RefreshCw className="h-4 w-4" />
            Refresh
          </button>
        </div>
      </div>

      {error ? (
        <div className="flex items-center gap-3 rounded-lg border border-rose-200 bg-rose-50 p-4 text-sm text-rose-700 dark:border-rose-800 dark:bg-rose-950/30 dark:text-rose-200">
          <AlertTriangle className="h-5 w-5" />
          {error}
        </div>
      ) : null}

      <div className="grid gap-6 xl:grid-cols-[380px_minmax(0,1fr)]">
        <div className="space-y-6">
          <CreateBlueprintForm
            formData={createForm}
            libraries={libraries}
            disabled={!selectedOrganizationId || submitting}
            onChange={setCreateForm}
            onSubmit={handleCreate}
          />
          <BlueprintList
            blueprints={blueprints}
            selectedBlueprintId={selectedBlueprintId}
            loading={loading}
            onSelect={setSelectedBlueprintId}
          />
        </div>

        <div className="space-y-6">
          {detailLoading ? (
            <div className="rounded-lg border border-slate-200 bg-white p-6 text-sm text-slate-500 dark:border-slate-800 dark:bg-slate-950">
              Loading methodology detail...
            </div>
          ) : detail ? (
            <>
              <section className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-950">
                <div className="flex flex-wrap items-start justify-between gap-4">
                  <div>
                    <h2 className="text-xl font-semibold text-slate-900 dark:text-slate-100">
                      {detail.blueprint.title}
                    </h2>
                    <p className="mt-1 text-sm text-slate-600 dark:text-slate-400">
                      {detail.blueprint.topic}
                    </p>
                  </div>
                  <span className="rounded-full bg-slate-100 px-2.5 py-1 text-xs font-medium text-slate-700 dark:bg-slate-800 dark:text-slate-200">
                    {detail.blueprint.status}
                  </span>
                </div>
                <div className="mt-4 flex flex-wrap gap-2">
                  {(detail.versions || []).map((version) => (
                    <button
                      type="button"
                      key={version.version_id}
                      onClick={() => setSelectedVersionId(version.version_id)}
                      className={`rounded-lg border px-3 py-2 text-left text-sm transition ${
                        selectedVersion?.version_id === version.version_id
                          ? 'border-blue-400 bg-blue-50 dark:border-blue-700 dark:bg-blue-950/40'
                          : 'border-slate-200 hover:bg-slate-50 dark:border-slate-800 dark:hover:bg-slate-900'
                      }`}
                    >
                      <span className="font-semibold">v{version.version_number}</span>
                      <span className={`ml-2 rounded-full px-2 py-0.5 text-xs ${statusClass(version.status)}`}>
                        {version.status}
                      </span>
                    </button>
                  ))}
                </div>
              </section>

              <DossierSummary
                dossier={detail.dossier}
                sources={detail.sources || []}
                notebook={notebook}
              />

              <ResearchConsole
                state={researchState}
                loading={researchLoading}
                formData={researchForm}
                disabled={submitting || detail.blueprint.status === 'archived'}
                onFormChange={setResearchForm}
                onSubmitResearch={handleRequestResearch}
                onMarkReady={() => void handleMarkResearchReady()}
                onSourceStatusChange={(source, nextStatus) => (
                  void handleSourceStatusChange(source, nextStatus)
                )}
                onAnswerInteraction={(requestDetail, content) => (
                  void handleAnswerInteraction(requestDetail, content)
                )}
                onRefresh={() => void refreshResearchState(detail.blueprint.blueprint_id)}
              />

              <DraftEditor
                formData={draftForm}
                selectedVersion={selectedVersion}
                disabled={submitting || detail.blueprint.status === 'archived'}
                onChange={setDraftForm}
                onSaveDraft={handleSaveDraft}
                onCreateVersion={handleCreateVersion}
                canEditVersion={canEditVersion}
                canCreateVersion={canCreateVersion}
              />

              <ReviewControls
                selectedVersion={selectedVersion}
                blueprint={detail.blueprint}
                workspaces={workspaces}
                workspaceId={applyWorkspaceId}
                reviewReason={reviewReason}
                preserveModerationPolicy={preserveModerationPolicy}
                disabled={submitting}
                onWorkspaceChange={setApplyWorkspaceId}
                onReviewReasonChange={setReviewReason}
                onPreserveModerationChange={setPreserveModerationPolicy}
                onApprove={() => void handleReview(true)}
                onReject={() => void handleReview(false)}
                onApply={() => void handleApply()}
                onArchive={() => void handleArchive()}
              />
            </>
          ) : (
            <div className="rounded-lg border border-dashed border-slate-200 p-10 text-center text-sm text-slate-500 dark:border-slate-800">
              Select or create a methodology blueprint.
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
