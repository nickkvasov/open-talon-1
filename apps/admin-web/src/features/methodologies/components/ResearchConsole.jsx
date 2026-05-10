import React, { useMemo, useState } from 'react';
import {
  CheckCircle2,
  Circle,
  ClipboardCheck,
  HelpCircle,
  ListChecks,
  Network,
  RefreshCw,
  Search,
  Send,
} from 'lucide-react';

import {
  fullMethodologyKnowledgeComponents,
  knowledgeCoverageFromState,
} from '../forms';

const lifecycleSteps = [
  'created',
  'scoping',
  'collecting',
  'synthesizing',
  'ready',
  'consumed',
  'archived',
];

const sourceStatuses = [
  'discovered',
  'fetched',
  'included',
  'excluded',
  'duplicate',
  'failed',
  'rejected',
  'unresolved',
];

function componentLabel(value) {
  return String(value || '').replaceAll('_', ' ');
}

function shortId(value) {
  return value ? value.slice(0, 8) : '';
}

function LifecycleStepper({ dossier }) {
  const currentIndex = lifecycleSteps.indexOf(dossier?.status);
  return (
    <div className="grid gap-2 sm:grid-cols-4 xl:grid-cols-7">
      {lifecycleSteps.map((step, index) => {
        const reached = currentIndex >= index;
        return (
          <div
            key={step}
            className={`flex min-h-12 items-center gap-2 rounded-lg border px-3 py-2 text-xs font-medium ${
              reached
                ? 'border-blue-200 bg-blue-50 text-blue-800 dark:border-blue-900 dark:bg-blue-950/40 dark:text-blue-200'
                : 'border-slate-200 text-slate-500 dark:border-slate-800 dark:text-slate-400'
            }`}
          >
            {reached ? <CheckCircle2 className="h-4 w-4" /> : <Circle className="h-4 w-4" />}
            <span className="capitalize">{componentLabel(step)}</span>
          </div>
        );
      })}
    </div>
  );
}

function SearchTurns({ turns }) {
  if (!turns?.length) {
    return (
      <div className="rounded-lg border border-dashed border-slate-200 p-4 text-sm text-slate-500 dark:border-slate-800">
        No search turns have been persisted yet.
      </div>
    );
  }
  return (
    <div className="space-y-2">
      {turns.map((turn, index) => (
        <div
          key={`${turn.turn || index}-${turn.query || 'search'}`}
          className="rounded-lg border border-slate-200 p-3 dark:border-slate-800"
        >
          <div className="flex items-center justify-between gap-3">
            <div className="text-sm font-medium text-slate-900 dark:text-slate-100">
              Turn {turn.turn || index + 1}
            </div>
            <span className="text-xs text-slate-500">{turn.source_count} sources</span>
          </div>
          <p className="mt-1 text-sm text-slate-600 dark:text-slate-400">
            {turn.query || 'Search trace without query metadata'}
          </p>
        </div>
      ))}
    </div>
  );
}

function KnowledgeCoverage({ state }) {
  const coverage = knowledgeCoverageFromState(state);
  const required = new Set(fullMethodologyKnowledgeComponents);
  return (
    <div className="grid gap-2 md:grid-cols-2">
      {coverage.map((item) => (
        <div
          key={item.component}
          className={`rounded-lg border px-3 py-2 ${
            item.present
              ? 'border-emerald-200 bg-emerald-50 text-emerald-900 dark:border-emerald-900 dark:bg-emerald-950/30 dark:text-emerald-100'
              : 'border-slate-200 text-slate-600 dark:border-slate-800 dark:text-slate-300'
          }`}
        >
          <div className="flex items-center justify-between gap-2">
            <span className="text-sm font-medium capitalize">
              {componentLabel(item.component)}
            </span>
            <span className="text-xs">
              {item.item_count || 0}
              {required.has(item.component) ? '' : ' extra'}
            </span>
          </div>
        </div>
      ))}
    </div>
  );
}

function SourceCuration({ sources, disabled, onSourceStatusChange }) {
  if (!sources?.length) {
    return (
      <div className="rounded-lg border border-dashed border-slate-200 p-4 text-sm text-slate-500 dark:border-slate-800">
        No dossier sources have been collected.
      </div>
    );
  }
  return (
    <div className="space-y-2">
      {sources.map((source) => (
        <div
          key={source.source_id}
          className="grid gap-3 rounded-lg border border-slate-200 p-3 dark:border-slate-800 md:grid-cols-[1fr_150px]"
        >
          <div className="min-w-0">
            <div className="truncate text-sm font-medium text-slate-900 dark:text-slate-100">
              {source.title}
            </div>
            <div className="mt-1 flex flex-wrap gap-2 text-xs text-slate-500">
              <span>{source.source_kind}</span>
              <span>{source.citation_id || shortId(source.source_id)}</span>
              {source.source_uri ? (
                <a
                  href={source.source_uri}
                  target="_blank"
                  rel="noreferrer"
                  className="text-blue-600 hover:text-blue-700"
                >
                  Source
                </a>
              ) : null}
            </div>
          </div>
          <select
            value={source.status}
            disabled={disabled}
            onChange={(event) => onSourceStatusChange(source, event.target.value)}
            className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-900"
          >
            {sourceStatuses.map((status) => (
              <option key={status} value={status}>
                {status}
              </option>
            ))}
          </select>
        </div>
      ))}
    </div>
  );
}

function InteractionRequests({ requests, disabled, onAnswerInteraction }) {
  const [answers, setAnswers] = useState({});
  const openRequests = (requests || []).filter((item) => item.request.status === 'open');
  if (!openRequests.length) {
    return (
      <div className="rounded-lg border border-dashed border-slate-200 p-4 text-sm text-slate-500 dark:border-slate-800">
        No open Researcher questions or approvals.
      </div>
    );
  }
  return (
    <div className="space-y-3">
      {openRequests.map((requestDetail) => {
        const requestId = requestDetail.request.request_id;
        const answer = answers[requestId] || '';
        return (
          <div
            key={requestId}
            className="rounded-lg border border-amber-200 bg-amber-50 p-3 dark:border-amber-900 dark:bg-amber-950/30"
          >
            <div className="text-sm font-semibold text-amber-950 dark:text-amber-100">
              {requestDetail.request.title}
            </div>
            {requestDetail.request.summary ? (
              <p className="mt-1 text-sm text-amber-900 dark:text-amber-200">
                {requestDetail.request.summary}
              </p>
            ) : null}
            {requestDetail.questions?.length ? (
              <ul className="mt-2 space-y-1 text-sm text-amber-900 dark:text-amber-200">
                {requestDetail.questions.map((question) => (
                  <li key={question.question_id}>{question.prompt}</li>
                ))}
              </ul>
            ) : null}
            <textarea
              value={answer}
              disabled={disabled}
              onChange={(event) => setAnswers({
                ...answers,
                [requestId]: event.target.value,
              })}
              placeholder="Answer or approval note"
              rows={3}
              className="mt-3 w-full rounded-lg border border-amber-200 bg-white px-3 py-2 text-sm dark:border-amber-900 dark:bg-slate-950"
            />
            <button
              type="button"
              disabled={disabled || !answer.trim()}
              onClick={() => {
                onAnswerInteraction(requestDetail, answer);
                setAnswers({ ...answers, [requestId]: '' });
              }}
              className="mt-2 inline-flex items-center gap-2 rounded-lg bg-amber-600 px-3 py-2 text-sm font-medium text-white hover:bg-amber-700 disabled:cursor-not-allowed disabled:opacity-60"
            >
              <Send className="h-4 w-4" />
              Answer
            </button>
          </div>
        );
      })}
    </div>
  );
}

export default function ResearchConsole({
  state,
  loading,
  formData,
  disabled,
  onFormChange,
  onSubmitResearch,
  onMarkReady,
  onSourceStatusChange,
  onAnswerInteraction,
  onRefresh,
}) {
  const dossier = state?.dossier;
  const notebook = state?.notebook;
  const metadata = state?.metadata || {};
  const coverageSummary = useMemo(() => {
    const covered = metadata.covered_knowledge_component_count || 0;
    const required = metadata.required_knowledge_component_count || 0;
    return `${covered} / ${required || fullMethodologyKnowledgeComponents.length}`;
  }, [metadata.covered_knowledge_component_count, metadata.required_knowledge_component_count]);

  if (!dossier) {
    return (
      <section className="rounded-lg border border-dashed border-slate-200 p-5 text-sm text-slate-500 dark:border-slate-800">
        Research console is available after a blueprint creates a dossier.
      </section>
    );
  }

  return (
    <section className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-950">
      <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2 text-sm font-semibold text-slate-900 dark:text-slate-100">
            <Search className="h-4 w-4 text-blue-500" />
            Research Console
          </div>
          <p className="mt-1 text-sm text-slate-600 dark:text-slate-400">
            Launch and monitor Researcher-led methodology research for this dossier.
          </p>
        </div>
        <button
          type="button"
          disabled={loading}
          onClick={onRefresh}
          className="inline-flex items-center gap-2 rounded-lg border border-slate-200 px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-60 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-900"
        >
          <RefreshCw className="h-4 w-4" />
          Refresh
        </button>
      </div>

      <LifecycleStepper dossier={dossier} />

      <div className="mt-5 grid gap-4 md:grid-cols-4">
        <div className="rounded-lg border border-slate-200 p-3 dark:border-slate-800">
          <div className="mb-1 flex items-center gap-2 text-xs font-semibold uppercase text-slate-500">
            <ListChecks className="h-3.5 w-3.5" />
            Knowledge
          </div>
          <div className="text-sm text-slate-700 dark:text-slate-300">{coverageSummary}</div>
        </div>
        <div className="rounded-lg border border-slate-200 p-3 dark:border-slate-800">
          <div className="mb-1 flex items-center gap-2 text-xs font-semibold uppercase text-slate-500">
            <ClipboardCheck className="h-3.5 w-3.5" />
            Sources
          </div>
          <div className="text-sm text-slate-700 dark:text-slate-300">
            {state.sources?.length || 0}
          </div>
        </div>
        <div className="rounded-lg border border-slate-200 p-3 dark:border-slate-800">
          <div className="mb-1 flex items-center gap-2 text-xs font-semibold uppercase text-slate-500">
            <Network className="h-3.5 w-3.5" />
            Notebook Graph
          </div>
          <div className="text-sm text-slate-700 dark:text-slate-300">
            {(notebook?.concepts?.length || 0) + (notebook?.claims?.length || 0)} nodes
          </div>
        </div>
        <div className="rounded-lg border border-slate-200 p-3 dark:border-slate-800">
          <div className="mb-1 flex items-center gap-2 text-xs font-semibold uppercase text-slate-500">
            <HelpCircle className="h-3.5 w-3.5" />
            Open Requests
          </div>
          <div className="text-sm text-slate-700 dark:text-slate-300">
            {metadata.open_interaction_count || 0}
          </div>
        </div>
      </div>

      <form className="mt-5 space-y-3" onSubmit={onSubmitResearch}>
        <textarea
          value={formData.instructions}
          onChange={(event) => onFormChange({ ...formData, instructions: event.target.value })}
          placeholder="Ask Researcher to run/refine methodology research, search the internet, curate sources, fill missing components, or ask for clarification."
          rows={4}
          className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-900"
        />
        <div className="grid gap-3 md:grid-cols-[180px_1fr]">
          <label className="text-sm text-slate-600 dark:text-slate-400">
            Search turns
            <input
              type="number"
              min="1"
              max="20"
              value={formData.max_search_turns}
              onChange={(event) => onFormChange({
                ...formData,
                max_search_turns: event.target.value,
              })}
              className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-900"
            />
          </label>
          <label className="flex items-end gap-2 text-sm text-slate-600 dark:text-slate-400">
            <input
              type="checkbox"
              checked={formData.require_admin_ready_approval}
              onChange={(event) => onFormChange({
                ...formData,
                require_admin_ready_approval: event.target.checked,
              })}
              className="mb-2"
            />
            Require admin readiness approval
          </label>
        </div>
        <div className="grid gap-2 md:grid-cols-2">
          {fullMethodologyKnowledgeComponents.map((component) => (
            <label
              key={component}
              className="flex items-center gap-2 text-sm text-slate-600 dark:text-slate-400"
            >
              <input
                type="checkbox"
                checked={(formData.required_components || []).includes(component)}
                onChange={(event) => {
                  const current = new Set(formData.required_components || []);
                  if (event.target.checked) {
                    current.add(component);
                  } else {
                    current.delete(component);
                  }
                  onFormChange({
                    ...formData,
                    required_components: [...current],
                  });
                }}
              />
              <span className="capitalize">{componentLabel(component)}</span>
            </label>
          ))}
        </div>
        <textarea
          value={formData.metadata}
          onChange={(event) => onFormChange({ ...formData, metadata: event.target.value })}
          placeholder='{"priority":"high"}'
          rows={2}
          className="w-full rounded-lg border border-slate-200 px-3 py-2 font-mono text-xs dark:border-slate-700 dark:bg-slate-900"
        />
        <div className="flex flex-wrap gap-2">
          <button
            type="submit"
            disabled={disabled || !formData.instructions.trim()}
            className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-3 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-60"
          >
            <Send className="h-4 w-4" />
            Request Research
          </button>
          <button
            type="button"
            disabled={disabled || !metadata.can_mark_ready}
            onClick={onMarkReady}
            className="inline-flex items-center gap-2 rounded-lg border border-emerald-200 px-3 py-2 text-sm font-medium text-emerald-700 hover:bg-emerald-50 disabled:cursor-not-allowed disabled:opacity-60 dark:border-emerald-900 dark:text-emerald-300 dark:hover:bg-emerald-950/30"
          >
            <CheckCircle2 className="h-4 w-4" />
            Mark Ready
          </button>
        </div>
      </form>

      <div className="mt-6 grid gap-5 xl:grid-cols-2">
        <div>
          <h3 className="mb-3 text-sm font-semibold text-slate-900 dark:text-slate-100">
            Search Turns
          </h3>
          <SearchTurns turns={state.search_turns || []} />
        </div>
        <div>
          <h3 className="mb-3 text-sm font-semibold text-slate-900 dark:text-slate-100">
            Knowledge Coverage
          </h3>
          <KnowledgeCoverage state={state} />
        </div>
        <div>
          <h3 className="mb-3 text-sm font-semibold text-slate-900 dark:text-slate-100">
            Source Curation
          </h3>
          <SourceCuration
            sources={state.sources || []}
            disabled={disabled}
            onSourceStatusChange={onSourceStatusChange}
          />
        </div>
        <div>
          <h3 className="mb-3 text-sm font-semibold text-slate-900 dark:text-slate-100">
            Questions And Approvals
          </h3>
          <InteractionRequests
            requests={state.interaction_requests || []}
            disabled={disabled}
            onAnswerInteraction={onAnswerInteraction}
          />
        </div>
      </div>
    </section>
  );
}
