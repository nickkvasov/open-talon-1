import React, { useState, useEffect } from 'react';
import {
  Plus, 
  Server, 
  Database, 
  Activity, 
  Trash2, 
  Edit2, 
  CheckCircle2, 
  AlertCircle,
  X,
  Search,
  Settings2
} from 'lucide-react';
import ConfirmationModal from '../components/Common/ConfirmationModal';
import { useApi } from '../api/useApi';
import { buildAdminActor } from '../config/adminActor';

export default function Providers() {
  const api = useApi();
  const [llmProviders, setLlmProviders] = useState([]);
  const [memoryProviders, setMemoryProviders] = useState([]);
  const [organizations, setOrganizations] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [activeTab, setActiveTab] = useState('llm');
  const [scopeMode, setScopeMode] = useState('global');
  const [selectedOrganizationId, setSelectedOrganizationId] = useState('');

  const [isModalOpen, setIsModalOpen] = useState(false);
  const [modalMode, setModalMode] = useState('create');
  const [editingProvider, setEditingProvider] = useState(null);

  const [llmFormData, setLlmFormData] = useState({
    engine_id: '',
    display_name: '',
    description: '',
    provider: 'openai',
    endpoint_kind: 'remote',
    url: '',
    default_model: '',
    capabilities: '',
    locality: 'cloud',
    priority: 100,
    enabled: true,
    secret_config: '{}',
    metadata: '{}'
  });

  const [memoryFormData, setMemoryFormData] = useState({
    provider_key: '',
    display_name: '',
    description: '',
    provider: 'postgres',
    enabled: true,
    config: '{}',
    secret_config: '{}',
    metadata: '{}'
  });

  const [confirmModal, setConfirmModal] = useState({ 
    isOpen: false, 
    title: '', 
    message: '', 
    onConfirm: () => {} 
  });

  const selectedOrganization = organizations.find(
    (organization) => organization.organization_id === selectedOrganizationId
  ) || null;

  const fetchOrganizations = async () => {
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

  const fetchData = async () => {
    try {
      setLoading(true);
      if (scopeMode === 'organization' && !selectedOrganizationId) {
        setLlmProviders([]);
        setMemoryProviders([]);
        setError(null);
        return;
      }
      const llmEndpoint =
        scopeMode === 'organization'
          ? `/v1/organizations/${selectedOrganizationId}/llm-providers`
          : '/v1/llm-providers';
      const memoryEndpoint =
        scopeMode === 'organization'
          ? `/v1/organizations/${selectedOrganizationId}/memory-providers`
          : '/v1/memory-providers';
      const [llmRes, memRes] = await Promise.all([
        api.get(llmEndpoint),
        api.get(memoryEndpoint),
      ]);

      setLlmProviders(llmRes.data);
      setMemoryProviders(memRes.data);
      setError(null);
    } catch (err) {
      setError(err.message || 'Failed to fetch providers');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void fetchOrganizations();
  }, [api]);

  useEffect(() => {
    if (scopeMode === 'organization' && !selectedOrganizationId && organizations.length === 1) {
      setSelectedOrganizationId(organizations[0].organization_id);
    }
  }, [organizations, scopeMode, selectedOrganizationId]);

  useEffect(() => {
    void fetchData();
  }, [api, scopeMode, selectedOrganizationId]);

  const resetForms = () => {
    setLlmFormData({
      engine_id: '',
      display_name: '',
      description: '',
      provider: 'openai',
      endpoint_kind: 'remote',
      url: '',
      default_model: '',
      capabilities: '',
      locality: 'cloud',
      priority: 100,
      enabled: true,
      secret_config: '{}',
      metadata: '{}'
    });
    setMemoryFormData({
      provider_key: '',
      display_name: '',
      description: '',
      provider: 'postgres',
      enabled: true,
      config: '{}',
      secret_config: '{}',
      metadata: '{}'
    });
    setEditingProvider(null);
    setModalMode('create');
  };

  const handleOpenCreateModal = () => {
    if (scopeMode === 'organization' && !selectedOrganizationId) {
      alert('Select an organization before creating an org-scoped provider.');
      return;
    }
    resetForms();
    setIsModalOpen(true);
  };

  const handleOpenEditModal = (provider) => {
    setEditingProvider(provider);
    setModalMode('edit');
    if (activeTab === 'llm') {
      setLlmFormData({
        engine_id: provider.engine_id,
        display_name: provider.display_name,
        description: provider.description,
        provider: provider.provider,
        endpoint_kind: provider.endpoint_kind,
        url: provider.url || '',
        default_model: provider.default_model || '',
        capabilities: provider.capabilities.join(', '),
        locality: provider.locality,
        priority: provider.priority,
        enabled: provider.enabled,
        secret_config: JSON.stringify(provider.secret_config, null, 2),
        metadata: JSON.stringify(provider.metadata, null, 2)
      });
    } else {
      setMemoryFormData({
        provider_key: provider.provider_key,
        display_name: provider.display_name,
        description: provider.description,
        provider: provider.provider,
        enabled: provider.enabled,
        config: JSON.stringify(provider.config, null, 2),
        secret_config: JSON.stringify(provider.secret_config, null, 2),
        metadata: JSON.stringify(provider.metadata, null, 2)
      });
    }
    setIsModalOpen(true);
  };

  const handleDeleteProvider = async (id, e) => {
    if (e) {
      e.preventDefault();
      e.stopPropagation();
    }
    
    setConfirmModal({
      isOpen: true,
      title: 'Delete Provider?',
      message: 'Are you sure you want to delete this infrastructure provider? System components relaying on this backend will be affected.',
      onConfirm: async () => {
        try {
          const endpoint = activeTab === 'llm' ? `llm-providers/${id}` : `memory-providers/${id}`;
          await api.delete(`/v1/${endpoint}`, {
            data: {
              actor: buildAdminActor()
            }
          });

          await fetchData();
        } catch (err) {
          alert('Failed to delete provider: ' + err.message);
        }
      }
    });
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    try {
      let payload;
      let endpoint;
      let method;

      if (activeTab === 'llm') {
        payload = {
          actor: buildAdminActor(),
          engine_id: llmFormData.engine_id,
          display_name: llmFormData.display_name,
          description: llmFormData.description,
          provider: llmFormData.provider,
          endpoint_kind: llmFormData.endpoint_kind,
          url: llmFormData.url || null,
          default_model: llmFormData.default_model || null,
          capabilities: llmFormData.capabilities.split(',').map(s => s.trim()).filter(Boolean),
          locality: llmFormData.locality,
          priority: parseInt(llmFormData.priority),
          enabled: llmFormData.enabled,
          secret_config: JSON.parse(llmFormData.secret_config || '{}'),
          metadata: JSON.parse(llmFormData.metadata || '{}')
        };
        endpoint = modalMode === 'edit'
          ? `llm-providers/${editingProvider.provider_id}`
          : scopeMode === 'organization'
            ? `organizations/${selectedOrganizationId}/llm-providers`
            : 'llm-providers';
        method = modalMode === 'edit' ? 'PATCH' : 'POST';
      } else {
        payload = {
          actor: buildAdminActor(),
          provider_key: memoryFormData.provider_key,
          display_name: memoryFormData.display_name,
          description: memoryFormData.description,
          provider: memoryFormData.provider,
          enabled: memoryFormData.enabled,
          config: JSON.parse(memoryFormData.config || '{}'),
          secret_config: JSON.parse(memoryFormData.secret_config || '{}'),
          metadata: JSON.parse(memoryFormData.metadata || '{}')
        };
        endpoint = modalMode === 'edit'
          ? `memory-providers/${editingProvider.provider_id}`
          : scopeMode === 'organization'
            ? `organizations/${selectedOrganizationId}/memory-providers`
            : 'memory-providers';
        method = modalMode === 'edit' ? 'PATCH' : 'POST';
      }

      await api.request({
        url: `/v1/${endpoint}`,
        method,
        data: payload,
      });

      setIsModalOpen(false);
      await fetchData();
    } catch (err) {
      alert(err.message);
    }
  };

  const handleHealthCheck = async (id) => {
    try {
      const endpoint = activeTab === 'llm' ? `llm-providers/${id}/health-check` : `memory-providers/${id}/health-check`;
      const { data: report } = await api.post(`/v1/${endpoint}`);

      alert(`Provider Status: ${report.status}\n\n${report.checks.map(c => `- ${c.name}: ${c.status} (${c.detail})`).join('\n')}`);
    } catch (err) {
      alert('Health check failed: ' + err.message);
    }
  };

  if (loading) return <div className="p-8 text-slate-500">Loading providers...</div>;

  return (
    <div className="p-8 max-w-7xl mx-auto space-y-6">
      <div className="flex justify-between items-center bg-white dark:bg-slate-800 p-6 rounded-xl border border-slate-200 dark:border-slate-700 shadow-sm">
        <div>
          <h1 className="text-2xl font-bold text-slate-900 dark:text-white flex items-center">
            <Server className="w-6 h-6 mr-3 text-blue-500" />
            Infrastructure Providers
          </h1>
          <p className="text-slate-500 mt-1">
            Manage {scopeMode === 'organization' ? 'organization-scoped' : 'platform-global'} LLM and Memory backend integrations
          </p>
        </div>
        <div className="flex items-center gap-3">
          <div className="flex space-x-1 bg-slate-100 dark:bg-slate-800/50 p-1 rounded-xl border border-slate-200 dark:border-slate-700">
            <button
              onClick={() => setScopeMode('global')}
              className={`px-3 py-2 rounded-lg text-sm font-medium transition-all ${scopeMode === 'global' ? 'bg-white dark:bg-slate-700 text-blue-600 dark:text-blue-400 shadow-sm' : 'text-slate-500 hover:text-slate-700 dark:hover:text-slate-300'}`}
            >
              Platform Global
            </button>
            <button
              onClick={() => setScopeMode('organization')}
              className={`px-3 py-2 rounded-lg text-sm font-medium transition-all ${scopeMode === 'organization' ? 'bg-white dark:bg-slate-700 text-blue-600 dark:text-blue-400 shadow-sm' : 'text-slate-500 hover:text-slate-700 dark:hover:text-slate-300'}`}
            >
              Organization
            </button>
          </div>
          {scopeMode === 'organization' && (
            <select
              value={selectedOrganizationId}
              onChange={(e) => setSelectedOrganizationId(e.target.value)}
              className="rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 px-3 py-2 text-sm"
            >
              <option value="">Select organization</option>
              {organizations.map((organization) => (
                <option key={organization.organization_id} value={organization.organization_id}>
                  {organization.name}
                </option>
              ))}
            </select>
          )}
          <button 
            onClick={handleOpenCreateModal}
            className="bg-blue-600 hover:bg-blue-700 text-white px-4 py-2 rounded-lg flex items-center transition-all shadow-lg shadow-blue-500/20 font-medium"
          >
            <Plus className="w-5 h-5 mr-2" />
            Add Provider
          </button>
        </div>
      </div>

      {error && (
        <div className="bg-rose-50 dark:bg-rose-900/20 text-rose-600 dark:text-rose-400 p-4 rounded-lg flex items-center border border-rose-200 dark:border-rose-800">
          <AlertCircle className="w-5 h-5 mr-3" />
          {error}
        </div>
      )}

      <div className="flex space-x-1 bg-slate-100 dark:bg-slate-800/50 p-1 rounded-xl w-fit border border-slate-200 dark:border-slate-700">
        <button
          onClick={() => setActiveTab('llm')}
          className={`flex items-center px-4 py-2 rounded-lg transition-all ${activeTab === 'llm' ? 'bg-white dark:bg-slate-700 text-blue-600 dark:text-blue-400 shadow-sm' : 'text-slate-500 hover:text-slate-700 dark:hover:text-slate-300'}`}
        >
          <Activity className="w-4 h-4 mr-2" />
          LLM Providers
        </button>
        <button
          onClick={() => setActiveTab('memory')}
          className={`flex items-center px-4 py-2 rounded-lg transition-all ${activeTab === 'memory' ? 'bg-white dark:bg-slate-700 text-blue-600 dark:text-blue-400 shadow-sm' : 'text-slate-500 hover:text-slate-700 dark:hover:text-slate-300'}`}
        >
          <Database className="w-4 h-4 mr-2" />
          Memory Providers
        </button>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
        {(activeTab === 'llm' ? llmProviders : memoryProviders).map((p) => (
          <div key={p.provider_id} className="bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-xl overflow-hidden shadow-sm hover:shadow-md transition-shadow group flex flex-col">
            <div className="p-5 border-b border-slate-100 dark:border-slate-700 flex justify-between items-start bg-slate-50/50 dark:bg-slate-800/50">
              <div className="flex items-center">
                <div className={`p-2 rounded-lg mr-3 ${activeTab === 'llm' ? 'bg-blue-100 dark:bg-blue-900/30 text-blue-600 dark:text-blue-400' : 'bg-emerald-100 dark:bg-emerald-900/30 text-emerald-600 dark:text-emerald-400'}`}>
                  {activeTab === 'llm' ? <Activity className="w-5 h-5" /> : <Database className="w-5 h-5" />}
                </div>
                <div>
                  <h3 className="font-bold text-slate-900 dark:text-white">{p.display_name}</h3>
                  <div className="flex items-center gap-2">
                    <code className="text-xs text-slate-400">{activeTab === 'llm' ? p.engine_id : p.provider_key}</code>
                    <span className="text-[10px] uppercase tracking-wide bg-slate-100 dark:bg-slate-700 text-slate-500 px-2 py-0.5 rounded-full">
                      {p.scope || 'global'}
                    </span>
                    {p.organization_id && selectedOrganization && (
                      <span className="text-[10px] uppercase tracking-wide bg-blue-50 dark:bg-blue-900/30 text-blue-600 dark:text-blue-300 px-2 py-0.5 rounded-full">
                        {selectedOrganization.name}
                      </span>
                    )}
                  </div>
                </div>
              </div>
              <div className="flex space-x-2">
                <button 
                  type="button"
                  onClick={(e) => { e.preventDefault(); e.stopPropagation(); handleOpenEditModal(p); }}
                  className="p-1.5 text-slate-400 hover:text-blue-500 hover:bg-blue-50 dark:hover:bg-blue-900/30 rounded-lg transition-colors"
                  title="Edit Provider"
                >
                  <Edit2 className="w-4 h-4" />
                </button>
                <button 
                  type="button"
                  onClick={(e) => { e.preventDefault(); e.stopPropagation(); handleDeleteProvider(p.provider_id, e); }}
                  className="p-1.5 text-slate-400 hover:text-rose-500 hover:bg-rose-50 dark:hover:bg-rose-900/30 rounded-lg transition-colors"
                  title="Delete Provider"
                >
                  <Trash2 className="w-4 h-4" />
                </button>
              </div>
            </div>
            
            <div className="p-5 flex-1 space-y-4">
              <p className="text-sm text-slate-500 dark:text-slate-400 line-clamp-2">{p.description}</p>
              
              <div className="grid grid-cols-2 gap-4 text-xs">
                <div className="space-y-1">
                  <span className="text-slate-400 block uppercase tracking-wider font-semibold">Backend</span>
                  <span className="text-slate-700 dark:text-slate-200 font-medium">{p.provider}</span>
                </div>
                <div className="space-y-1 text-right">
                  <span className="text-slate-400 block uppercase tracking-wider font-semibold">Status</span>
                  <span className={`inline-flex items-center font-medium ${p.enabled ? 'text-emerald-500' : 'text-slate-400'}`}>
                    <span className={`w-1.5 h-1.5 rounded-full mr-1.5 ${p.enabled ? 'bg-emerald-500 animate-pulse' : 'bg-slate-400'}`}></span>
                    {p.enabled ? 'Enabled' : 'Disabled'}
                  </span>
                </div>
              </div>
            </div>

            <div className="px-5 py-4 bg-slate-50 dark:bg-slate-800/50 border-t border-slate-100 dark:border-slate-700 mt-auto">
              <button 
                onClick={() => handleHealthCheck(p.provider_id)}
                className="w-full text-xs font-semibold py-2 bg-white dark:bg-slate-700 text-slate-600 dark:text-slate-300 border border-slate-200 dark:border-slate-600 rounded-lg hover:bg-slate-50 dark:hover:bg-slate-600 transition-colors flex items-center justify-center"
              >
                <Activity className="w-3 h-3 mr-2" />
                Run Health Check
              </button>
            </div>
          </div>
        ))}
        
        <button 
          onClick={handleOpenCreateModal}
          className="border-2 border-dashed border-slate-200 dark:border-slate-700 rounded-xl p-8 flex flex-col items-center justify-center text-slate-400 hover:text-blue-500 hover:border-blue-300 dark:hover:border-blue-700 transition-all hover:bg-blue-50/30 dark:hover:bg-blue-900/10 min-h-[220px]"
        >
          <div className="p-3 bg-slate-100 dark:bg-slate-800 rounded-full mb-3 group-hover:bg-blue-100 transition-colors">
            <Plus className="w-6 h-6" />
          </div>
          <span className="font-medium text-sm">Add New {activeTab === 'llm' ? 'LLM' : 'Memory'} Provider</span>
        </button>
      </div>

      {isModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/60 transition-opacity animate-in fade-in duration-200">
          <div className="bg-white dark:bg-slate-800 w-full max-w-4xl max-h-[90vh] overflow-y-auto rounded-2xl shadow-2xl border border-slate-200 dark:border-slate-700 animate-in zoom-in-95 duration-200 flex flex-col">
            <div className="sticky top-0 z-10 p-6 border-b border-slate-100 dark:border-slate-700 flex justify-between items-center bg-white dark:bg-slate-800/95 backdrop-blur-md">
              <div>
                <h2 className="text-xl font-bold text-slate-900 dark:text-white flex items-center">
                  <Settings2 className="w-5 h-5 mr-3 text-blue-500" />
                  {modalMode === 'edit' ? 'Edit' : 'Configure New'} {activeTab === 'llm' ? 'LLM' : 'Memory'} Provider
                </h2>
                <p className="text-slate-500 text-sm mt-1">Fill in the provider configuration details below</p>
              </div>
              <button 
                onClick={() => setIsModalOpen(false)}
                className="p-2 text-slate-400 hover:text-slate-600 hover:bg-slate-100 dark:hover:bg-slate-700 rounded-full transition-all"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <form onSubmit={handleSubmit} className="p-8 space-y-8">
              {activeTab === 'llm' ? (
                <>
                  <div className="grid grid-cols-2 gap-8">
                    <div className="space-y-4">
                      <h4 className="text-sm font-bold text-slate-400 uppercase tracking-widest border-b border-slate-100 dark:border-slate-700 pb-2">Basic Info</h4>
                      <div className="space-y-4">
                        <div>
                          <label className="block text-sm font-semibold text-slate-700 dark:text-slate-300 mb-1.5">Engine ID</label>
                          <input
                            required
                            placeholder="e.g. gpt-4, claude-3"
                            className="w-full bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-lg px-4 py-2.5 focus:ring-2 focus:ring-blue-500 outline-none transition-all text-slate-900 dark:text-white"
                            value={llmFormData.engine_id}
                            onChange={e => setLlmFormData({...llmFormData, engine_id: e.target.value})}
                          />
                        </div>
                        <div>
                          <label className="block text-sm font-semibold text-slate-700 dark:text-slate-300 mb-1.5">Display Name</label>
                          <input
                            required
                            placeholder="e.g. OpenAI GPT-4"
                            className="w-full bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-lg px-4 py-2.5 focus:ring-2 focus:ring-blue-500 outline-none transition-all text-slate-900 dark:text-white"
                            value={llmFormData.display_name}
                            onChange={e => setLlmFormData({...llmFormData, display_name: e.target.value})}
                          />
                        </div>
                        <div>
                          <label className="block text-sm font-semibold text-slate-700 dark:text-slate-300 mb-1.5">Description</label>
                          <textarea
                            rows={3}
                            placeholder="Brief description of this provider"
                            className="w-full bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-lg px-4 py-2.5 focus:ring-2 focus:ring-blue-500 outline-none transition-all text-slate-900 dark:text-white resize-none"
                            value={llmFormData.description}
                            onChange={e => setLlmFormData({...llmFormData, description: e.target.value})}
                          />
                        </div>
                      </div>
                    </div>

                    <div className="space-y-4">
                      <h4 className="text-sm font-bold text-slate-400 uppercase tracking-widest border-b border-slate-100 dark:border-slate-700 pb-2">Technical Setup</h4>
                      <div className="grid grid-cols-2 gap-4">
                        <div>
                          <label className="block text-sm font-semibold text-slate-700 dark:text-slate-300 mb-1.5">Backend</label>
                          <select
                            className="w-full bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-lg px-4 py-2.5 focus:ring-2 focus:ring-blue-500 outline-none appearance-none transition-all text-slate-900 dark:text-white"
                            value={llmFormData.provider}
                            onChange={e => setLlmFormData({...llmFormData, provider: e.target.value})}
                          >
                            <option value="openai">OpenAI</option>
                            <option value="anthropic">Anthropic</option>
                            <option value="ollama">Ollama</option>
                            <option value="vllm">vLLM</option>
                            <option value="azure">Azure OpenAI</option>
                          </select>
                        </div>
                        <div>
                          <label className="block text-sm font-semibold text-slate-700 dark:text-slate-300 mb-1.5">Endpoint Kind</label>
                          <select
                            className="w-full bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-lg px-4 py-2.5 focus:ring-2 focus:ring-blue-500 outline-none appearance-none transition-all text-slate-900 dark:text-white"
                            value={llmFormData.endpoint_kind}
                            onChange={e => setLlmFormData({...llmFormData, endpoint_kind: e.target.value})}
                          >
                            <option value="remote">Remote (Cloud)</option>
                            <option value="local">Local Service</option>
                          </select>
                        </div>
                      </div>
                      <div>
                        <label className="block text-sm font-semibold text-slate-700 dark:text-slate-300 mb-1.5">Base URL (Optional)</label>
                        <input
                          placeholder="e.g. https://api.openai.com/v1"
                          className="w-full bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-lg px-4 py-2.5 focus:ring-2 focus:ring-blue-500 outline-none transition-all text-slate-900 dark:text-white"
                          value={llmFormData.url}
                          onChange={e => setLlmFormData({...llmFormData, url: e.target.value})}
                        />
                      </div>
                      <div>
                        <label className="block text-sm font-semibold text-slate-700 dark:text-slate-300 mb-1.5">Default Model</label>
                        <input
                          placeholder="e.g. gpt-4o"
                          className="w-full bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-lg px-4 py-2.5 focus:ring-2 focus:ring-blue-500 outline-none transition-all text-slate-900 dark:text-white"
                          value={llmFormData.default_model}
                          onChange={e => setLlmFormData({...llmFormData, default_model: e.target.value})}
                        />
                      </div>
                    </div>
                  </div>

                  <div className="grid grid-cols-2 gap-8">
                    <div className="space-y-4">
                      <h4 className="text-sm font-bold text-slate-400 uppercase tracking-widest border-b border-slate-100 dark:border-slate-700 pb-2">Policy & Prefs</h4>
                      <div className="grid grid-cols-2 gap-4">
                        <div>
                          <label className="block text-sm font-semibold text-slate-700 dark:text-slate-300 mb-1.5">Locality</label>
                          <select
                            className="w-full bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-lg px-4 py-2.5 focus:ring-2 focus:ring-blue-500 outline-none transition-all text-slate-900 dark:text-white"
                            value={llmFormData.locality}
                            onChange={e => setLlmFormData({...llmFormData, locality: e.target.value})}
                          >
                            <option value="cloud">Cloud</option>
                            <option value="local">On-Prem</option>
                          </select>
                        </div>
                        <div>
                          <label className="block text-sm font-semibold text-slate-700 dark:text-slate-300 mb-1.5">Priority</label>
                          <input
                            type="number"
                            className="w-full bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-lg px-4 py-2.5 focus:ring-2 focus:ring-blue-500 outline-none transition-all text-slate-900 dark:text-white"
                            value={llmFormData.priority}
                            onChange={e => setLlmFormData({...llmFormData, priority: e.target.value})}
                          />
                        </div>
                      </div>
                      <div>
                        <label className="block text-sm font-semibold text-slate-700 dark:text-slate-300 mb-1.5">Capabilities (comma separated)</label>
                        <input
                          placeholder="e.g. chat, vision, tool_use"
                          className="w-full bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-lg px-4 py-2.5 focus:ring-2 focus:ring-blue-500 outline-none transition-all text-slate-900 dark:text-white"
                          value={llmFormData.capabilities}
                          onChange={e => setLlmFormData({...llmFormData, capabilities: e.target.value})}
                        />
                      </div>
                      <div className="flex items-center p-3 bg-slate-50 dark:bg-slate-900 rounded-lg border border-slate-100 dark:border-slate-700 w-fit">
                        <input
                          type="checkbox"
                          id="llm-enabled"
                          className="w-4 h-4 text-blue-600 rounded mr-3"
                          checked={llmFormData.enabled}
                          onChange={e => setLlmFormData({...llmFormData, enabled: e.target.checked})}
                        />
                        <label htmlFor="llm-enabled" className="text-sm font-semibold text-slate-700 dark:text-slate-300">Enable this provider immediately</label>
                      </div>
                    </div>

                    <div className="space-y-4">
                      <h4 className="text-sm font-bold text-slate-400 uppercase tracking-widest border-b border-slate-100 dark:border-slate-700 pb-2">Secrets & Metadata</h4>
                      <div>
                        <label className="block text-sm font-semibold text-slate-700 dark:text-slate-300 mb-1.5">Secret Config (JSON)</label>
                        <textarea
                          rows={4}
                          placeholder='{ "api_key": "..." }'
                          className="w-full bg-slate-900 dark:bg-black border border-slate-700 rounded-lg px-4 py-3 font-mono text-xs text-blue-400 focus:ring-2 focus:ring-blue-500 outline-none resize-none shadow-inner"
                          value={llmFormData.secret_config}
                          onChange={e => setLlmFormData({...llmFormData, secret_config: e.target.value})}
                        />
                        <p className="text-[10px] text-slate-500 mt-1 italic italic">API keys, tokens, or credentials</p>
                      </div>
                      <div>
                        <label className="block text-sm font-semibold text-slate-700 dark:text-slate-300 mb-1.5">Metadata (JSON)</label>
                        <textarea
                          rows={2}
                          placeholder="{}"
                          className="w-full bg-slate-900 dark:bg-black border border-slate-700 rounded-lg px-4 py-3 font-mono text-xs text-slate-300 focus:ring-2 focus:ring-slate-500 outline-none resize-none shadow-inner"
                          value={llmFormData.metadata}
                          onChange={e => setLlmFormData({...llmFormData, metadata: e.target.value})}
                        />
                      </div>
                    </div>
                  </div>
                </>
              ) : (
                <>
                  <div className="grid grid-cols-2 gap-8">
                    <div className="space-y-4">
                      <h4 className="text-sm font-bold text-slate-400 uppercase tracking-widest border-b border-slate-100 dark:border-slate-700 pb-2">Basic Info</h4>
                      <div className="space-y-4">
                        <div>
                          <label className="block text-sm font-semibold text-slate-700 dark:text-slate-300 mb-1.5">Provider Key</label>
                          <input
                            required
                            placeholder="e.g. pg-vector, redis-search"
                            className="w-full bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-lg px-4 py-2.5 focus:ring-2 focus:ring-blue-500 outline-none transition-all text-slate-900 dark:text-white"
                            value={memoryFormData.provider_key}
                            onChange={e => setMemoryFormData({...memoryFormData, provider_key: e.target.value})}
                          />
                        </div>
                        <div>
                          <label className="block text-sm font-semibold text-slate-700 dark:text-slate-300 mb-1.5">Display Name</label>
                          <input
                            required
                            placeholder="e.g. Postgres Vector Store"
                            className="w-full bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-lg px-4 py-2.5 focus:ring-2 focus:ring-blue-500 outline-none transition-all text-slate-900 dark:text-white"
                            value={memoryFormData.display_name}
                            onChange={e => setMemoryFormData({...memoryFormData, display_name: e.target.value})}
                          />
                        </div>
                        <div>
                          <label className="block text-sm font-semibold text-slate-700 dark:text-slate-300 mb-1.5">Description</label>
                          <textarea
                            rows={3}
                            placeholder="Brief description of this memory provider"
                            className="w-full bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-lg px-4 py-2.5 focus:ring-2 focus:ring-blue-500 outline-none transition-all text-slate-900 dark:text-white resize-none"
                            value={memoryFormData.description}
                            onChange={e => setMemoryFormData({...memoryFormData, description: e.target.value})}
                          />
                        </div>
                      </div>
                    </div>

                    <div className="space-y-4">
                      <h4 className="text-sm font-bold text-slate-400 uppercase tracking-widest border-b border-slate-100 dark:border-slate-700 pb-2">Storage Config</h4>
                      <div>
                        <label className="block text-sm font-semibold text-slate-700 dark:text-slate-300 mb-1.5">Backend Vendor</label>
                        <select
                          className="w-full bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-lg px-4 py-2.5 focus:ring-2 focus:ring-blue-500 outline-none appearance-none transition-all text-slate-900 dark:text-white"
                          value={memoryFormData.provider}
                          onChange={e => setMemoryFormData({...memoryFormData, provider: e.target.value})}
                        >
                          <option value="postgres">Postgres (pgvector)</option>
                          <option value="redis">Redis (RediSearch)</option>
                          <option value="memgraph">Memgraph (Graph Store)</option>
                          <option value="mem0">Mem0 Managed</option>
                        </select>
                      </div>
                      <div>
                        <label className="block text-sm font-semibold text-slate-700 dark:text-slate-300 mb-1.5">Vendor Config (JSON)</label>
                        <textarea
                          rows={6}
                          placeholder='{ "host": "localhost", "port": 5432 }'
                          className="w-full bg-slate-900 dark:bg-black border border-slate-700 rounded-lg px-4 py-3 font-mono text-xs text-emerald-400 focus:ring-2 focus:ring-emerald-500 outline-none resize-none shadow-inner"
                          value={memoryFormData.config}
                          onChange={e => setMemoryFormData({...memoryFormData, config: e.target.value})}
                        />
                        <p className="text-[10px] text-slate-500 mt-1 italic italic">Non-secret connection parameters</p>
                      </div>
                      <div className="flex items-center p-3 bg-slate-50 dark:bg-slate-900 rounded-lg border border-slate-100 dark:border-slate-700 w-fit">
                        <input
                          type="checkbox"
                          id="mem-enabled"
                          className="w-4 h-4 text-emerald-600 rounded mr-3"
                          checked={memoryFormData.enabled}
                          onChange={e => setMemoryFormData({...memoryFormData, enabled: e.target.checked})}
                        />
                        <label htmlFor="mem-enabled" className="text-sm font-semibold text-slate-700 dark:text-slate-300">Enable this provider immediately</label>
                      </div>
                    </div>
                  </div>

                  <div className="grid grid-cols-2 gap-8">
                    <div className="space-y-4">
                      <h4 className="text-sm font-bold text-slate-400 uppercase tracking-widest border-b border-slate-100 dark:border-slate-700 pb-2">Secret Config</h4>
                      <div>
                        <label className="block text-sm font-semibold text-slate-700 dark:text-slate-300 mb-1.5">Secret Config (JSON)</label>
                        <textarea
                          rows={4}
                          placeholder='{ "password": "..." }'
                          className="w-full bg-slate-900 dark:bg-black border border-slate-700 rounded-lg px-4 py-3 font-mono text-xs text-blue-400 focus:ring-2 focus:ring-blue-500 outline-none resize-none shadow-inner"
                          value={memoryFormData.secret_config}
                          onChange={e => setMemoryFormData({...memoryFormData, secret_config: e.target.value})}
                        />
                      </div>
                    </div>
                    <div className="space-y-4">
                      <h4 className="text-sm font-bold text-slate-400 uppercase tracking-widest border-b border-slate-100 dark:border-slate-700 pb-2">Metadata</h4>
                      <div>
                        <label className="block text-sm font-semibold text-slate-700 dark:text-slate-300 mb-1.5">Metadata (JSON)</label>
                        <textarea
                          rows={4}
                          placeholder="{}"
                          className="w-full bg-slate-900 dark:bg-black border border-slate-700 rounded-lg px-4 py-3 font-mono text-xs text-slate-300 focus:ring-2 focus:ring-slate-500 outline-none resize-none shadow-inner"
                          value={memoryFormData.metadata}
                          onChange={e => setMemoryFormData({...memoryFormData, metadata: e.target.value})}
                        />
                      </div>
                    </div>
                  </div>
                </>
              )}

              <div className="flex justify-end space-x-4 pt-6 border-t border-slate-100 dark:border-slate-700 sticky bottom-0 bg-white dark:bg-slate-800 py-4 -mb-8">
                <button
                  type="button"
                  onClick={() => setIsModalOpen(false)}
                  className="px-6 py-2.5 text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white font-semibold transition-colors"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="px-10 py-2.5 bg-blue-600 hover:bg-blue-700 text-white rounded-lg font-bold shadow-lg shadow-blue-500/20 transition-all hover:scale-[1.02] active:scale-[0.98]"
                >
                  {modalMode === 'edit' ? 'Update' : 'Create'} Provider
                </button>
              </div>
            </form>
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
