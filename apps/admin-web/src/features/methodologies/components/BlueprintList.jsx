import React from 'react';
import { Archive, Clock3, FileText } from 'lucide-react';

function statusClass(status) {
  if (status === 'active') return 'bg-emerald-100 text-emerald-800';
  if (status === 'archived') return 'bg-slate-200 text-slate-700';
  return 'bg-blue-100 text-blue-800';
}

function shortId(value) {
  return value ? value.slice(0, 8) : '';
}

export default function BlueprintList({
  blueprints,
  selectedBlueprintId,
  loading,
  onSelect,
}) {
  if (loading) {
    return (
      <div className="rounded-lg border border-slate-200 bg-white p-6 text-sm text-slate-500 dark:border-slate-800 dark:bg-slate-950">
        Loading methodologies...
      </div>
    );
  }

  return (
    <section className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm dark:border-slate-800 dark:bg-slate-950">
      <div className="mb-4 flex items-center gap-2 text-sm font-semibold text-slate-700 dark:text-slate-200">
        <FileText className="h-4 w-4" />
        Methodology Blueprints
      </div>
      <div className="space-y-3">
        {blueprints.map((blueprint) => (
          <button
            type="button"
            key={blueprint.blueprint_id}
            onClick={() => onSelect(blueprint.blueprint_id)}
            className={`w-full rounded-lg border p-4 text-left transition ${
              selectedBlueprintId === blueprint.blueprint_id
                ? 'border-blue-400 bg-blue-50 dark:border-blue-700 dark:bg-blue-950/40'
                : 'border-slate-200 hover:border-slate-300 dark:border-slate-800 dark:hover:border-slate-700'
            }`}
          >
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="truncate font-semibold text-slate-900 dark:text-slate-100">
                  {blueprint.title}
                </div>
                <div className="mt-1 line-clamp-2 text-xs text-slate-600 dark:text-slate-400">
                  {blueprint.topic}
                </div>
              </div>
              <span className={`shrink-0 rounded-full px-2.5 py-1 text-xs font-medium ${statusClass(blueprint.status)}`}>
                {blueprint.status}
              </span>
            </div>
            <div className="mt-3 flex flex-wrap items-center gap-3 text-xs text-slate-500">
              <span className="inline-flex items-center gap-1">
                <Clock3 className="h-3.5 w-3.5" />
                {new Date(blueprint.updated_at || blueprint.created_at).toLocaleString()}
              </span>
              <span className="font-mono">{shortId(blueprint.blueprint_id)}</span>
              {blueprint.status === 'archived' ? (
                <span className="inline-flex items-center gap-1">
                  <Archive className="h-3.5 w-3.5" />
                  archived
                </span>
              ) : null}
            </div>
          </button>
        ))}
        {blueprints.length === 0 ? (
          <div className="rounded-lg border border-dashed border-slate-200 p-8 text-center text-sm text-slate-500 dark:border-slate-800">
            No methodologies match this filter.
          </div>
        ) : null}
      </div>
    </section>
  );
}
