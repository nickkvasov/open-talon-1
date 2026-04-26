import React, { useEffect, useMemo, useRef, useState } from 'react';
import { CheckCircle2, Clock3, Hammer, Package, XCircle } from 'lucide-react';

import { useApi } from '../api/useApi';
import { buildAdminActor } from '../config/adminActor';

const STATUS_BADGE = {
  submitted: 'bg-slate-100 text-slate-700',
  clarification_needed: 'bg-amber-100 text-amber-800',
  drafting: 'bg-blue-100 text-blue-800',
  validating: 'bg-cyan-100 text-cyan-800',
  pending_approval: 'bg-violet-100 text-violet-800',
  verifying_registry_pull: 'bg-amber-100 text-amber-900',
  published: 'bg-emerald-100 text-emerald-800',
  rejected: 'bg-rose-100 text-rose-800',
  failed: 'bg-red-100 text-red-800',
};

function StatusBadge({ status }) {
  return (
    <span className={`inline-flex rounded-full px-2.5 py-1 text-xs font-medium ${STATUS_BADGE[status] || 'bg-slate-100 text-slate-700'}`}>
      {status}
    </span>
  );
}

export default function ToolGenerationRequests() {
  const api = useApi();
  const [requests, setRequests] = useState([]);
  const [selectedRequestId, setSelectedRequestId] = useState('');
  const [selectedDetail, setSelectedDetail] = useState(null);
  const [filter, setFilter] = useState('pending_approval');
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [error, setError] = useState('');
  const [reviewReason, setReviewReason] = useState('');
  const requestLoadSeq = useRef(0);

  const selectedRevision = useMemo(() => {
    if (!selectedDetail?.revisions?.length) {
      return null;
    }
    return selectedDetail.revisions[0];
  }, [selectedDetail]);

  const loadRequests = async (requestedFilter = filter) => {
    const loadId = requestLoadSeq.current + 1;
    requestLoadSeq.current = loadId;
    try {
      setLoading(true);
      const response = await api.get('/v1/tool-generation/requests', {
        params: requestedFilter ? { status: requestedFilter } : {},
      });
      if (loadId !== requestLoadSeq.current) {
        return;
      }
      const nextRequests = response.data || [];
      setRequests(nextRequests);
      setSelectedRequestId((current) => {
        if (nextRequests.some(({ request }) => request.request_id === current)) {
          return current;
        }
        return nextRequests[0]?.request.request_id || '';
      });
      setError('');
    } catch (err) {
      if (loadId !== requestLoadSeq.current) {
        return;
      }
      setError(err.message || 'Failed to load tool-generation requests');
    } finally {
      if (loadId === requestLoadSeq.current) {
        setLoading(false);
      }
    }
  };

  const loadDetail = async (requestId) => {
    if (!requestId) {
      setSelectedDetail(null);
      return;
    }
    try {
      setDetailLoading(true);
      const response = await api.get(`/v1/tool-generation/requests/${requestId}`);
      setSelectedDetail(response.data);
      setError('');
    } catch (err) {
      setError(err.message || 'Failed to load request detail');
    } finally {
      setDetailLoading(false);
    }
  };

  useEffect(() => {
    loadRequests(filter);
  }, [api, filter]);

  useEffect(() => {
    if (selectedRequestId) {
      loadDetail(selectedRequestId);
    }
  }, [api, selectedRequestId]);

  const handleApprove = async () => {
    if (!selectedRevision) {
      return;
    }
    try {
      const response = await api.post(
        `/v1/tool-generation/revisions/${selectedRevision.revision_id}/approve`,
        {
          actor: buildAdminActor(),
          reason: reviewReason || null,
        },
      );
      setSelectedDetail(response.data);
      setReviewReason('');
      await loadRequests();
    } catch (err) {
      alert(`Failed to approve revision: ${err.message}`);
    }
  };

  const handleReject = async () => {
    if (!selectedRevision) {
      return;
    }
    try {
      const response = await api.post(
        `/v1/tool-generation/revisions/${selectedRevision.revision_id}/reject`,
        {
          actor: buildAdminActor(),
          reason: reviewReason || null,
        },
      );
      setSelectedDetail(response.data);
      setReviewReason('');
      await loadRequests();
    } catch (err) {
      alert(`Failed to reject revision: ${err.message}`);
    }
  };

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900 dark:text-slate-100">Tool Generation</h1>
          <p className="text-sm text-slate-600 dark:text-slate-400">
            Approve or reject generated tools before they appear in the global system tools catalog.
          </p>
        </div>
        <select
          value={filter}
          onChange={(event) => setFilter(event.target.value)}
          className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-900"
        >
          <option value="pending_approval">Pending approval</option>
          <option value="verifying_registry_pull">Verifying registry pull</option>
          <option value="submitted">Submitted</option>
          <option value="drafting">Drafting</option>
          <option value="validating">Validating</option>
          <option value="published">Published</option>
          <option value="rejected">Rejected</option>
          <option value="">All statuses</option>
        </select>
      </div>

      {error ? (
        <div className="rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
          {error}
        </div>
      ) : null}

      <div className="grid gap-6 lg:grid-cols-[360px_minmax(0,1fr)]">
        <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm dark:border-slate-800 dark:bg-slate-950">
          <div className="mb-4 flex items-center gap-2 text-sm font-medium text-slate-700 dark:text-slate-200">
            <Clock3 className="h-4 w-4" />
            Requests
          </div>
          {loading ? (
            <div className="text-sm text-slate-500">Loading requests…</div>
          ) : requests.length ? (
            <div className="space-y-3">
              {requests.map(({ request }) => (
                <button
                  type="button"
                  key={request.request_id}
                  onClick={() => setSelectedRequestId(request.request_id)}
                  className={`w-full rounded-xl border p-3 text-left transition ${
                    selectedRequestId === request.request_id
                      ? 'border-blue-400 bg-blue-50 dark:border-blue-700 dark:bg-blue-950/40'
                      : 'border-slate-200 hover:border-slate-300 dark:border-slate-800 dark:hover:border-slate-700'
                  }`}
                >
                  <div className="mb-2 flex items-center justify-between gap-3">
                    <div className="truncate font-medium text-slate-900 dark:text-slate-100">
                      {request.target_tool_name || 'Unnamed tool request'}
                    </div>
                    <StatusBadge status={request.status} />
                  </div>
                  <div className="text-xs text-slate-600 dark:text-slate-400">
                    {request.summary || 'No summary recorded yet.'}
                  </div>
                </button>
              ))}
            </div>
          ) : (
            <div className="text-sm text-slate-500">No matching tool-generation requests.</div>
          )}
        </div>

        <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-950">
          {detailLoading ? (
            <div className="text-sm text-slate-500">Loading request detail…</div>
          ) : selectedDetail ? (
            <div className="space-y-5">
              <div className="flex flex-wrap items-start justify-between gap-4">
                <div>
                  <h2 className="text-xl font-semibold text-slate-900 dark:text-slate-100">
                    {selectedDetail.request.target_tool_name || selectedRevision?.manifest?.name || 'Unnamed generated tool'}
                  </h2>
                  <p className="mt-1 text-sm text-slate-600 dark:text-slate-400">
                    {selectedDetail.request.summary || selectedRevision?.manifest?.description || 'No summary provided.'}
                  </p>
                </div>
                <StatusBadge status={selectedDetail.request.status} />
              </div>

              {selectedRevision ? (
                <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
                  <div className="rounded-xl border border-slate-200 p-4 dark:border-slate-800">
                    <div className="mb-2 flex items-center gap-2 text-sm font-medium text-slate-700 dark:text-slate-200">
                      <Hammer className="h-4 w-4" />
                      Revision
                    </div>
                    <div className="text-sm text-slate-600 dark:text-slate-400">
                      #{selectedRevision.revision_number} · {selectedRevision.status}
                    </div>
                  </div>
                  <div className="rounded-xl border border-slate-200 p-4 dark:border-slate-800">
                    <div className="mb-2 text-sm font-medium text-slate-700 dark:text-slate-200">Trust</div>
                    <div className="text-sm text-slate-600 dark:text-slate-400">
                      {selectedRevision.manifest.execution.trust_level}
                    </div>
                  </div>
                  <div className="rounded-xl border border-slate-200 p-4 dark:border-slate-800">
                    <div className="mb-2 text-sm font-medium text-slate-700 dark:text-slate-200">Network</div>
                    <div className="text-sm text-slate-600 dark:text-slate-400">
                      {selectedRevision.manifest.network_access}
                    </div>
                  </div>
                  <div className="rounded-xl border border-slate-200 p-4 dark:border-slate-800">
                    <div className="mb-2 text-sm font-medium text-slate-700 dark:text-slate-200">Workspace Access</div>
                    <div className="text-sm text-slate-600 dark:text-slate-400">
                      {selectedRevision.manifest.workspace_access}
                    </div>
                  </div>
                </div>
              ) : null}

              {selectedRevision ? (
                <>
                  <div className="rounded-xl border border-slate-200 p-4 dark:border-slate-800">
                    <div className="mb-2 flex items-center gap-2 text-sm font-medium text-slate-700 dark:text-slate-200">
                      <Package className="h-4 w-4" />
                      Image
                    </div>
                    <div className="space-y-1 text-sm text-slate-600 dark:text-slate-400">
                      <div>Ref: {selectedRevision.image_ref || 'Not recorded'}</div>
                      <div>Digest: {selectedRevision.image_digest || 'Not recorded'}</div>
                      <div>
                        Immutable ref:{' '}
                        {selectedRevision.metadata?.approval_verification_immutable_ref || selectedDetail.request.metadata?.approval_verification_immutable_ref || 'Not recorded'}
                      </div>
                    </div>
                  </div>

                  {selectedRevision.metadata?.approval_verification_error || selectedDetail.request.metadata?.approval_verification_error ? (
                    <div className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900 dark:border-amber-800 dark:bg-amber-950/40 dark:text-amber-200">
                      Latest verification error: {selectedRevision.metadata?.approval_verification_error || selectedDetail.request.metadata?.approval_verification_error}
                    </div>
                  ) : null}

                  <div className="rounded-xl border border-slate-200 p-4 dark:border-slate-800">
                    <div className="mb-3 text-sm font-medium text-slate-700 dark:text-slate-200">Validation</div>
                    <div className="text-sm text-slate-600 dark:text-slate-400">
                      {selectedRevision.validation_report?.summary || 'No validation summary recorded.'}
                    </div>
                    {selectedRevision.validation_report?.checks?.length ? (
                      <div className="mt-3 space-y-2">
                        {selectedRevision.validation_report.checks.map((check) => (
                          <div key={check.name} className="rounded-lg bg-slate-50 px-3 py-2 text-sm dark:bg-slate-900">
                            <div className="font-medium text-slate-800 dark:text-slate-100">
                              {check.name} · {check.status}
                            </div>
                            {check.detail ? (
                              <div className="mt-1 text-slate-600 dark:text-slate-400">{check.detail}</div>
                            ) : null}
                          </div>
                        ))}
                      </div>
                    ) : null}
                  </div>

                  <div className="rounded-xl border border-slate-200 p-4 dark:border-slate-800">
                    <div className="mb-3 text-sm font-medium text-slate-700 dark:text-slate-200">Review</div>
                    <textarea
                      value={reviewReason}
                      onChange={(event) => setReviewReason(event.target.value)}
                      rows={4}
                      placeholder="Optional approval or rejection note"
                      className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-900"
                    />
                    <div className="mt-4 flex flex-wrap gap-3">
                      <button
                        type="button"
                        onClick={handleApprove}
                        disabled={selectedRevision.status !== 'pending_approval'}
                        className="inline-flex items-center gap-2 rounded-lg bg-emerald-600 px-4 py-2 text-sm font-medium text-white disabled:cursor-not-allowed disabled:bg-slate-400"
                      >
                        <CheckCircle2 className="h-4 w-4" />
                        Approve
                      </button>
                      <button
                        type="button"
                        onClick={handleReject}
                        disabled={!['pending_approval', 'verifying_registry_pull', 'validating', 'drafting'].includes(selectedRevision.status)}
                        className="inline-flex items-center gap-2 rounded-lg bg-rose-600 px-4 py-2 text-sm font-medium text-white disabled:cursor-not-allowed disabled:bg-slate-400"
                      >
                        <XCircle className="h-4 w-4" />
                        Reject
                      </button>
                    </div>
                  </div>
                </>
              ) : (
                <div className="text-sm text-slate-500">No revisions recorded for this request yet.</div>
              )}
            </div>
          ) : (
            <div className="text-sm text-slate-500">Select a tool-generation request to inspect it.</div>
          )}
        </div>
      </div>
    </div>
  );
}
