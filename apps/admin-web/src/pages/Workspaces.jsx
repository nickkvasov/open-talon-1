import React, { useEffect, useState } from 'react';
import { 
  FolderKanban, 
  FolderTree,
  AlertTriangle, 
  Users, 
  Edit2, 
  Trash2, 
  Plus, 
  X, 
  ShieldCheck, 
  Save,
  ChevronRight,
  Info,
  Settings2
} from 'lucide-react';
import { useApi } from '../api/useApi';
import ConfirmationModal from '../components/Common/ConfirmationModal';
import { buildAdminActor } from '../config/adminActor';
import { buildProjectMutation, buildWorkspaceMutation } from '../lib/adminForms';

export default function Workspaces() {
  const api = useApi();
  const [organizations, setOrganizations] = useState([]);
  const [selectedOrganizationId, setSelectedOrganizationId] = useState('');
  const [projects, setProjects] = useState([]);
  const [selectedProjectId, setSelectedProjectId] = useState('');
  const [workspaces, setWorkspaces] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  // Detail Modal specific states
  const [selectedWorkspace, setSelectedWorkspace] = useState(null);
  const [editingRoleName, setEditingRoleName] = useState('');
  const [draftRoleName, setDraftRoleName] = useState('');
  const [editingRoleDef, setEditingRoleDef] = useState('');
  
  // Workspace Edit Modal
  const [isEditModalOpen, setIsEditModalOpen] = useState(false);
  const [isProjectModalOpen, setIsProjectModalOpen] = useState(false);
  const [modalMode, setModalMode] = useState('create');
  const [projectFormData, setProjectFormData] = useState({
    slug: '',
    name: '',
    description: '',
    owner_user_id: '',
    owner_system_agent_id: '',
    editor_user_ids: '',
    editor_system_agent_ids: '',
    viewer_user_ids: '',
    viewer_system_agent_ids: '',
    metadata: '{}',
  });
  const [workspaceFormData, setWorkspaceFormData] = useState({
    name: '',
    description: '',
    project_id: '',
    metadata: '{}',
    harness_summary: '',
    methodology_ontology: '',
    methodology_axiology: '',
    methodology_epistemology: '',
    methodology_principles: '[]',
    methodics: '[]',
    execution_rules: '[]',
    moderation_enabled: true,
    moderation_level: 'balanced',
    moderation_topic: '',
    moderation_allowed_adjacent_topics: '[]',
    moderation_blocked_topics: '[]',
    moderation_explain_blocked_messages: true,
  });

  const [confirmModal, setConfirmModal] = useState({ 
    isOpen: false, 
    title: '', 
    message: '', 
    onConfirm: () => {} 
  });

  const fetchWorkspaces = async () => {
    try {
      setLoading(true);
      const params = {};
      if (selectedOrganizationId) params.organization_id = selectedOrganizationId;
      if (selectedProjectId) params.project_id = selectedProjectId;
      const res = await api.get('/v1/workspaces', {
        params,
      });
      setWorkspaces(res.data);
      setError(null);
    } catch (err) {
      setError(err.message || 'Failed to fetch workspaces');
    } finally {
      setLoading(false);
    }
  };

  const fetchProjects = async () => {
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

  useEffect(() => {
    const load = async () => {
      try {
        const res = await api.get('/v1/organizations');
        setOrganizations(res.data);
        if (!selectedOrganizationId && res.data.length === 1) {
          setSelectedOrganizationId(res.data[0].organization_id);
        }
      } catch (err) {
        setError(err.message || 'Failed to fetch organizations');
      }
    };
    load();
  }, [api, selectedOrganizationId]);

  useEffect(() => {
    fetchWorkspaces();
  }, [api, selectedOrganizationId, selectedProjectId]);

  useEffect(() => {
    fetchProjects();
  }, [api, selectedOrganizationId]);

  const resetForm = () => {
    setWorkspaceFormData({
      name: '',
      description: '',
      project_id: selectedProjectId || projects.find((project) => project.slug === 'default')?.project_id || projects[0]?.project_id || '',
      metadata: '{}',
      harness_summary: '',
      methodology_ontology: '',
      methodology_axiology: '',
      methodology_epistemology: '',
      methodology_principles: '[]',
      methodics: '[]',
      execution_rules: '[]',
      moderation_enabled: true,
      moderation_level: 'balanced',
      moderation_topic: '',
      moderation_allowed_adjacent_topics: '[]',
      moderation_blocked_topics: '[]',
      moderation_explain_blocked_messages: true,
    });
    setModalMode('create');
  };

  const handleOpenCreate = () => {
    resetForm();
    setIsEditModalOpen(true);
  };

  const handleOpenEdit = (ws, e) => {
    e.stopPropagation();
    setModalMode('edit');
    setSelectedWorkspace(ws);
    setWorkspaceFormData({
      name: ws.name,
      description: ws.description || '',
      project_id: ws.project_id || '',
      metadata: JSON.stringify(ws.metadata || {}, null, 2),
      harness_summary: ws.harness?.summary || '',
      methodology_ontology: ws.harness?.methodology?.ontology || '',
      methodology_axiology: ws.harness?.methodology?.axiology || '',
      methodology_epistemology: ws.harness?.methodology?.epistemology || '',
      methodology_principles: JSON.stringify(ws.harness?.methodology?.principles || [], null, 2),
      methodics: JSON.stringify(ws.harness?.methodics || [], null, 2),
      execution_rules: JSON.stringify(ws.harness?.execution_rules || [], null, 2),
      moderation_enabled: ws.harness?.moderation_policy?.enabled ?? true,
      moderation_level: ws.harness?.moderation_policy?.level || 'balanced',
      moderation_topic: ws.harness?.moderation_policy?.topic || '',
      moderation_allowed_adjacent_topics: JSON.stringify(ws.harness?.moderation_policy?.allowed_adjacent_topics || [], null, 2),
      moderation_blocked_topics: JSON.stringify(ws.harness?.moderation_policy?.blocked_topics || [], null, 2),
      moderation_explain_blocked_messages: ws.harness?.moderation_policy?.explain_blocked_messages ?? true,
    });
    setIsEditModalOpen(true);
  };

  const handleOpenWorkspace = async (workspace) => {
    setDraftRoleName('');
    try {
      const res = await api.get(`/v1/workspaces/${workspace.workspace_id}`);
      setSelectedWorkspace(res.data);
    } catch {
      setSelectedWorkspace(workspace);
    }
  };

  const handleDeleteWorkspace = async (workspace_id, e) => {
    if (e) {
      e.preventDefault();
      e.stopPropagation();
    }
    
    setConfirmModal({
      isOpen: true,
      title: 'Delete Workspace?',
      message: 'Are you sure you want to delete this workspace? All threads and participants will be lost. This action is irreversible.',
      onConfirm: async () => {
        try {
          await api.delete(`/v1/workspaces/${workspace_id}`, {
            data: {
              actor: buildAdminActor()
            }
          });
          fetchWorkspaces();
        } catch (err) {
          alert('Failed to delete workspace: ' + err.message);
        }
      }
    });
  };

  const handleSaveWorkspace = async (e) => {
    e.preventDefault();
    try {
      const payload = buildWorkspaceMutation({
        actor: buildAdminActor(),
        organizationId: selectedOrganizationId,
        projectId: workspaceFormData.project_id || selectedProjectId,
        formData: workspaceFormData,
        modalMode,
      });

      if (modalMode === 'create') {
        await api.post('/v1/workspaces', payload);
      } else {
        await api.patch(`/v1/workspaces/${selectedWorkspace.workspace_id}`, payload);
      }
      
      setIsEditModalOpen(false);
      fetchWorkspaces();
    } catch (err) {
      alert('Failed to save workspace: ' + err.message);
    }
  };

  const handleOpenProjectCreate = () => {
    setProjectFormData({
      slug: '',
      name: '',
      description: '',
      owner_user_id: '',
      owner_system_agent_id: '',
      editor_user_ids: '',
      editor_system_agent_ids: '',
      viewer_user_ids: '',
      viewer_system_agent_ids: '',
      metadata: '{}',
    });
    setIsProjectModalOpen(true);
  };

  const handleSaveProject = async (e) => {
    e.preventDefault();
    if (!selectedOrganizationId) {
      alert('Select an organization before creating a project.');
      return;
    }
    try {
      const payload = buildProjectMutation({
        actor: buildAdminActor(),
        formData: projectFormData,
      });
      const res = await api.post(`/v1/organizations/${selectedOrganizationId}/projects`, payload);
      setSelectedProjectId(res.data.project_id);
      setIsProjectModalOpen(false);
      fetchProjects();
    } catch (err) {
      alert('Failed to save project: ' + err.message);
    }
  };

  const handleSaveRole = async (workspaceId, roleName) => {
    try {
      await api.put(`/v1/workspaces/${workspaceId}/roles/${roleName}`, {
        actor: buildAdminActor(),
        name: roleName,
        definition: editingRoleDef
      });
      setEditingRoleName('');
      setDraftRoleName('');
      setEditingRoleDef('');
      const updatedWs = await api.get(`/v1/workspaces/${workspaceId}`);
      setSelectedWorkspace(updatedWs.data);
      fetchWorkspaces();
    } catch (err) {
      alert('Failed to update role: ' + err.message);
    }
  };

  const handleDeleteRole = async (workspaceId, roleName, e) => {
    if (e) {
      e.preventDefault();
      e.stopPropagation();
    }
    
    setConfirmModal({
      isOpen: true,
      title: 'Delete Role Override?',
      message: `Are you sure you want to delete the role override for "${roleName}"? This will revert this role to system defaults in this workspace.`,
      onConfirm: async () => {
        try {
          await api.delete(`/v1/workspaces/${workspaceId}/roles/${roleName}`, {
            data: {
              actor: buildAdminActor()
            }
          });
          const updatedWs = await api.get(`/v1/workspaces/${workspaceId}`);
          setSelectedWorkspace(updatedWs.data);
          fetchWorkspaces();
        } catch (err) {
          alert('Failed to delete role: ' + err.message);
        }
      }
    });
  };

  const selectedWorkspaceRecord = selectedWorkspace?.workspace || selectedWorkspace;
  const selectedWorkspaceId = selectedWorkspaceRecord?.workspace_id || '';
  const selectedProject = projects.find((project) => project.project_id === selectedProjectId);
  const projectById = Object.fromEntries(projects.map((project) => [project.project_id, project]));
  const selectedRoleDefinitions = Array.isArray(selectedWorkspace?.role_definitions)
    ? Object.fromEntries(
        selectedWorkspace.role_definitions.map((roleDefinition) => [
          roleDefinition.name,
          roleDefinition,
        ])
      )
    : (selectedWorkspace?.metadata?.role_definitions || {});
  const selectedParticipantCount = selectedWorkspaceRecord?.participant_count
    ?? selectedWorkspace?.participants?.length
    ?? 0;

  if (loading) return <div className="p-8 text-slate-500">Loading workspaces...</div>;

  return (
    <div className="p-8 space-y-6">
      <div className="flex justify-between items-center bg-white dark:bg-slate-800 p-6 rounded-xl border border-slate-200 dark:border-slate-700 shadow-sm">
        <div>
          <h1 className="text-2xl font-bold text-slate-900 dark:text-white flex items-center">
            <FolderKanban className="w-6 h-6 mr-3 text-blue-500" />
            Workspace Fleet
          </h1>
          <p className="text-slate-500 mt-1">Orchestrate collaboration boundaries and role policies</p>
        </div>
        <div className="flex items-center gap-3">
          <select
            value={selectedOrganizationId}
            onChange={(e) => {
              setSelectedOrganizationId(e.target.value);
              setSelectedProjectId('');
            }}
            className="rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 px-3 py-2 text-sm"
          >
            <option value="">All Organizations</option>
            {organizations.map((organization) => (
              <option key={organization.organization_id} value={organization.organization_id}>
                {organization.name}
              </option>
            ))}
          </select>
          <select
            value={selectedProjectId}
            onChange={(e) => setSelectedProjectId(e.target.value)}
            disabled={!selectedOrganizationId}
            className="rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 px-3 py-2 text-sm disabled:opacity-50"
          >
            <option value="">All Projects</option>
            {projects.map((project) => (
              <option key={project.project_id} value={project.project_id}>
                {project.name}
              </option>
            ))}
          </select>
          <button
            type="button"
            onClick={handleOpenProjectCreate}
            disabled={!selectedOrganizationId}
            className="border border-slate-200 dark:border-slate-700 text-slate-700 dark:text-slate-200 px-3 py-2 rounded-lg flex items-center gap-2 text-sm font-medium disabled:opacity-50"
          >
            <FolderTree className="w-4 h-4" />
            Project
          </button>
          <button 
            onClick={handleOpenCreate}
            className="bg-blue-600 hover:bg-blue-700 text-white px-4 py-2 rounded-lg flex items-center transition-all shadow-lg shadow-blue-500/20 font-medium"
          >
            <Plus className="w-5 h-5 mr-2" />
            Create Workspace
          </button>
        </div>
      </div>
      
      {error && (
        <div className="bg-rose-50 dark:bg-rose-900/20 text-rose-600 dark:text-rose-400 p-4 rounded-lg flex items-center border border-rose-200 dark:border-rose-800">
          <AlertTriangle className="w-5 h-5 mr-3" />
          {error}
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
        {workspaces.map(ws => (
          <div 
            key={ws.workspace_id} 
            onClick={() => { void handleOpenWorkspace(ws); }}
            className="group bg-white dark:bg-slate-800 rounded-xl p-6 flex flex-col border border-slate-200 dark:border-slate-700 hover:border-blue-500 dark:hover:border-blue-500 transition-all cursor-pointer shadow-sm relative"
          >
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-3">
                <div className="p-2 bg-blue-50 dark:bg-blue-900/30 text-blue-600 dark:text-blue-400 rounded-lg">
                  <FolderKanban className="w-5 h-5" />
                </div>
                <h2 className="text-lg font-bold text-slate-900 dark:text-white truncate" title={ws.name}>{ws.name}</h2>
              </div>
              <div className="flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                <button 
                  onClick={(e) => handleOpenEdit(ws, e)}
                  className="p-1.5 text-slate-400 hover:text-blue-500 hover:bg-blue-50 dark:hover:bg-blue-900/30 rounded-md"
                >
                  <Edit2 className="w-3.5 h-3.5" />
                </button>
                <button 
                  type="button"
                  onClick={(e) => handleDeleteWorkspace(ws.workspace_id, e)}
                  className="p-1.5 text-slate-400 hover:text-rose-500 hover:bg-rose-50 dark:hover:bg-rose-900/30 rounded-md"
                >
                  <Trash2 className="w-3.5 h-3.5" />
                </button>
              </div>
            </div>
            
            <p className="text-sm text-slate-500 dark:text-slate-400 mb-6 line-clamp-2 min-h-[40px]">
              {ws.description || 'No description provided for this cluster.'}
            </p>
            <div className="mb-4 flex items-center gap-2 text-xs font-semibold text-slate-500 dark:text-slate-400">
              <FolderTree className="w-3.5 h-3.5" />
              {projectById[ws.project_id]?.name || selectedProject?.name || 'Project'}
            </div>
            
            <div className="flex items-center justify-between mt-auto pt-4 border-t border-slate-100 dark:border-slate-700/50">
              <div className="flex items-center gap-2">
                <span className="text-[10px] font-mono text-slate-400 bg-slate-50 dark:bg-slate-900 px-2 py-0.5 rounded border border-slate-100 dark:border-slate-800">
                  {ws.workspace_id.slice(0, 8)}
                </span>
              </div>
              <div className="flex items-center gap-2 text-slate-500 dark:text-slate-400 text-xs font-semibold">
                <Users className="w-3.5 h-3.5" />
                {ws.participant_count || 0}
              </div>
            </div>
          </div>
        ))}
        
        <button 
          onClick={handleOpenCreate}
          className="border-2 border-dashed border-slate-200 dark:border-slate-700 rounded-xl p-8 flex flex-col items-center justify-center text-slate-400 hover:text-blue-500 hover:border-blue-300 dark:hover:border-blue-700 transition-all hover:bg-blue-50/30 dark:hover:bg-blue-900/10 min-h-[200px]"
        >
          <div className="p-3 bg-slate-100 dark:bg-slate-800 rounded-full mb-3 group-hover:bg-blue-100 transition-colors">
            <Plus className="w-6 h-6" />
          </div>
          <span className="font-medium text-sm">Provision New Workspace</span>
        </button>
      </div>

      {isProjectModalOpen && (
        <div className="fixed inset-0 z-[60] flex items-center justify-center p-4 bg-slate-900/60 transition-opacity animate-in fade-in duration-200">
          <div className="bg-white dark:bg-slate-800 w-full max-w-2xl max-h-[90vh] rounded-2xl shadow-2xl border border-slate-200 dark:border-slate-700 animate-in zoom-in-95 duration-200 flex flex-col overflow-hidden">
            <div className="p-6 border-b border-slate-100 dark:border-slate-700 flex justify-between items-center">
              <div>
                <h2 className="text-xl font-bold text-slate-900 dark:text-white flex items-center">
                  <FolderTree className="w-5 h-5 mr-3 text-blue-500" />
                  Create Project
                </h2>
              </div>
              <button onClick={() => setIsProjectModalOpen(false)} className="p-2 text-slate-400 hover:text-slate-600 rounded-full">
                <X className="w-5 h-5" />
              </button>
            </div>
            <form onSubmit={handleSaveProject} className="p-6 space-y-5 overflow-y-auto">
              <div>
                <label className="block text-sm font-semibold text-slate-700 dark:text-slate-300 mb-1.5">Project Name</label>
                <input
                  required
                  type="text"
                  value={projectFormData.name}
                  onChange={e => setProjectFormData({...projectFormData, name: e.target.value})}
                  className="w-full bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-lg px-4 py-2.5 focus:ring-2 focus:ring-blue-500 outline-none transition-all text-slate-900 dark:text-white"
                />
              </div>
              <div>
                <label className="block text-sm font-semibold text-slate-700 dark:text-slate-300 mb-1.5">Slug</label>
                <input
                  required
                  type="text"
                  value={projectFormData.slug}
                  onChange={e => setProjectFormData({...projectFormData, slug: e.target.value})}
                  className="w-full bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-lg px-4 py-2.5 focus:ring-2 focus:ring-blue-500 outline-none transition-all text-slate-900 dark:text-white"
                />
              </div>
              <div>
                <label className="block text-sm font-semibold text-slate-700 dark:text-slate-300 mb-1.5">Description</label>
                <textarea
                  value={projectFormData.description}
                  onChange={e => setProjectFormData({...projectFormData, description: e.target.value})}
                  rows={3}
                  className="w-full bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-lg px-4 py-2.5 focus:ring-2 focus:ring-blue-500 outline-none transition-all text-slate-900 dark:text-white resize-none"
                />
              </div>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-semibold text-slate-700 dark:text-slate-300 mb-1.5">Owner User IDs</label>
                  <input
                    type="text"
                    value={projectFormData.owner_user_id}
                    onChange={e => setProjectFormData({...projectFormData, owner_user_id: e.target.value})}
                    className="w-full bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-lg px-4 py-2.5 focus:ring-2 focus:ring-blue-500 outline-none transition-all text-slate-900 dark:text-white"
                  />
                </div>
                <div>
                  <label className="block text-sm font-semibold text-slate-700 dark:text-slate-300 mb-1.5">Owner Agent IDs</label>
                  <input
                    type="text"
                    value={projectFormData.owner_system_agent_id}
                    onChange={e => setProjectFormData({...projectFormData, owner_system_agent_id: e.target.value})}
                    className="w-full bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-lg px-4 py-2.5 focus:ring-2 focus:ring-blue-500 outline-none transition-all text-slate-900 dark:text-white"
                  />
                </div>
                <div>
                  <label className="block text-sm font-semibold text-slate-700 dark:text-slate-300 mb-1.5">Editor User IDs</label>
                  <input
                    type="text"
                    value={projectFormData.editor_user_ids}
                    onChange={e => setProjectFormData({...projectFormData, editor_user_ids: e.target.value})}
                    className="w-full bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-lg px-4 py-2.5 focus:ring-2 focus:ring-blue-500 outline-none transition-all text-slate-900 dark:text-white"
                  />
                </div>
                <div>
                  <label className="block text-sm font-semibold text-slate-700 dark:text-slate-300 mb-1.5">Editor Agent IDs</label>
                  <input
                    type="text"
                    value={projectFormData.editor_system_agent_ids}
                    onChange={e => setProjectFormData({...projectFormData, editor_system_agent_ids: e.target.value})}
                    className="w-full bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-lg px-4 py-2.5 focus:ring-2 focus:ring-blue-500 outline-none transition-all text-slate-900 dark:text-white"
                  />
                </div>
                <div>
                  <label className="block text-sm font-semibold text-slate-700 dark:text-slate-300 mb-1.5">Viewer User IDs</label>
                  <input
                    type="text"
                    value={projectFormData.viewer_user_ids}
                    onChange={e => setProjectFormData({...projectFormData, viewer_user_ids: e.target.value})}
                    className="w-full bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-lg px-4 py-2.5 focus:ring-2 focus:ring-blue-500 outline-none transition-all text-slate-900 dark:text-white"
                  />
                </div>
                <div>
                  <label className="block text-sm font-semibold text-slate-700 dark:text-slate-300 mb-1.5">Viewer Agent IDs</label>
                  <input
                    type="text"
                    value={projectFormData.viewer_system_agent_ids}
                    onChange={e => setProjectFormData({...projectFormData, viewer_system_agent_ids: e.target.value})}
                    className="w-full bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-lg px-4 py-2.5 focus:ring-2 focus:ring-blue-500 outline-none transition-all text-slate-900 dark:text-white"
                  />
                </div>
              </div>
              <div>
                <label className="block text-sm font-semibold text-slate-700 dark:text-slate-300 mb-1.5 font-mono">Metadata (JSON)</label>
                <textarea
                  value={projectFormData.metadata}
                  onChange={e => setProjectFormData({...projectFormData, metadata: e.target.value})}
                  rows={4}
                  className="w-full bg-slate-900 dark:bg-black border border-slate-700 rounded-lg px-4 py-3 font-mono text-xs text-blue-400 focus:ring-2 focus:ring-blue-500 outline-none resize-none shadow-inner"
                />
              </div>
              <div className="flex justify-end gap-3 pt-2">
                <button type="button" onClick={() => setIsProjectModalOpen(false)} className="px-4 py-2 rounded-lg border border-slate-200 dark:border-slate-700 text-slate-600 dark:text-slate-300">
                  Cancel
                </button>
                <button type="submit" className="px-4 py-2 rounded-lg bg-blue-600 hover:bg-blue-700 text-white font-semibold flex items-center gap-2">
                  <Save className="w-4 h-4" />
                  Save
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Workspace Create/Edit Modal */}
      {isEditModalOpen && (
        <div className="fixed inset-0 z-[60] flex items-center justify-center p-4 bg-slate-900/60 transition-opacity animate-in fade-in duration-200">
          <div className="bg-white dark:bg-slate-800 w-full max-w-2xl max-h-[90vh] rounded-2xl shadow-2xl border border-slate-200 dark:border-slate-700 animate-in zoom-in-95 duration-200 flex flex-col overflow-hidden">
            <div className="p-6 border-b border-slate-100 dark:border-slate-700 flex justify-between items-center shrink-0">
              <div>
                <h2 className="text-xl font-bold text-slate-900 dark:text-white flex items-center">
                  <FolderKanban className="w-5 h-5 mr-3 text-blue-500" />
                  {modalMode === 'edit' ? 'Update Workspace' : 'Create Workspace'}
                </h2>
                <p className="text-slate-500 text-sm mt-1">Configure global boundaries and cluster metadata</p>
              </div>
              <button onClick={() => setIsEditModalOpen(false)} className="p-2 text-slate-400 hover:text-slate-600 rounded-full">
                <X className="w-5 h-5" />
              </button>
            </div>
            
            <form onSubmit={handleSaveWorkspace} className="flex min-h-0 flex-1 flex-col">
              <div className="flex-1 overflow-y-auto p-8 space-y-6">
                {modalMode === 'create' && (
                  <div>
                    <label className="block text-sm font-semibold text-slate-700 dark:text-slate-300 mb-1.5">Project</label>
                    <select
                      value={workspaceFormData.project_id}
                      onChange={e => setWorkspaceFormData({...workspaceFormData, project_id: e.target.value})}
                      className="w-full bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-lg px-4 py-2.5 focus:ring-2 focus:ring-blue-500 outline-none transition-all text-slate-900 dark:text-white"
                    >
                      {projects.map((project) => (
                        <option key={project.project_id} value={project.project_id}>
                          {project.name}
                        </option>
                      ))}
                    </select>
                  </div>
                )}
                <div>
                  <label className="block text-sm font-semibold text-slate-700 dark:text-slate-300 mb-1.5">Workspace Name</label>
                  <input
                    required
                    type="text"
                    value={workspaceFormData.name}
                    onChange={e => setWorkspaceFormData({...workspaceFormData, name: e.target.value})}
                    className="w-full bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-lg px-4 py-2.5 focus:ring-2 focus:ring-blue-500 outline-none transition-all text-slate-900 dark:text-white"
                    placeholder="e.g. Project Talon Core"
                  />
                </div>
                <div>
                  <label className="block text-sm font-semibold text-slate-700 dark:text-slate-300 mb-1.5">Description</label>
                  <textarea
                    value={workspaceFormData.description}
                    onChange={e => setWorkspaceFormData({...workspaceFormData, description: e.target.value})}
                    rows={3}
                    className="w-full bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-lg px-4 py-2.5 focus:ring-2 focus:ring-blue-500 outline-none transition-all text-slate-900 dark:text-white resize-none"
                    placeholder="What is the scope of this workspace?"
                  />
                </div>
                <div>
                  <label className="block text-sm font-semibold text-slate-700 dark:text-slate-300 mb-1.5 font-mono">Metadata (JSON)</label>
                  <textarea
                    value={workspaceFormData.metadata}
                    onChange={e => setWorkspaceFormData({...workspaceFormData, metadata: e.target.value})}
                    rows={6}
                    className="w-full bg-slate-900 dark:bg-black border border-slate-700 rounded-lg px-4 py-3 font-mono text-xs text-blue-400 focus:ring-2 focus:ring-blue-500 outline-none resize-none shadow-inner"
                    placeholder="{}"
                  />
                </div>
                <div className="space-y-6 rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900/40 p-5">
                  <div>
                    <h3 className="text-sm font-bold text-slate-900 dark:text-white">Workspace Harness</h3>
                    <p className="mt-1 text-xs text-slate-500">Methodology, methodics, and execution rules for this workspace.</p>
                  </div>
                  <div>
                    <label className="block text-sm font-semibold text-slate-700 dark:text-slate-300 mb-1.5">Harness Summary</label>
                    <textarea
                      value={workspaceFormData.harness_summary}
                      onChange={e => setWorkspaceFormData({...workspaceFormData, harness_summary: e.target.value})}
                      rows={2}
                      className="w-full bg-white dark:bg-slate-950 border border-slate-200 dark:border-slate-700 rounded-lg px-4 py-2.5 focus:ring-2 focus:ring-blue-500 outline-none transition-all text-slate-900 dark:text-white resize-none"
                      placeholder="High-level execution posture for this workspace..."
                    />
                  </div>
                  <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                    <label className="flex items-center gap-3 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-950 px-4 py-3 text-sm font-semibold text-slate-700 dark:text-slate-300">
                      <input
                        type="checkbox"
                        checked={workspaceFormData.moderation_enabled}
                        onChange={e => setWorkspaceFormData({...workspaceFormData, moderation_enabled: e.target.checked})}
                        className="h-4 w-4 rounded border-slate-300 text-blue-600 focus:ring-blue-500"
                      />
                      Topic Review
                    </label>
                    <div>
                      <label className="block text-sm font-semibold text-slate-700 dark:text-slate-300 mb-1.5">Review Level</label>
                      <select
                        value={workspaceFormData.moderation_level}
                        onChange={e => setWorkspaceFormData({...workspaceFormData, moderation_level: e.target.value})}
                        className="w-full bg-white dark:bg-slate-950 border border-slate-200 dark:border-slate-700 rounded-lg px-4 py-2.5 focus:ring-2 focus:ring-blue-500 outline-none text-slate-900 dark:text-white"
                      >
                        <option value="strict">Strict</option>
                        <option value="balanced">Balanced</option>
                        <option value="open">Open</option>
                      </select>
                    </div>
                    <label className="flex items-center gap-3 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-950 px-4 py-3 text-sm font-semibold text-slate-700 dark:text-slate-300">
                      <input
                        type="checkbox"
                        checked={workspaceFormData.moderation_explain_blocked_messages}
                        onChange={e => setWorkspaceFormData({...workspaceFormData, moderation_explain_blocked_messages: e.target.checked})}
                        className="h-4 w-4 rounded border-slate-300 text-blue-600 focus:ring-blue-500"
                      />
                      Explain Blocks
                    </label>
                  </div>
                  <div>
                    <label className="block text-sm font-semibold text-slate-700 dark:text-slate-300 mb-1.5">Topic</label>
                    <textarea
                      value={workspaceFormData.moderation_topic}
                      onChange={e => setWorkspaceFormData({...workspaceFormData, moderation_topic: e.target.value})}
                      rows={2}
                      className="w-full bg-white dark:bg-slate-950 border border-slate-200 dark:border-slate-700 rounded-lg px-4 py-2.5 focus:ring-2 focus:ring-blue-500 outline-none transition-all text-slate-900 dark:text-white resize-none"
                    />
                  </div>
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <div>
                      <label className="block text-sm font-semibold text-slate-700 dark:text-slate-300 mb-1.5 font-mono">Adjacent Topics (JSON array)</label>
                      <textarea
                        value={workspaceFormData.moderation_allowed_adjacent_topics}
                        onChange={e => setWorkspaceFormData({...workspaceFormData, moderation_allowed_adjacent_topics: e.target.value})}
                        rows={4}
                        className="w-full bg-slate-950 border border-slate-800 rounded-lg px-4 py-3 font-mono text-xs text-cyan-300 focus:ring-2 focus:ring-blue-500 outline-none resize-none"
                      />
                    </div>
                    <div>
                      <label className="block text-sm font-semibold text-slate-700 dark:text-slate-300 mb-1.5 font-mono">Blocked Topics (JSON array)</label>
                      <textarea
                        value={workspaceFormData.moderation_blocked_topics}
                        onChange={e => setWorkspaceFormData({...workspaceFormData, moderation_blocked_topics: e.target.value})}
                        rows={4}
                        className="w-full bg-slate-950 border border-slate-800 rounded-lg px-4 py-3 font-mono text-xs text-cyan-300 focus:ring-2 focus:ring-blue-500 outline-none resize-none"
                      />
                    </div>
                  </div>
                  <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                    <div>
                      <label className="block text-sm font-semibold text-slate-700 dark:text-slate-300 mb-1.5">Ontology</label>
                      <textarea
                        value={workspaceFormData.methodology_ontology}
                        onChange={e => setWorkspaceFormData({...workspaceFormData, methodology_ontology: e.target.value})}
                        rows={4}
                        className="w-full bg-white dark:bg-slate-950 border border-slate-200 dark:border-slate-700 rounded-lg px-4 py-2.5 focus:ring-2 focus:ring-blue-500 outline-none transition-all text-slate-900 dark:text-white resize-none"
                      />
                    </div>
                    <div>
                      <label className="block text-sm font-semibold text-slate-700 dark:text-slate-300 mb-1.5">Axiology</label>
                      <textarea
                        value={workspaceFormData.methodology_axiology}
                        onChange={e => setWorkspaceFormData({...workspaceFormData, methodology_axiology: e.target.value})}
                        rows={4}
                        className="w-full bg-white dark:bg-slate-950 border border-slate-200 dark:border-slate-700 rounded-lg px-4 py-2.5 focus:ring-2 focus:ring-blue-500 outline-none transition-all text-slate-900 dark:text-white resize-none"
                      />
                    </div>
                    <div>
                      <label className="block text-sm font-semibold text-slate-700 dark:text-slate-300 mb-1.5">Epistemology</label>
                      <textarea
                        value={workspaceFormData.methodology_epistemology}
                        onChange={e => setWorkspaceFormData({...workspaceFormData, methodology_epistemology: e.target.value})}
                        rows={4}
                        className="w-full bg-white dark:bg-slate-950 border border-slate-200 dark:border-slate-700 rounded-lg px-4 py-2.5 focus:ring-2 focus:ring-blue-500 outline-none transition-all text-slate-900 dark:text-white resize-none"
                      />
                    </div>
                  </div>
                  <div>
                    <label className="block text-sm font-semibold text-slate-700 dark:text-slate-300 mb-1.5 font-mono">Methodology Principles (JSON array)</label>
                    <textarea
                      value={workspaceFormData.methodology_principles}
                      onChange={e => setWorkspaceFormData({...workspaceFormData, methodology_principles: e.target.value})}
                      rows={4}
                      className="w-full bg-slate-950 border border-slate-800 rounded-lg px-4 py-3 font-mono text-xs text-cyan-300 focus:ring-2 focus:ring-blue-500 outline-none resize-none"
                    />
                  </div>
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <div>
                      <label className="block text-sm font-semibold text-slate-700 dark:text-slate-300 mb-1.5 font-mono">Methodics (JSON array)</label>
                      <textarea
                        value={workspaceFormData.methodics}
                        onChange={e => setWorkspaceFormData({...workspaceFormData, methodics: e.target.value})}
                        rows={8}
                        className="w-full bg-slate-950 border border-slate-800 rounded-lg px-4 py-3 font-mono text-xs text-cyan-300 focus:ring-2 focus:ring-blue-500 outline-none resize-none"
                      />
                    </div>
                    <div>
                      <label className="block text-sm font-semibold text-slate-700 dark:text-slate-300 mb-1.5 font-mono">Execution Rules (JSON array)</label>
                      <textarea
                        value={workspaceFormData.execution_rules}
                        onChange={e => setWorkspaceFormData({...workspaceFormData, execution_rules: e.target.value})}
                        rows={8}
                        className="w-full bg-slate-950 border border-slate-800 rounded-lg px-4 py-3 font-mono text-xs text-cyan-300 focus:ring-2 focus:ring-blue-500 outline-none resize-none"
                      />
                    </div>
                  </div>
                </div>
              </div>
              
              <div className="flex justify-end space-x-4 border-t border-slate-100 dark:border-slate-700 bg-white dark:bg-slate-800 px-8 py-4 shrink-0">
                <button type="button" onClick={() => setIsEditModalOpen(false)} className="px-6 py-2.5 text-slate-500 font-semibold hover:text-slate-800 transition-colors">Cancel</button>
                <button type="submit" className="px-10 py-2.5 bg-blue-600 hover:bg-blue-700 text-white rounded-lg font-bold shadow-lg shadow-blue-500/20 transition-all">
                  {modalMode === 'edit' ? 'Update' : 'Create'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Workspace Detail Modal (Roles & Config) */}
      {selectedWorkspaceRecord && !isEditModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/70 transition-opacity animate-in fade-in duration-200">
          <div className="bg-white dark:bg-slate-900 w-full max-w-5xl rounded-2xl shadow-2xl border border-slate-200 dark:border-slate-700 flex flex-col overflow-hidden max-h-[90vh] animate-in slide-in-from-bottom-4 duration-300">
            <div className="p-6 border-b border-slate-100 dark:border-slate-800 flex justify-between items-center bg-slate-50 dark:bg-slate-900/50 backdrop-blur-md">
              <div className="flex items-center gap-4">
                <div className="p-3 bg-blue-600 text-white rounded-xl shadow-lg shadow-blue-500/20">
                  <FolderKanban className="w-6 h-6" />
                </div>
                <div>
                  <h3 className="text-xl font-extrabold text-slate-900 dark:text-white leading-tight">{selectedWorkspaceRecord.name}</h3>
                  <div className="flex items-center gap-2 mt-1">
                    <span className="text-[11px] font-mono text-blue-500 bg-blue-50 dark:bg-blue-900/30 px-2 py-0.5 rounded border border-blue-100 dark:border-blue-900">{selectedWorkspaceRecord.workspace_id}</span>
                  </div>
                </div>
              </div>
              <button 
                className="p-2 text-slate-400 hover:text-rose-500 hover:bg-rose-50 dark:hover:bg-rose-900/30 rounded-full transition-all" 
                onClick={() => {
                  setSelectedWorkspace(null);
                  setEditingRoleName('');
                  setDraftRoleName('');
                }}
              >
                <X className="w-6 h-6" />
              </button>
            </div>

            <div className="flex-1 overflow-y-auto p-8 bg-white dark:bg-slate-950 space-y-10">
              <section>
                <div className="flex items-center gap-2 mb-4">
                  <Info className="w-4 h-4 text-slate-400" />
                  <h4 className="text-xs font-bold text-slate-400 uppercase tracking-widest">Workspace Context</h4>
                </div>
                <div className="grid grid-cols-3 gap-6">
                  <div className="p-5 bg-slate-50 dark:bg-slate-900 border border-slate-100 dark:border-slate-800 rounded-2xl">
                    <span className="text-[10px] font-bold text-slate-400 uppercase tracking-tighter">Capacity</span>
                    <div className="text-2xl font-black text-slate-900 dark:text-white mt-1">{selectedParticipantCount}</div>
                    <span className="text-xs text-slate-500">Active Participants</span>
                  </div>
                  <div className="p-5 bg-slate-50 dark:bg-slate-900 border border-slate-100 dark:border-slate-800 rounded-2xl col-span-2">
                    <span className="text-[10px] font-bold text-slate-400 uppercase tracking-tighter">Manifest</span>
                    <p className="text-sm text-slate-700 dark:text-slate-300 mt-2 font-medium leading-relaxed">
                      {selectedWorkspaceRecord.description || 'No declarative description provided for this cluster execution boundary.'}
                    </p>
                  </div>
                </div>
                <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mt-6">
                  <div className="p-5 bg-slate-50 dark:bg-slate-900 border border-slate-100 dark:border-slate-800 rounded-2xl">
                    <span className="text-[10px] font-bold text-slate-400 uppercase tracking-tighter">Topic Review</span>
                    <div className="text-lg font-black text-slate-900 dark:text-white mt-1">
                      {selectedWorkspaceRecord.harness?.moderation_policy?.enabled === false ? 'Off' : 'On'}
                    </div>
                    <span className="text-xs text-slate-500">
                      {selectedWorkspaceRecord.harness?.moderation_policy?.level || 'balanced'}
                    </span>
                  </div>
                  <div className="p-5 bg-slate-50 dark:bg-slate-900 border border-slate-100 dark:border-slate-800 rounded-2xl md:col-span-2">
                    <span className="text-[10px] font-bold text-slate-400 uppercase tracking-tighter">Topic Boundary</span>
                    <p className="text-sm text-slate-700 dark:text-slate-300 mt-2 font-medium leading-relaxed">
                      {selectedWorkspaceRecord.harness?.moderation_policy?.topic || selectedWorkspaceRecord.name}
                    </p>
                  </div>
                </div>
              </section>

              <section>
                <div className="flex items-center justify-between mb-6">
                  <div className="flex items-center gap-2">
                    <ShieldCheck className="w-4 h-4 text-emerald-500" />
                    <h4 className="text-xs font-bold text-slate-400 uppercase tracking-widest">Role Governance</h4>
                  </div>
                  <button 
                    onClick={() => {
                      setDraftRoleName('');
                      setEditingRoleName('new_role');
                      setEditingRoleDef('');
                    }}
                    className="text-xs font-bold text-blue-600 dark:text-blue-400 hover:underline flex items-center gap-1"
                  >
                    <Plus className="w-3 h-3" /> Add Role Override
                  </button>
                </div>

                <div className="grid grid-cols-1 gap-4">
                  {Object.entries(selectedRoleDefinitions).map(([roleKey, roleObj]) => (
                    <div key={roleKey} className="group flex flex-col border border-slate-200 dark:border-slate-800 rounded-2xl overflow-hidden bg-white dark:bg-slate-900 shadow-sm transition-all hover:shadow-md hover:border-slate-300 dark:hover:border-slate-700">
                      <div className="flex justify-between items-center px-5 py-3 border-b border-slate-100 dark:border-slate-800 bg-slate-50/50 dark:bg-slate-900/50">
                        <div className="flex items-center gap-3">
                          <code className="text-xs font-bold text-emerald-600 dark:text-emerald-400 bg-emerald-50 dark:bg-emerald-900/30 px-2 py-0.5 rounded">{roleKey}</code>
                          <span className="text-[10px] text-slate-400">Policy Map</span>
                        </div>
                        <div className="flex gap-2">
                          <button 
                            onClick={() => { setEditingRoleName(roleKey); setEditingRoleDef(roleObj.definition || ''); }}
                            className="p-1.5 text-slate-400 hover:text-blue-500 transition-colors"
                          >
                            <Edit2 className="w-4 h-4" />
                          </button>
                          <button 
                            type="button"
                            onClick={(e) => handleDeleteRole(selectedWorkspaceId, roleKey, e)}
                            className="p-1.5 text-slate-400 hover:text-rose-500 transition-colors"
                          >
                            <Trash2 className="w-4 h-4" />
                          </button>
                        </div>
                      </div>
                      <div className="p-5 overflow-x-auto">
                        <pre className="text-xs font-mono text-slate-600 dark:text-slate-400 leading-relaxed max-h-40 overflow-y-auto scrollbar-thin">
                          {roleObj.definition || 'Inheriting system default capabilities.'}
                        </pre>
                      </div>
                    </div>
                  ))}
                  
                  {editingRoleName && (
                    <div className="border-2 border-blue-500/30 rounded-2xl p-6 bg-blue-50/10 dark:bg-blue-900/10 space-y-4 animate-in fade-in slide-in-from-top-2 duration-200">
                      <div className="flex justify-between items-center">
                        <div className="flex items-center gap-2">
                          <Settings2 className="w-4 h-4 text-blue-500" />
                          <h5 className="text-sm font-bold text-slate-800 dark:text-slate-200">
                            {editingRoleName === 'new_role' ? 'Define New Role Scope' : `Editing Scope: ${editingRoleName}`}
                          </h5>
                        </div>
                        <button
                          onClick={() => {
                            setEditingRoleName('');
                            setDraftRoleName('');
                          }}
                          className="text-slate-400 hover:text-slate-600"
                        >
                          <X className="w-4 h-4"/>
                        </button>
                      </div>
                      {editingRoleName === 'new_role' && (
                        <input 
                          type="text" 
                          value={draftRoleName}
                          placeholder="Unique Role Identifier (e.g. lead_developer)"
                          className="w-full bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-lg px-4 py-2 text-sm font-mono focus:ring-2 focus:ring-blue-500 outline-none"
                          onChange={e => setDraftRoleName(e.target.value)}
                        />
                      )}
                      <textarea
                        value={editingRoleDef}
                        placeholder="Natural language definition or system policy rules..."
                        onChange={e => setEditingRoleDef(e.target.value)}
                        className="w-full text-sm p-4 bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-xl focus:ring-2 focus:ring-blue-500 outline-none font-serif leading-relaxed"
                        rows={6}
                      />
                      <div className="flex justify-end gap-3">
                        <button
                          onClick={() => {
                            setEditingRoleName('');
                            setDraftRoleName('');
                          }}
                          className="px-5 py-2 text-sm font-semibold text-slate-500"
                        >
                          Cancel
                        </button>
                        <button 
                          onClick={() => handleSaveRole(
                            selectedWorkspaceId,
                            editingRoleName === 'new_role' ? draftRoleName : editingRoleName,
                          )}
                          disabled={editingRoleName === 'new_role' && !draftRoleName.trim()}
                          className="px-8 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg font-bold shadow-lg shadow-blue-500/20 flex items-center gap-2"
                        >
                          <Save className="w-4 h-4" /> Commit Definition
                        </button>
                      </div>
                    </div>
                  )}
                  
                  {Object.keys(selectedRoleDefinitions).length === 0 && !editingRoleName && (
                      <div className="flex flex-col items-center justify-center p-12 border-2 border-dashed border-slate-100 dark:border-slate-800 rounded-3xl text-center space-y-3">
                        <div className="p-3 bg-slate-50 dark:bg-slate-900 rounded-full text-slate-300">
                          <ShieldCheck className="w-8 h-8" />
                        </div>
                        <p className="text-sm text-slate-400 font-medium">Using canonical role templates.<br/>No workspace-specific overrides active.</p>
                      </div>
                  )}
                </div>
              </section>
            </div>
            
            <div className={`p-4 transition-all duration-500 flex items-center justify-center gap-3 ${selectedWorkspace ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-4'}`}>
               <span className="w-2 h-2 rounded-full bg-emerald-500 shadow-[0_0_8px_rgba(16,185,129,0.5)]"></span>
               <span className="text-[10px] font-black tracking-[0.2em] text-slate-300 uppercase">System Ready & Synchronized</span>
            </div>
          </div>
        </div>
      )}

      <ConfirmationModal 
        isOpen={confirmModal.isOpen}
        onClose={() => setConfirmModal({ ...confirmModal, isOpen: false })}
        onConfirm={confirmModal.onConfirm}
        title={confirmModal.title}
        message={confirmModal.message}
      />

    </div>
  );
}
