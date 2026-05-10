import React from 'react';
import { Edit3, FileJson } from 'lucide-react';

function TextInput({ label, value, onChange, placeholder = '' }) {
  return (
    <div>
      <label className="mb-1 block text-sm font-medium text-slate-700 dark:text-slate-300">
        {label}
      </label>
      <input
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
        className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-900"
      />
    </div>
  );
}

function JsonArea({ label, value, onChange, rows = 5 }) {
  return (
    <div>
      <label className="mb-1 flex items-center gap-2 text-sm font-medium text-slate-700 dark:text-slate-300">
        <FileJson className="h-4 w-4" />
        {label}
      </label>
      <textarea
        rows={rows}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="w-full resize-y rounded-lg border border-slate-200 bg-white px-3 py-2 font-mono text-xs dark:border-slate-700 dark:bg-slate-900"
      />
    </div>
  );
}

export default function DraftEditor({
  formData,
  selectedVersion,
  disabled,
  onChange,
  onSaveDraft,
  onCreateVersion,
  canEditVersion,
  canCreateVersion,
}) {
  const setField = (field, value) => onChange({ ...formData, [field]: value });

  return (
    <section className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-950">
      <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2 text-sm font-semibold text-slate-900 dark:text-slate-100">
            <Edit3 className="h-4 w-4 text-blue-500" />
            Draft Editor
          </div>
          <p className="mt-1 text-sm text-slate-600 dark:text-slate-400">
            Version {selectedVersion?.version_number || '-'} - {selectedVersion?.status || 'none'}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={onSaveDraft}
            disabled={disabled || !canEditVersion}
            className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:bg-slate-400"
          >
            Save Draft
          </button>
          <button
            type="button"
            onClick={onCreateVersion}
            disabled={disabled || !canCreateVersion}
            className="rounded-lg border border-slate-200 px-4 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-900"
          >
            Create Edited Version
          </button>
        </div>
      </div>

      <div className="space-y-4">
        <div>
          <label className="mb-1 block text-sm font-medium text-slate-700 dark:text-slate-300">
            Cited Output
          </label>
          <textarea
            rows={9}
            value={formData.cited_output}
            onChange={(event) => setField('cited_output', event.target.value)}
            className="w-full resize-y rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-900"
            placeholder="# Methodology draft with source citations"
          />
        </div>
        <TextInput
          label="Harness Summary"
          value={formData.harness_summary}
          onChange={(value) => setField('harness_summary', value)}
        />
        <div className="grid gap-4 lg:grid-cols-3">
          <TextInput
            label="Ontology"
            value={formData.methodology_ontology}
            onChange={(value) => setField('methodology_ontology', value)}
          />
          <TextInput
            label="Axiology"
            value={formData.methodology_axiology}
            onChange={(value) => setField('methodology_axiology', value)}
          />
          <TextInput
            label="Epistemology"
            value={formData.methodology_epistemology}
            onChange={(value) => setField('methodology_epistemology', value)}
          />
        </div>
        <JsonArea
          label="Methodology Principles JSON"
          value={formData.methodology_principles}
          onChange={(value) => setField('methodology_principles', value)}
          rows={4}
        />
        <JsonArea
          label="Methodics JSON"
          value={formData.methodics}
          onChange={(value) => setField('methodics', value)}
          rows={8}
        />
        <JsonArea
          label="Execution Rules JSON"
          value={formData.execution_rules}
          onChange={(value) => setField('execution_rules', value)}
        />
        <TextInput
          label="Revision Reason"
          value={formData.reason}
          onChange={(value) => setField('reason', value)}
          placeholder="Why this edit is needed"
        />
        <JsonArea
          label="Metadata JSON"
          value={formData.metadata}
          onChange={(value) => setField('metadata', value)}
          rows={4}
        />
      </div>
    </section>
  );
}
