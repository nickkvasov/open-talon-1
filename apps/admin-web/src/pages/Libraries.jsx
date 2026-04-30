import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  AlertTriangle,
  BookOpen,
  Database,
  Download,
  FileText,
  FolderKanban,
  FolderTree,
  Link2,
  Plus,
  RefreshCw,
  Upload,
} from 'lucide-react';
import { useApi } from '../api/useApi';
import { buildAdminActor } from '../config/adminActor';
import {
  buildLibraryIndexPayload,
  buildLibraryMutation,
  buildLibraryTextItemPayload,
} from '../lib/adminForms';

const blankLibraryForm = {
  slug: '',
  name: '',
  description: '',
  metadata: '{}',
};

const blankTextItemForm = {
  title: '',
  content: '',
  item_kind: 'text',
  logical_name: '',
  source_uri: '',
  content_type: 'text/markdown',
  metadata: '{}',
};

function libraryEndpoint(scope, { organizationId, projectId, workspaceId }) {
  if (scope === 'project') {
    return `/v1/organizations/${organizationId}/projects/${projectId}/libraries`;
  }
  if (scope === 'workspace') {
    return `/v1/workspaces/${workspaceId}/libraries`;
  }
  return `/v1/organizations/${organizationId}/libraries`;
}

function scopeReady(scope, { organizationId, projectId, workspaceId }) {
  if (scope === 'project') {
    return Boolean(organizationId && projectId);
  }
  if (scope === 'workspace') {
    return Boolean(workspaceId);
  }
  return Boolean(organizationId);
}

function shortId(value) {
  return value ? value.slice(0, 8) : '';
}

export default function Libraries() {
  const api = useApi();
  const [organizations, setOrganizations] = useState([]);
  const [projects, setProjects] = useState([]);
  const [workspaces, setWorkspaces] = useState([]);
  const [selectedOrganizationId, setSelectedOrganizationId] = useState('');
  const [selectedProjectId, setSelectedProjectId] = useState('');
  const [selectedWorkspaceId, setSelectedWorkspaceId] = useState('');
  const [scope, setScope] = useState('organization');
  const [libraries, setLibraries] = useState([]);
  const [selectedLibrary, setSelectedLibrary] = useState(null);
  const [items, setItems] = useState([]);
  const [libraryForm, setLibraryForm] = useState(blankLibraryForm);
  const [textItemForm, setTextItemForm] = useState(blankTextItemForm);
  const [uploadFile, setUploadFile] = useState(null);
  const [uploadTitle, setUploadTitle] = useState('');
  const [attachWorkspaceId, setAttachWorkspaceId] = useState('');
  const [ingestionJobs, setIngestionJobs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const scopeContext = useMemo(() => ({
    organizationId: selectedOrganizationId,
    projectId: selectedProjectId,
    workspaceId: selectedWorkspaceId,
  }), [selectedOrganizationId, selectedProjectId, selectedWorkspaceId]);
  const canLoadLibraries = scopeReady(scope, scopeContext);
  const selectedLibraryId = selectedLibrary?.library_id || '';
  const selectedLibraryCanAttach = selectedLibrary
    && (selectedLibrary.scope === 'organization' || selectedLibrary.scope === 'project');

  const fetchLibraries = useCallback(async () => {
    if (!canLoadLibraries) {
      setLibraries([]);
      setSelectedLibrary(null);
      return;
    }
    try {
      const res = await api.get(libraryEndpoint(scope, scopeContext));
      setLibraries(res.data);
      setSelectedLibrary((current) => (
        res.data.find((library) => library.library_id === current?.library_id) || res.data[0] || null
      ));
      setError(null);
    } catch (err) {
      setError(err.message || 'Failed to fetch libraries');
    }
  }, [api, canLoadLibraries, scope, scopeContext]);

  const fetchItems = useCallback(async (libraryId) => {
    if (!libraryId) {
      setItems([]);
      return;
    }
    try {
      const res = await api.get(`/v1/libraries/${libraryId}/items`);
      setItems(res.data);
    } catch (err) {
      setError(err.message || 'Failed to fetch library items');
    }
  }, [api]);

  useEffect(() => {
    const loadOrganizations = async () => {
      try {
        setLoading(true);
        const res = await api.get('/v1/organizations');
        setOrganizations(res.data);
        if (!selectedOrganizationId && res.data.length === 1) {
          setSelectedOrganizationId(res.data[0].organization_id);
        }
      } catch (err) {
        setError(err.message || 'Failed to fetch organizations');
      } finally {
        setLoading(false);
      }
    };
    void loadOrganizations();
  }, [api, selectedOrganizationId]);

  useEffect(() => {
    const loadProjects = async () => {
      if (!selectedOrganizationId) {
        setProjects([]);
        setSelectedProjectId('');
        return;
      }
      try {
        const res = await api.get(`/v1/organizations/${selectedOrganizationId}/projects`);
        setProjects(res.data);
        setSelectedProjectId((current) => (
          res.data.some((project) => project.project_id === current) ? current : ''
        ));
      } catch (err) {
        setError(err.message || 'Failed to fetch projects');
      }
    };
    void loadProjects();
  }, [api, selectedOrganizationId]);

  useEffect(() => {
    const loadWorkspaces = async () => {
      const params = {};
      if (selectedOrganizationId) params.organization_id = selectedOrganizationId;
      if (selectedProjectId) params.project_id = selectedProjectId;
      try {
        const res = await api.get('/v1/workspaces', { params });
        setWorkspaces(res.data);
        setSelectedWorkspaceId((current) => (
          res.data.some((workspace) => workspace.workspace_id === current) ? current : ''
        ));
        setAttachWorkspaceId((current) => (
          res.data.some((workspace) => workspace.workspace_id === current) ? current : ''
        ));
      } catch (err) {
        setError(err.message || 'Failed to fetch workspaces');
      }
    };
    void loadWorkspaces();
  }, [api, selectedOrganizationId, selectedProjectId]);

  useEffect(() => {
    void fetchLibraries();
  }, [fetchLibraries]);

  useEffect(() => {
    void fetchItems(selectedLibraryId);
  }, [fetchItems, selectedLibraryId]);

  const handleCreateLibrary = async (event) => {
    event.preventDefault();
    if (!canLoadLibraries) return;
    try {
      const res = await api.post(
        libraryEndpoint(scope, scopeContext),
        buildLibraryMutation(buildAdminActor(), libraryForm),
      );
      setLibraryForm(blankLibraryForm);
      await fetchLibraries();
      setSelectedLibrary(res.data);
    } catch (err) {
      alert('Failed to create library: ' + err.message);
    }
  };

  const handleCreateTextItem = async (event) => {
    event.preventDefault();
    if (!selectedLibraryId) return;
    try {
      await api.post(
        `/v1/libraries/${selectedLibraryId}/items/text`,
        buildLibraryTextItemPayload(buildAdminActor(), textItemForm),
      );
      setTextItemForm(blankTextItemForm);
      await fetchItems(selectedLibraryId);
    } catch (err) {
      alert('Failed to add text item: ' + err.message);
    }
  };

  const handleUploadItem = async (event) => {
    event.preventDefault();
    if (!selectedLibraryId || !uploadFile) return;
    try {
      const formData = new FormData();
      formData.append('file', uploadFile);
      formData.append('title', uploadTitle.trim() || uploadFile.name);
      formData.append('item_kind', 'file');
      formData.append('actor_display_name', 'admin-web');
      await api.post(`/v1/libraries/${selectedLibraryId}/items/upload`, formData);
      setUploadFile(null);
      setUploadTitle('');
      event.target.reset();
      await fetchItems(selectedLibraryId);
    } catch (err) {
      alert('Failed to upload item: ' + err.message);
    }
  };

  const handleDownload = async (itemId) => {
    try {
      const res = await api.get(`/v1/library-items/${itemId}/download`);
      window.open(res.data.url, '_blank', 'noopener,noreferrer');
    } catch (err) {
      alert('Failed to create download URL: ' + err.message);
    }
  };

  const handleAttach = async () => {
    if (!selectedLibraryId || !attachWorkspaceId) return;
    try {
      await api.put(
        `/v1/workspaces/${attachWorkspaceId}/library-attachments/${selectedLibraryId}`,
        { actor: buildAdminActor(), enabled: true, metadata: {} },
      );
      await fetchLibraries();
    } catch (err) {
      alert('Failed to attach library: ' + err.message);
    }
  };

  const handleIndex = async () => {
    if (!selectedLibraryId) return;
    try {
      const res = await api.post(
        `/v1/libraries/${selectedLibraryId}/index`,
        buildLibraryIndexPayload(buildAdminActor()),
      );
      setIngestionJobs(res.data);
    } catch (err) {
      alert('Failed to index library: ' + err.message);
    }
  };

  if (loading) {
    return <div className="p-8 text-slate-500">Loading libraries...</div>;
  }

  return (
    <div className="p-8 space-y-6">
      <div className="flex flex-col gap-4 bg-white dark:bg-slate-800 p-6 rounded-xl border border-slate-200 dark:border-slate-700 shadow-sm lg:flex-row lg:items-center lg:justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-900 dark:text-white flex items-center">
            <BookOpen className="w-6 h-6 mr-3 text-blue-500" />
            Libraries
          </h1>
          <p className="text-slate-500 mt-1">Durable reference stores and retriever indexing</p>
        </div>
        <div className="flex flex-wrap gap-3">
          <select
            value={selectedOrganizationId}
            onChange={(event) => {
              setSelectedOrganizationId(event.target.value);
              setSelectedProjectId('');
              setSelectedWorkspaceId('');
            }}
            className="rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 px-3 py-2 text-sm"
          >
            <option value="">Organization</option>
            {organizations.map((organization) => (
              <option key={organization.organization_id} value={organization.organization_id}>
                {organization.name}
              </option>
            ))}
          </select>
          <select
            value={selectedProjectId}
            onChange={(event) => setSelectedProjectId(event.target.value)}
            disabled={!selectedOrganizationId}
            className="rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 px-3 py-2 text-sm disabled:opacity-50"
          >
            <option value="">Project</option>
            {projects.map((project) => (
              <option key={project.project_id} value={project.project_id}>
                {project.name}
              </option>
            ))}
          </select>
          <select
            value={selectedWorkspaceId}
            onChange={(event) => setSelectedWorkspaceId(event.target.value)}
            className="rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 px-3 py-2 text-sm"
          >
            <option value="">Workspace</option>
            {workspaces.map((workspace) => (
              <option key={workspace.workspace_id} value={workspace.workspace_id}>
                {workspace.name}
              </option>
            ))}
          </select>
          <select
            value={scope}
            onChange={(event) => setScope(event.target.value)}
            className="rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 px-3 py-2 text-sm"
          >
            <option value="organization">Organization Libraries</option>
            <option value="project">Project Libraries</option>
            <option value="workspace">Workspace Libraries</option>
          </select>
        </div>
      </div>

      {error && (
        <div className="bg-rose-50 dark:bg-rose-900/20 text-rose-600 dark:text-rose-400 p-4 rounded-lg flex items-center border border-rose-200 dark:border-rose-800">
          <AlertTriangle className="w-5 h-5 mr-3" />
          {error}
        </div>
      )}

      <div className="grid grid-cols-1 xl:grid-cols-[minmax(320px,420px)_1fr] gap-6">
        <section className="space-y-6">
          <form onSubmit={handleCreateLibrary} className="bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 p-6 space-y-4 shadow-sm">
            <div className="flex items-center gap-2">
              <Plus className="w-4 h-4 text-blue-500" />
              <h2 className="text-sm font-bold uppercase tracking-widest text-slate-400">Create Library</h2>
            </div>
            <div>
              <label className="block text-sm font-semibold text-slate-700 dark:text-slate-300 mb-1.5">Name</label>
              <input
                required
                value={libraryForm.name}
                onChange={(event) => setLibraryForm({ ...libraryForm, name: event.target.value })}
                className="w-full rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900 px-4 py-2.5 text-sm outline-none focus:ring-2 focus:ring-blue-500"
              />
            </div>
            <div>
              <label className="block text-sm font-semibold text-slate-700 dark:text-slate-300 mb-1.5">Slug</label>
              <input
                value={libraryForm.slug}
                onChange={(event) => setLibraryForm({ ...libraryForm, slug: event.target.value })}
                className="w-full rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900 px-4 py-2.5 text-sm font-mono outline-none focus:ring-2 focus:ring-blue-500"
              />
            </div>
            <div>
              <label className="block text-sm font-semibold text-slate-700 dark:text-slate-300 mb-1.5">Description</label>
              <textarea
                value={libraryForm.description}
                onChange={(event) => setLibraryForm({ ...libraryForm, description: event.target.value })}
                rows={3}
                className="w-full rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900 px-4 py-2.5 text-sm outline-none resize-none focus:ring-2 focus:ring-blue-500"
              />
            </div>
            <div>
              <label className="block text-sm font-semibold text-slate-700 dark:text-slate-300 mb-1.5 font-mono">Metadata</label>
              <textarea
                value={libraryForm.metadata}
                onChange={(event) => setLibraryForm({ ...libraryForm, metadata: event.target.value })}
                rows={3}
                className="w-full rounded-lg border border-slate-700 bg-slate-950 px-4 py-3 text-xs text-cyan-300 font-mono outline-none resize-none focus:ring-2 focus:ring-blue-500"
              />
            </div>
            <button
              type="submit"
              disabled={!canLoadLibraries}
              className="w-full rounded-lg bg-blue-600 hover:bg-blue-700 text-white px-4 py-2.5 text-sm font-bold shadow-lg shadow-blue-500/20 disabled:opacity-50"
            >
              Create
            </button>
          </form>

          <section className="bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 p-4 shadow-sm">
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-2">
                <Database className="w-4 h-4 text-slate-400" />
                <h2 className="text-sm font-bold uppercase tracking-widest text-slate-400">Library Set</h2>
              </div>
              <button
                type="button"
                onClick={() => void fetchLibraries()}
                className="p-2 rounded-lg text-slate-400 hover:text-blue-500 hover:bg-blue-50 dark:hover:bg-blue-900/30"
                title="Refresh libraries"
              >
                <RefreshCw className="w-4 h-4" />
              </button>
            </div>
            <div className="space-y-3">
              {libraries.map((library) => (
                <button
                  type="button"
                  key={library.library_id}
                  onClick={() => setSelectedLibrary(library)}
                  className={`w-full rounded-lg border p-4 text-left transition-all ${
                    selectedLibraryId === library.library_id
                      ? 'border-blue-500 bg-blue-50 dark:bg-blue-900/20'
                      : 'border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900 hover:border-slate-300 dark:hover:border-slate-600'
                  }`}
                >
                  <div className="flex items-center justify-between gap-3">
                    <span className="font-bold text-slate-900 dark:text-white truncate">{library.name}</span>
                    <span className="text-[10px] font-black uppercase text-slate-400">{library.scope}</span>
                  </div>
                  <div className="mt-1 flex items-center gap-2 text-xs text-slate-500">
                    {library.scope === 'workspace' ? <FolderKanban className="w-3.5 h-3.5" /> : <FolderTree className="w-3.5 h-3.5" />}
                    <code>{library.slug}</code>
                    <span>{shortId(library.library_id)}</span>
                  </div>
                </button>
              ))}
              {libraries.length === 0 && (
                <div className="rounded-lg border border-dashed border-slate-200 dark:border-slate-700 p-8 text-center text-sm text-slate-400">
                  No libraries in this scope.
                </div>
              )}
            </div>
          </section>
        </section>

        <section className="space-y-6">
          <div className="bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 p-6 shadow-sm">
            <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
              <div>
                <h2 className="text-xl font-black text-slate-900 dark:text-white">
                  {selectedLibrary?.name || 'Select a library'}
                </h2>
                {selectedLibrary && (
                  <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-slate-500">
                    <span className="rounded border border-slate-200 dark:border-slate-700 px-2 py-1 font-mono">{selectedLibrary.slug}</span>
                    <span className="rounded border border-slate-200 dark:border-slate-700 px-2 py-1">{selectedLibrary.status}</span>
                    <span className="rounded border border-slate-200 dark:border-slate-700 px-2 py-1">{items.length} items</span>
                  </div>
                )}
              </div>
              <div className="flex flex-wrap gap-3">
                <button
                  type="button"
                  onClick={handleIndex}
                  disabled={!selectedLibraryId}
                  className="rounded-lg bg-emerald-600 hover:bg-emerald-700 text-white px-4 py-2 text-sm font-bold flex items-center gap-2 disabled:opacity-50"
                >
                  <Database className="w-4 h-4" />
                  Index
                </button>
                <select
                  value={attachWorkspaceId}
                  onChange={(event) => setAttachWorkspaceId(event.target.value)}
                  className="rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 px-3 py-2 text-sm"
                >
                  <option value="">Attach target</option>
                  {workspaces.map((workspace) => (
                    <option key={workspace.workspace_id} value={workspace.workspace_id}>
                      {workspace.name}
                    </option>
                  ))}
                </select>
                <button
                  type="button"
                  onClick={handleAttach}
                  disabled={!selectedLibraryCanAttach || !attachWorkspaceId}
                  className="rounded-lg border border-slate-200 dark:border-slate-700 text-slate-700 dark:text-slate-200 px-4 py-2 text-sm font-bold flex items-center gap-2 disabled:opacity-50"
                >
                  <Link2 className="w-4 h-4" />
                  Attach
                </button>
              </div>
            </div>
            {ingestionJobs.length > 0 && (
              <div className="mt-5 rounded-lg border border-emerald-200 dark:border-emerald-900 bg-emerald-50 dark:bg-emerald-900/20 p-4 text-sm text-emerald-700 dark:text-emerald-300">
                Queued {ingestionJobs.length} ingestion jobs.
              </div>
            )}
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <form onSubmit={handleCreateTextItem} className="bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 p-6 space-y-4 shadow-sm">
              <div className="flex items-center gap-2">
                <FileText className="w-4 h-4 text-blue-500" />
                <h3 className="text-sm font-bold uppercase tracking-widest text-slate-400">Text Item</h3>
              </div>
              <input
                required
                placeholder="Title"
                value={textItemForm.title}
                onChange={(event) => setTextItemForm({ ...textItemForm, title: event.target.value })}
                className="w-full rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900 px-4 py-2.5 text-sm outline-none focus:ring-2 focus:ring-blue-500"
              />
              <textarea
                required
                placeholder="Markdown or text"
                value={textItemForm.content}
                onChange={(event) => setTextItemForm({ ...textItemForm, content: event.target.value })}
                rows={6}
                className="w-full rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900 px-4 py-2.5 text-sm outline-none resize-none focus:ring-2 focus:ring-blue-500"
              />
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                <input
                  placeholder="Logical name"
                  value={textItemForm.logical_name}
                  onChange={(event) => setTextItemForm({ ...textItemForm, logical_name: event.target.value })}
                  className="rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900 px-4 py-2.5 text-sm outline-none focus:ring-2 focus:ring-blue-500"
                />
                <input
                  placeholder="Source URI"
                  value={textItemForm.source_uri}
                  onChange={(event) => setTextItemForm({ ...textItemForm, source_uri: event.target.value })}
                  className="rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900 px-4 py-2.5 text-sm outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>
              <button
                type="submit"
                disabled={!selectedLibraryId}
                className="w-full rounded-lg bg-blue-600 hover:bg-blue-700 text-white px-4 py-2.5 text-sm font-bold disabled:opacity-50"
              >
                Add Text
              </button>
            </form>

            <form onSubmit={handleUploadItem} className="bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 p-6 space-y-4 shadow-sm">
              <div className="flex items-center gap-2">
                <Upload className="w-4 h-4 text-blue-500" />
                <h3 className="text-sm font-bold uppercase tracking-widest text-slate-400">File Upload</h3>
              </div>
              <input
                type="file"
                onChange={(event) => setUploadFile(event.target.files?.[0] || null)}
                className="w-full rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900 px-4 py-2.5 text-sm"
              />
              <input
                placeholder="Title"
                value={uploadTitle}
                onChange={(event) => setUploadTitle(event.target.value)}
                className="w-full rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900 px-4 py-2.5 text-sm outline-none focus:ring-2 focus:ring-blue-500"
              />
              <button
                type="submit"
                disabled={!selectedLibraryId || !uploadFile}
                className="w-full rounded-lg bg-blue-600 hover:bg-blue-700 text-white px-4 py-2.5 text-sm font-bold disabled:opacity-50"
              >
                Upload
              </button>
            </form>
          </div>

          <section className="bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 p-6 shadow-sm">
            <div className="flex items-center justify-between mb-5">
              <div className="flex items-center gap-2">
                <FileText className="w-4 h-4 text-slate-400" />
                <h3 className="text-sm font-bold uppercase tracking-widest text-slate-400">Items</h3>
              </div>
              <button
                type="button"
                onClick={() => void fetchItems(selectedLibraryId)}
                disabled={!selectedLibraryId}
                className="p-2 rounded-lg text-slate-400 hover:text-blue-500 hover:bg-blue-50 dark:hover:bg-blue-900/30 disabled:opacity-50"
                title="Refresh items"
              >
                <RefreshCw className="w-4 h-4" />
              </button>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {items.map((item) => (
                <div key={item.item_id} className="rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900 p-4">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <h4 className="font-bold text-slate-900 dark:text-white truncate">{item.title}</h4>
                      <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-slate-500">
                        <span>{item.item_kind}</span>
                        <span>{item.content_type || 'application/octet-stream'}</span>
                        <span>{shortId(item.item_id)}</span>
                      </div>
                    </div>
                    <button
                      type="button"
                      onClick={() => void handleDownload(item.item_id)}
                      className="p-2 rounded-lg text-slate-400 hover:text-blue-500 hover:bg-blue-50 dark:hover:bg-blue-900/30"
                      title="Download item"
                    >
                      <Download className="w-4 h-4" />
                    </button>
                  </div>
                </div>
              ))}
              {items.length === 0 && (
                <div className="md:col-span-2 rounded-lg border border-dashed border-slate-200 dark:border-slate-700 p-8 text-center text-sm text-slate-400">
                  No items in this library.
                </div>
              )}
            </div>
          </section>
        </section>
      </div>
    </div>
  );
}
