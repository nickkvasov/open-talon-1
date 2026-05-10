import React from 'react';
import { BookOpen, Plus } from 'lucide-react';

export default function CreateBlueprintForm({
  formData,
  libraries,
  disabled,
  onChange,
  onSubmit,
}) {
  const toggleLibrary = (libraryId) => {
    const selected = new Set(formData.library_ids);
    if (selected.has(libraryId)) {
      selected.delete(libraryId);
    } else {
      selected.add(libraryId);
    }
    onChange({ ...formData, library_ids: Array.from(selected) });
  };

  return (
    <form
      onSubmit={onSubmit}
      className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-950"
    >
      <div className="mb-4 flex items-center gap-2 font-semibold text-slate-900 dark:text-slate-100">
        <Plus className="h-4 w-4 text-blue-500" />
        Request Methodology
      </div>
      <div className="space-y-4">
        <div>
          <label className="mb-1 block text-sm font-medium text-slate-700 dark:text-slate-300">
            Title
          </label>
          <input
            required
            value={formData.title}
            onChange={(event) => onChange({ ...formData, title: event.target.value })}
            className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-900"
            placeholder="Evidence-backed onboarding"
          />
        </div>
        <div>
          <label className="mb-1 block text-sm font-medium text-slate-700 dark:text-slate-300">
            Research Topic
          </label>
          <textarea
            required
            rows={3}
            value={formData.topic}
            onChange={(event) => onChange({ ...formData, topic: event.target.value })}
            className="w-full resize-none rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-900"
            placeholder="What should Researcher investigate?"
          />
        </div>
        <div>
          <label className="mb-1 block text-sm font-medium text-slate-700 dark:text-slate-300">
            Target Goal
          </label>
          <input
            value={formData.target_goal}
            onChange={(event) => onChange({ ...formData, target_goal: event.target.value })}
            className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-900"
            placeholder="Reusable workspace methodology"
          />
        </div>
        <div>
          <label className="mb-1 block text-sm font-medium text-slate-700 dark:text-slate-300">
            Research Tasks
          </label>
          <textarea
            rows={4}
            value={formData.tasks}
            onChange={(event) => onChange({ ...formData, tasks: event.target.value })}
            className="w-full resize-none rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-900"
            placeholder={'Discover source evidence\nIdentify contradictions\nDraft workspace methodics'}
          />
        </div>
        <div>
          <label className="mb-1 block text-sm font-medium text-slate-700 dark:text-slate-300">
            Source Policy
          </label>
          <select
            value={formData.source_policy}
            onChange={(event) => onChange({ ...formData, source_policy: event.target.value })}
            className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-900"
          >
            <option value="hybrid">hybrid</option>
            <option value="local_first">local_first</option>
            <option value="web_first">web_first</option>
          </select>
        </div>
        <div>
          <div className="mb-2 flex items-center gap-2 text-sm font-medium text-slate-700 dark:text-slate-300">
            <BookOpen className="h-4 w-4" />
            Source Libraries
          </div>
          <div className="max-h-44 space-y-2 overflow-y-auto rounded-lg border border-slate-200 p-3 dark:border-slate-800">
            {libraries.map((library) => (
              <label
                key={library.library_id}
                className="flex items-start gap-2 text-sm text-slate-700 dark:text-slate-300"
              >
                <input
                  type="checkbox"
                  checked={formData.library_ids.includes(library.library_id)}
                  onChange={() => toggleLibrary(library.library_id)}
                  className="mt-1"
                />
                <span className="min-w-0">
                  <span className="block truncate font-medium">{library.name}</span>
                  <span className="block text-xs text-slate-500">
                    {library.scope} - {library.slug}
                  </span>
                </span>
              </label>
            ))}
            {libraries.length === 0 ? (
              <div className="text-sm text-slate-500">No organization libraries available.</div>
            ) : null}
          </div>
        </div>
        <div>
          <label className="mb-1 block text-sm font-medium text-slate-700 dark:text-slate-300">
            Metadata JSON
          </label>
          <textarea
            rows={3}
            value={formData.metadata}
            onChange={(event) => onChange({ ...formData, metadata: event.target.value })}
            className="w-full resize-none rounded-lg border border-slate-200 bg-white px-3 py-2 font-mono text-xs dark:border-slate-700 dark:bg-slate-900"
          />
        </div>
        <button
          type="submit"
          disabled={disabled}
          className="w-full rounded-lg bg-blue-600 px-4 py-2.5 text-sm font-semibold text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:bg-slate-400"
        >
          Create Blueprint
        </button>
      </div>
    </form>
  );
}
