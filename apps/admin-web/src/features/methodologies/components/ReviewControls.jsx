import React from 'react';
import { Archive, CheckCircle2, Send, XCircle } from 'lucide-react';

export default function ReviewControls({
  selectedVersion,
  blueprint,
  workspaces,
  workspaceId,
  reviewReason,
  preserveModerationPolicy,
  disabled,
  onWorkspaceChange,
  onReviewReasonChange,
  onPreserveModerationChange,
  onApprove,
  onReject,
  onApply,
  onArchive,
}) {
  const isArchived = blueprint?.status === 'archived';
  const canReview = selectedVersion?.status === 'pending_review' && !isArchived;
  const canApply = selectedVersion?.status === 'approved' && !isArchived && workspaceId;
  const canArchive = blueprint && !isArchived;

  return (
    <section className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-950">
      <div className="mb-4 text-sm font-semibold text-slate-900 dark:text-slate-100">
        Review And Apply
      </div>
      <div className="space-y-4">
        <div>
          <label className="mb-1 block text-sm font-medium text-slate-700 dark:text-slate-300">
            Review Reason
          </label>
          <textarea
            rows={3}
            value={reviewReason}
            onChange={(event) => onReviewReasonChange(event.target.value)}
            className="w-full resize-none rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-900"
            placeholder="Optional approval or rejection note"
          />
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={onApprove}
            disabled={disabled || !canReview}
            className="inline-flex items-center gap-2 rounded-lg bg-emerald-600 px-4 py-2 text-sm font-semibold text-white hover:bg-emerald-700 disabled:cursor-not-allowed disabled:bg-slate-400"
          >
            <CheckCircle2 className="h-4 w-4" />
            Approve
          </button>
          <button
            type="button"
            onClick={onReject}
            disabled={disabled || !canReview}
            className="inline-flex items-center gap-2 rounded-lg bg-rose-600 px-4 py-2 text-sm font-semibold text-white hover:bg-rose-700 disabled:cursor-not-allowed disabled:bg-slate-400"
          >
            <XCircle className="h-4 w-4" />
            Reject
          </button>
        </div>
        <div className="border-t border-slate-200 pt-4 dark:border-slate-800">
          <label className="mb-1 block text-sm font-medium text-slate-700 dark:text-slate-300">
            Apply To Workspace
          </label>
          <div className="flex flex-col gap-3 lg:flex-row">
            <select
              value={workspaceId}
              onChange={(event) => onWorkspaceChange(event.target.value)}
              className="min-w-0 flex-1 rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-900"
            >
              <option value="">Select workspace</option>
              {workspaces.map((workspace) => (
                <option key={workspace.workspace_id} value={workspace.workspace_id}>
                  {workspace.name}
                </option>
              ))}
            </select>
            <button
              type="button"
              onClick={onApply}
              disabled={disabled || !canApply}
              className="inline-flex items-center justify-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:bg-slate-400"
            >
              <Send className="h-4 w-4" />
              Apply
            </button>
          </div>
          <label className="mt-3 flex items-center gap-2 text-sm text-slate-600 dark:text-slate-400">
            <input
              type="checkbox"
              checked={preserveModerationPolicy}
              onChange={(event) => onPreserveModerationChange(event.target.checked)}
            />
            Preserve workspace moderation policy
          </label>
        </div>
        <div className="border-t border-slate-200 pt-4 dark:border-slate-800">
          <button
            type="button"
            onClick={onArchive}
            disabled={disabled || !canArchive}
            className="inline-flex items-center gap-2 rounded-lg border border-slate-200 px-4 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-900"
          >
            <Archive className="h-4 w-4" />
            Archive
          </button>
        </div>
      </div>
    </section>
  );
}
