import React from 'react';
import { BookOpen, ExternalLink, FileText, GitBranch, Search } from 'lucide-react';

function shortId(value) {
  return value ? value.slice(0, 8) : '';
}

export default function DossierSummary({ dossier, sources, notebook }) {
  if (!dossier) {
    return (
      <section className="rounded-lg border border-dashed border-slate-200 p-5 text-sm text-slate-500 dark:border-slate-800">
        No dossier is linked to the selected version.
      </section>
    );
  }

  const sourceCount = sources?.length || 0;
  const includedCount = (sources || []).filter((source) => source.status === 'included').length;
  const notebookUrl = notebook?.notebook?.external_url;

  return (
    <section className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-950">
      <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2 text-sm font-semibold text-slate-900 dark:text-slate-100">
            <Search className="h-4 w-4 text-blue-500" />
            Dossier
          </div>
          <p className="mt-1 text-sm text-slate-600 dark:text-slate-400">{dossier.topic}</p>
        </div>
        <span className="rounded-full bg-slate-100 px-2.5 py-1 text-xs font-medium text-slate-700 dark:bg-slate-800 dark:text-slate-200">
          {dossier.status}
        </span>
      </div>
      <div className="grid gap-3 md:grid-cols-3">
        <div className="rounded-lg border border-slate-200 p-3 dark:border-slate-800">
          <div className="mb-1 flex items-center gap-2 text-xs font-semibold uppercase text-slate-500">
            <FileText className="h-3.5 w-3.5" />
            Sources
          </div>
          <div className="text-sm text-slate-700 dark:text-slate-300">
            {includedCount} included / {sourceCount} total
          </div>
        </div>
        <div className="rounded-lg border border-slate-200 p-3 dark:border-slate-800">
          <div className="mb-1 flex items-center gap-2 text-xs font-semibold uppercase text-slate-500">
            <BookOpen className="h-3.5 w-3.5" />
            Retained Library
          </div>
          <div className="font-mono text-sm text-slate-700 dark:text-slate-300">
            {shortId(dossier.retained_library_id) || 'none'}
          </div>
        </div>
        <div className="rounded-lg border border-slate-200 p-3 dark:border-slate-800">
          <div className="mb-1 flex items-center gap-2 text-xs font-semibold uppercase text-slate-500">
            <GitBranch className="h-3.5 w-3.5" />
            Context Packs
          </div>
          <div className="text-sm text-slate-700 dark:text-slate-300">
            {dossier.context_pack_ids?.length || 0}
          </div>
        </div>
      </div>
      {dossier.summary ? (
        <p className="mt-4 text-sm text-slate-700 dark:text-slate-300">{dossier.summary}</p>
      ) : null}
      {dossier.gaps?.length ? (
        <div className="mt-4 rounded-lg bg-amber-50 p-3 text-sm text-amber-900 dark:bg-amber-950/30 dark:text-amber-200">
          {dossier.gaps.length} unresolved gap{dossier.gaps.length === 1 ? '' : 's'} recorded.
        </div>
      ) : null}
      {notebookUrl ? (
        <a
          href={notebookUrl}
          target="_blank"
          rel="noreferrer"
          className="mt-4 inline-flex items-center gap-2 text-sm font-medium text-blue-600 hover:text-blue-700"
        >
          <ExternalLink className="h-4 w-4" />
          Open notebook projection
        </a>
      ) : null}
    </section>
  );
}
