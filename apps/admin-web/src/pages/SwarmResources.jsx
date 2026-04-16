import React, { useEffect, useState } from 'react';
import { 
  Bot, 
  Wrench, 
  AlertTriangle, 
  Edit2, 
  Trash2, 
  Plus, 
  Settings2, 
  X,
  Code2,
  Cpu,
  Globe
} from 'lucide-react';
import { useApi } from '../api/useApi';
import ConfirmationModal from '../components/Common/ConfirmationModal';

const API_BASE = 'http://localhost:8000/v1';

export default function SwarmResources() {
  const api = useApi();
  const [agents, setAgents] = useState([]);
  const [tools, setTools] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  // Modal states
  const [isAgentModalOpen, setIsAgentModalOpen] = useState(false);
  const [isToolModalOpen, setIsToolModalOpen] = useState(false);
  const [agentModalMode, setAgentModalMode] = useState('create');
  const [toolModalMode, setToolModalMode] = useState('create');
  const [editingAgent, setEditingAgent] = useState(null);
  const [editingTool, setEditingTool] = useState(null);
  
  const [agentData, setAgentData] = useState({
    display_name: '', description: '', role: 'assistant', capabilities: 'execute_code',
    endpoint_kind: 'local', endpoint_model: '', endpoint_provider: '',
    system_prompt: 'You are a helpful assistant.', instructions: '', completion_criteria: ''
  });

  const [toolData, setToolData] = useState({
    name: '', description: '', param_strategy: 'strict', exec_strategy: 'webhook', exec_url: ''
  });
  const [toolSchema, setToolSchema] = useState('{\n  "type": "object",\n  "properties": {},\n  "required": []\n}');
  
  const [confirmModal, setConfirmModal] = useState({ 
    isOpen: false, 
    title: '', 
    message: '', 
    onConfirm: () => {} 
  });

  const fetchResources = async () => {
    try {
      setLoading(true);
      const [agentsRes, toolsRes] = await Promise.all([
        api.get('/v1/agents'),
        api.get('/v1/tools')
      ]);
      setAgents(agentsRes.data);
      setTools(toolsRes.data);
      setError(null);
    } catch (err) {
      setError(err.message || 'Failed to fetch swarm resources');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchResources();
  }, [api]);

  const resetAgentForm = () => {
    setAgentData({
      display_name: '', description: '', role: 'assistant', capabilities: 'execute_code',
      endpoint_kind: 'local', endpoint_model: '', endpoint_provider: '',
      system_prompt: 'You are a helpful assistant.', instructions: '', completion_criteria: ''
    });
    setEditingAgent(null);
    setAgentModalMode('create');
  };

  const resetToolForm = () => {
    setToolData({
      name: '', description: '', param_strategy: 'strict', exec_strategy: 'webhook', exec_url: ''
    });
    setToolSchema('{\n  "type": "object",\n  "properties": {},\n  "required": []\n}');
    setEditingTool(null);
    setToolModalMode('create');
  };

  const handleOpenAgentEdit = (agent) => {
    setEditingAgent(agent);
    setAgentModalMode('edit');
    setAgentData({
      display_name: agent.display_name,
      description: agent.description,
      role: agent.role,
      capabilities: agent.capabilities.join(', '),
      endpoint_kind: agent.endpoint.kind,
      endpoint_model: agent.endpoint.model || '',
      endpoint_provider: agent.endpoint.provider || '',
      system_prompt: agent.system_prompt,
      instructions: agent.interaction_contract?.instructions?.join(', ') || '',
      completion_criteria: agent.interaction_contract?.completion_criteria?.join(', ') || ''
    });
    setIsAgentModalOpen(true);
  };

  const handleOpenToolEdit = (tool) => {
    setEditingTool(tool);
    setToolModalMode('edit');
    setToolData({
      name: tool.name,
      description: tool.description,
      param_strategy: tool.parameter_contract.strategy,
      exec_strategy: tool.execution.strategy,
      exec_url: tool.execution.config?.url || ''
    });
    setToolSchema(JSON.stringify(tool.input_schema, null, 2));
    setIsToolModalOpen(true);
  };

  const handleDeleteAgent = async (agent_id) => {
    setConfirmModal({
      isOpen: true,
      title: 'Delete Agent?',
      message: 'Are you sure you want to delete this agent definition? This will remove the agent from the system registry.',
      onConfirm: async () => {
        try {
          await api.delete(`/v1/agents/${agent_id}`, {
            data: {
              actor: { participant_id: "00000000-0000-0000-0000-000000000001", participant_type: "user", display_name: "Admin" }
            }
          });
          fetchResources();
        } catch (err) {
          alert('Failed to delete agent: ' + err.message);
        }
      }
    });
  };

  const handleDeleteTool = async (tool_id) => {
    setConfirmModal({
      isOpen: true,
      title: 'Delete Tool?',
      message: 'Are you sure you want to delete this system tool? Agents relying on this tool may fail to execute tasks.',
      onConfirm: async () => {
        try {
          await api.delete(`/v1/tools/${tool_id}`, {
            data: {
              actor: { participant_id: "00000000-0000-0000-0000-000000000001", participant_type: "user", display_name: "Admin" }
            }
          });
          fetchResources();
        } catch (err) {
          alert('Failed to delete tool: ' + err.message);
        }
      }
    });
  };

  const handleSaveAgent = async () => {
    try {
      const payload = {
        actor: { participant_id: "00000000-0000-0000-0000-000000000001", participant_type: "user", display_name: "Admin" },
        display_name: agentData.display_name,
        description: agentData.description,
        role: agentData.role,
        capabilities: agentData.capabilities.split(',').map(s => s.trim()).filter(Boolean),
        endpoint: { kind: agentData.endpoint_kind, model: agentData.endpoint_model || null, provider: agentData.endpoint_provider || null },
        system_prompt: agentData.system_prompt,
        interaction_contract: {
          instructions: agentData.instructions.split(',').map(s => s.trim()).filter(Boolean),
          completion_criteria: agentData.completion_criteria.split(',').map(s => s.trim()).filter(Boolean),
          response_contract: { content_type: 'text/markdown', json_mode: false }
        }
      };

      if (agentModalMode === 'create') {
        await api.post('/v1/agents', payload);
      } else {
        await api.patch(`/v1/agents/${editingAgent.agent_id}`, payload);
      }
      
      setIsAgentModalOpen(false);
      resetAgentForm();
      fetchResources();
    } catch (err) {
      setError('Failed to save agent: ' + err.message);
    }
  };

  const handleSaveTool = async () => {
    try {
      const payload = {
        actor: { participant_id: "00000000-0000-0000-0000-000000000001", participant_type: "user", display_name: "Admin" },
        name: toolData.name,
        description: toolData.description,
        parameter_contract: { strategy: toolData.param_strategy },
        input_schema: JSON.parse(toolSchema),
        execution: { strategy: toolData.exec_strategy, config: toolData.exec_url ? { url: toolData.exec_url } : {} }
      };

      if (toolModalMode === 'create') {
        await api.post('/v1/tools', payload);
      } else {
        await api.patch(`/v1/tools/${editingTool.tool_id}`, payload);
      }

      setIsToolModalOpen(false);
      resetToolForm();
      fetchResources();
    } catch (err) {
      setError('Failed to save tool: ' + err.message);
    }
  };

  if (loading) return <div className="p-8 text-slate-500">Loading swarm definitions...</div>;

  return (
    <div className="p-8 space-y-6">
      <div className="flex justify-between items-center bg-white dark:bg-slate-800 p-6 rounded-xl border border-slate-200 dark:border-slate-700 shadow-sm">
        <div>
          <h1 className="text-2xl font-bold text-slate-900 dark:text-white flex items-center">
            <Bot className="w-6 h-6 mr-3 text-blue-500" />
            Swarm Resources
          </h1>
          <p className="text-slate-500 mt-1">Manage system-wide agent and tool definitions</p>
        </div>
        <div className="flex gap-4">
          <button 
            onClick={() => { resetAgentForm(); setIsAgentModalOpen(true); }}
            className="bg-blue-600 hover:bg-blue-700 text-white px-4 py-2 rounded-lg flex items-center transition-all shadow-lg shadow-blue-500/20 font-medium"
          >
            <Plus className="w-5 h-5 mr-2" />
            Add Agent
          </button>
          <button 
            onClick={() => { resetToolForm(); setIsToolModalOpen(true); }}
            className="bg-emerald-600 hover:bg-emerald-700 text-white px-4 py-2 rounded-lg flex items-center transition-all shadow-lg shadow-emerald-500/20 font-medium"
          >
            <Plus className="w-5 h-5 mr-2" />
            Add Tool
          </button>
        </div>
      </div>
      
      {error && (
        <div className="bg-rose-50 dark:bg-rose-900/20 text-rose-600 dark:text-rose-400 p-4 rounded-lg flex items-center border border-rose-200 dark:border-rose-800">
          <AlertTriangle className="w-5 h-5 mr-3" />
          {error}
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
        {/* Agents List */}
        <div className="space-y-4">
          <div className="flex items-center gap-2 mb-2">
            <Bot className="text-blue-500 w-5 h-5" />
            <h2 className="text-lg font-bold dark:text-white">System Agents</h2>
            <span className="text-xs bg-slate-100 dark:bg-slate-800 text-slate-500 py-1 px-2 rounded-full font-mono">
              {agents.length}
            </span>
          </div>
          <div className="bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-xl divide-y divide-slate-100 dark:divide-slate-700 shadow-sm overflow-hidden">
            {agents.length === 0 ? (
              <div className="p-8 text-slate-500 text-center italic">No system agents registered.</div>
            ) : (
              agents.map(agent => (
                <div key={agent.agent_id} className="p-5 flex items-start justify-between hover:bg-slate-50 dark:hover:bg-slate-700/30 transition-colors">
                  <div className="space-y-2 max-w-[70%]">
                    <div className="flex items-center gap-2">
                      <span className="font-bold text-slate-900 dark:text-white text-lg">{agent.display_name}</span>
                      <span className="text-[10px] bg-blue-50 dark:bg-blue-900/40 text-blue-600 dark:text-blue-400 px-2 py-0.5 rounded-full font-mono border border-blue-100 dark:border-blue-800 uppercase tracking-tight">
                        {agent.endpoint.kind}
                      </span>
                    </div>
                    <p className="text-sm text-slate-500 dark:text-slate-400 line-clamp-1">{agent.description}</p>
                    <div className="flex flex-wrap gap-1.5">
                      {agent.capabilities.map(c => (
                        <span key={c} className="text-[10px] bg-slate-100 dark:bg-slate-900 text-slate-500 dark:text-slate-400 px-2 py-0.5 rounded border border-slate-200 dark:border-slate-800 font-medium">
                          {c}
                        </span>
                      ))}
                    </div>
                  </div>
                  <div className="flex gap-2">
                    <button 
                      onClick={() => handleOpenAgentEdit(agent)}
                      className="p-2 text-slate-400 hover:text-blue-500 hover:bg-blue-50 dark:hover:bg-blue-900/30 rounded-lg transition-all"
                      title="Edit Agent"
                    >
                      <Edit2 className="w-4 h-4" />
                    </button>
                    <button 
                      type="button"
                      onClick={(e) => { e.preventDefault(); e.stopPropagation(); handleDeleteAgent(agent.agent_id); }}
                      className="p-2 text-slate-400 hover:text-rose-500 hover:bg-rose-50 dark:hover:bg-rose-900/30 rounded-lg transition-all"
                      title="Delete Agent"
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                  </div>
                </div>
              ))
            )}
          </div>
        </div>

        {/* Tools List */}
        <div className="space-y-4">
          <div className="flex items-center gap-2 mb-2">
            <Wrench className="text-emerald-500 w-5 h-5" />
            <h2 className="text-lg font-bold dark:text-white">System Tools</h2>
            <span className="text-xs bg-slate-100 dark:bg-slate-800 text-slate-500 py-1 px-2 rounded-full font-mono">
              {tools.length}
            </span>
          </div>
          <div className="bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-xl divide-y divide-slate-100 dark:divide-slate-700 shadow-sm overflow-hidden">
            {tools.length === 0 ? (
              <div className="p-8 text-slate-500 text-center italic">No system tools registered.</div>
            ) : (
              tools.map(tool => (
                <div key={tool.tool_id} className="p-5 flex items-start justify-between hover:bg-slate-50 dark:hover:bg-slate-700/30 transition-colors">
                  <div className="space-y-2 max-w-[70%]">
                    <div className="flex items-center gap-2">
                      <span className="font-bold text-slate-900 dark:text-white text-lg">{tool.name}</span>
                      <span className="text-[10px] bg-emerald-50 dark:bg-emerald-900/40 text-emerald-600 dark:text-emerald-400 px-2 py-0.5 rounded-full font-mono border border-emerald-100 dark:border-emerald-800 uppercase tracking-tight">
                        {tool.execution.strategy}
                      </span>
                    </div>
                    <p className="text-sm text-slate-500 dark:text-slate-400 line-clamp-1">{tool.description}</p>
                    <div className="flex items-center text-xs text-slate-400 font-mono italic">
                      {tool.execution.config?.url || 'Internal process'}
                    </div>
                  </div>
                  <div className="flex gap-2">
                    <button 
                      type="button"
                      onClick={(e) => { e.preventDefault(); e.stopPropagation(); handleOpenToolEdit(tool); }}
                      className="p-2 text-slate-400 hover:text-blue-500 hover:bg-blue-50 dark:hover:bg-blue-900/30 rounded-lg transition-all"
                      title="Edit Tool"
                    >
                      <Edit2 className="w-4 h-4" />
                    </button>
                    <button 
                      type="button"
                      onClick={(e) => { e.preventDefault(); e.stopPropagation(); handleDeleteTool(tool.tool_id); }}
                      className="p-2 text-slate-400 hover:text-rose-500 hover:bg-rose-50 dark:hover:bg-rose-900/30 rounded-lg transition-all"
                      title="Delete Tool"
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                  </div>
                </div>
              ))
            )}
          </div>
        </div>
      </div>

      {/* Agent Modal */}
      {isAgentModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/60 transition-opacity animate-in fade-in duration-200">
          <div className="bg-white dark:bg-slate-800 w-full max-w-4xl max-h-[90vh] overflow-y-auto rounded-2xl shadow-2xl border border-slate-200 dark:border-slate-700 animate-in zoom-in-95 duration-200 flex flex-col">
            <div className="sticky top-0 z-10 p-6 border-b border-slate-100 dark:border-slate-700 flex justify-between items-center bg-white dark:bg-slate-800/95 backdrop-blur-md">
              <div>
                <h2 className="text-xl font-bold text-slate-900 dark:text-white flex items-center">
                  <span className={`p-1.5 rounded-lg mr-3 ${agentModalMode === 'edit' ? 'bg-blue-100 dark:bg-blue-900/30 text-blue-600' : 'bg-emerald-100 dark:bg-emerald-900/30 text-emerald-600'}`}>
                    <Bot className="w-6 h-6"/>
                  </span>
                  {agentModalMode === 'edit' ? 'Update' : 'Provision New'} System Agent
                </h2>
                <p className="text-slate-500 text-sm mt-1">Configure persona, integration endpoint, and behavioral contracts</p>
              </div>
              <button onClick={() => setIsAgentModalOpen(false)} className="p-2 text-slate-400 hover:text-slate-600 hover:bg-slate-100 dark:hover:bg-slate-700 rounded-full transition-all">
                <X className="w-5 h-5" />
              </button>
            </div>
            
            <div className="p-8 space-y-8">
              <div className="grid grid-cols-2 gap-8">
                <div className="space-y-4">
                  <h4 className="text-xs font-bold text-slate-400 uppercase tracking-widest border-b border-slate-100 dark:border-slate-700 pb-2">Core Identity</h4>
                  <div>
                    <label className="block text-sm font-semibold text-slate-700 dark:text-slate-300 mb-1.5">Display Name</label>
                    <input type="text" value={agentData.display_name} onChange={e => setAgentData({...agentData, display_name: e.target.value})} className="w-full bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-lg px-4 py-2.5 focus:ring-2 focus:ring-blue-500 outline-none transition-all text-slate-900 dark:text-white" placeholder="e.g. Code Architect" />
                  </div>
                  <div>
                    <label className="block text-sm font-semibold text-slate-700 dark:text-slate-300 mb-1.5">Internal Role Key</label>
                    <input type="text" value={agentData.role} onChange={e => setAgentData({...agentData, role: e.target.value})} className="w-full bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-lg px-4 py-2.5 focus:ring-2 focus:ring-blue-500 outline-none transition-all font-mono text-sm text-slate-900 dark:text-white" placeholder="e.g. software_engineer" />
                  </div>
                  <div>
                    <label className="block text-sm font-semibold text-slate-700 dark:text-slate-300 mb-1.5">Description</label>
                    <textarea value={agentData.description} onChange={e => setAgentData({...agentData, description: e.target.value})} rows={3} className="w-full bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-lg px-4 py-2.5 focus:ring-2 focus:ring-blue-500 outline-none transition-all text-slate-900 dark:text-white resize-none" placeholder="What is this agent specialized for?" />
                  </div>
                </div>

                <div className="space-y-4">
                  <h4 className="text-xs font-bold text-slate-400 uppercase tracking-widest border-b border-slate-100 dark:border-slate-700 pb-2 flex items-center justify-between">
                    Runtime Integration
                    <Cpu className="w-3 h-3" />
                  </h4>
                  <div className="p-4 bg-slate-50 dark:bg-slate-900 rounded-xl border border-slate-100 dark:border-slate-700 space-y-4">
                    <div>
                      <label className="block text-sm font-semibold text-slate-700 dark:text-slate-300 mb-1.5">Endpoint Kind</label>
                      <select value={agentData.endpoint_kind} onChange={e => setAgentData({...agentData, endpoint_kind: e.target.value})} className="w-full bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg px-4 py-2.5 focus:ring-2 focus:ring-blue-500 outline-none transition-all text-slate-900 dark:text-white appearance-none">
                        <option value="local">local (stateless runtime)</option>
                        <option value="system">system (built-in kernel loop)</option>
                        <option value="remote">remote (custom gRPC/HTTP)</option>
                      </select>
                    </div>
                    <div className="grid grid-cols-2 gap-4">
                      <div>
                        <label className="block text-sm font-semibold text-slate-700 dark:text-slate-300 mb-1.5">Default Provider</label>
                        <input type="text" value={agentData.endpoint_provider} onChange={e => setAgentData({...agentData, endpoint_provider: e.target.value})} className="w-full bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg px-3 py-2 focus:ring-2 focus:ring-blue-500 outline-none transition-all text-sm" placeholder="e.g. openai" />
                      </div>
                      <div>
                        <label className="block text-sm font-semibold text-slate-700 dark:text-slate-300 mb-1.5">Ideal Model</label>
                        <input type="text" value={agentData.endpoint_model} onChange={e => setAgentData({...agentData, endpoint_model: e.target.value})} className="w-full bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg px-3 py-2 focus:ring-2 focus:ring-blue-500 outline-none transition-all text-sm" placeholder="e.g. gpt-4o" />
                      </div>
                    </div>
                  </div>
                  <div>
                    <label className="block text-sm font-semibold text-slate-700 dark:text-slate-300 mb-1.5">Capabilities</label>
                    <input type="text" value={agentData.capabilities} onChange={e => setAgentData({...agentData, capabilities: e.target.value})} className="w-full bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-lg px-4 py-2.5 focus:ring-2 focus:ring-blue-500 outline-none transition-all text-sm font-mono text-blue-600 dark:text-blue-400" placeholder="comma-separated keys..." />
                  </div>
                </div>
              </div>

              <div className="space-y-4">
                <h4 className="text-xs font-bold text-slate-400 uppercase tracking-widest border-b border-slate-100 dark:border-slate-700 pb-2 flex items-center justify-between">
                  Behavioral Directives
                  <Globe className="w-3 h-3" />
                </h4>
                <div className="p-6 bg-slate-50 dark:bg-slate-900 rounded-xl border border-slate-100 dark:border-slate-700 space-y-6">
                  <div>
                    <label className="block text-sm font-semibold text-slate-700 dark:text-slate-300 mb-1.5 flex items-center">
                      System Prompt Template
                      <span className="ml-2 text-[10px] bg-slate-200 dark:bg-slate-800 px-2 py-0.5 rounded text-slate-500 uppercase">Canonical</span>
                    </label>
                    <textarea value={agentData.system_prompt} onChange={e => setAgentData({...agentData, system_prompt: e.target.value})} rows={6} className="w-full bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg px-4 py-3 font-serif text-slate-800 dark:text-slate-200 focus:ring-2 focus:ring-emerald-500 outline-none transition-all shadow-inner" placeholder="Detailed system-level instructions for the model..." />
                  </div>
                  <div className="grid grid-cols-2 gap-8">
                    <div>
                      <label className="block text-sm font-semibold text-slate-700 dark:text-slate-300 mb-1.5">Runtime Instructions</label>
                      <input type="text" value={agentData.instructions} onChange={e => setAgentData({...agentData, instructions: e.target.value})} className="w-full bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg px-4 py-2.5 focus:ring-2 focus:ring-emerald-500 outline-none transition-all text-sm" placeholder="Key behaviors to reinforce..." />
                    </div>
                    <div>
                      <label className="block text-sm font-semibold text-slate-700 dark:text-slate-300 mb-1.5">Success Criteria</label>
                      <input type="text" value={agentData.completion_criteria} onChange={e => setAgentData({...agentData, completion_criteria: e.target.value})} className="w-full bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg px-4 py-2.5 focus:ring-2 focus:ring-emerald-500 outline-none transition-all text-sm" placeholder="How to know the task is done..." />
                    </div>
                  </div>
                </div>
              </div>

              <div className="flex justify-end space-x-4 pt-4 sticky bottom-0 bg-white dark:bg-slate-800 py-6 border-t border-slate-100 dark:border-slate-700 -mb-8">
                <button 
                  onClick={() => setIsAgentModalOpen(false)}
                  className="px-6 py-2.5 text-slate-500 font-semibold hover:text-slate-800 dark:hover:text-slate-200 transition-colors"
                >
                  Cancel
                </button>
                <button 
                  onClick={handleSaveAgent}
                  className="px-10 py-2.5 bg-blue-600 hover:bg-blue-700 text-white rounded-lg font-bold shadow-lg shadow-blue-500/20 transition-all hover:scale-[1.02] active:scale-[0.98]"
                >
                  {agentModalMode === 'edit' ? 'Update Agent' : 'Create Agent'}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Tool Modal */}
      {isToolModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/60 transition-opacity animate-in fade-in duration-200">
          <div className="bg-white dark:bg-slate-800 w-full max-w-2xl max-h-[90vh] overflow-y-auto rounded-2xl shadow-2xl border border-slate-200 dark:border-slate-700 animate-in zoom-in-95 duration-200 flex flex-col">
            <div className="sticky top-0 z-10 p-6 border-b border-slate-100 dark:border-slate-700 flex justify-between items-center bg-white dark:bg-slate-800/95 backdrop-blur-md">
              <div>
                <h2 className="text-xl font-bold text-slate-900 dark:text-white flex items-center">
                  <span className={`p-1.5 rounded-lg mr-3 ${toolModalMode === 'edit' ? 'bg-emerald-100 dark:bg-emerald-900/30 text-emerald-600' : 'bg-teal-100 dark:bg-teal-900/30 text-teal-600'}`}>
                    <Wrench className="w-6 h-6"/>
                  </span>
                  {toolModalMode === 'edit' ? 'Update' : 'Define New'} System Tool
                </h2>
                <p className="text-slate-500 text-sm mt-1">Specify tool invocation schema and execution backend</p>
              </div>
              <button onClick={() => setIsToolModalOpen(false)} className="p-2 text-slate-400 hover:text-slate-600 hover:bg-slate-100 dark:hover:bg-slate-700 rounded-full transition-all">
                <X className="w-5 h-5" />
              </button>
            </div>
            
            <div className="p-8 space-y-8">
              <div className="space-y-4">
                <h4 className="text-xs font-bold text-slate-400 uppercase tracking-widest border-b border-slate-100 dark:border-slate-700 pb-2">Tool Specification</h4>
                <div className="grid grid-cols-2 gap-6">
                  <div>
                    <label className="block text-sm font-semibold text-slate-700 dark:text-slate-300 mb-1.5">Tool Name (ID)</label>
                    <input type="text" value={toolData.name} onChange={e => setToolData({...toolData, name: e.target.value})} className="w-full bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-lg px-4 py-2.5 focus:ring-2 focus:ring-emerald-500 outline-none transition-all font-mono text-sm" placeholder="e.g. github_search" />
                  </div>
                  <div>
                    <label className="block text-sm font-semibold text-slate-700 dark:text-slate-300 mb-1.5">Param Strategy</label>
                    <select value={toolData.param_strategy} onChange={e => setToolData({...toolData, param_strategy: e.target.value})} className="w-full bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-lg px-4 py-2.5 focus:ring-2 focus:ring-emerald-500 outline-none transition-all">
                      <option value="strict">Strict (Schema required)</option>
                      <option value="flexible">Flexible (Key-Value)</option>
                    </select>
                  </div>
                </div>
                <div>
                  <label className="block text-sm font-semibold text-slate-700 dark:text-slate-300 mb-1.5">Description</label>
                  <textarea value={toolData.description} onChange={e => setToolData({...toolData, description: e.target.value})} rows={2} className="w-full bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-lg px-4 py-2.5 focus:ring-2 focus:ring-emerald-500 outline-none transition-all text-sm resize-none" placeholder="Detailed description for the LLM discovery..." />
                </div>
              </div>

              <div className="space-y-4">
                <h4 className="text-xs font-bold text-slate-400 uppercase tracking-widest border-b border-slate-100 dark:border-slate-700 pb-2 flex items-center justify-between">
                  Execution Backend
                  <Settings2 className="w-3 h-3" />
                </h4>
                <div className="grid grid-cols-2 gap-6 p-4 bg-slate-50 dark:bg-slate-900 rounded-xl border border-slate-100 dark:border-slate-700">
                  <div>
                    <label className="block text-sm font-semibold text-slate-700 dark:text-slate-300 mb-1.5">Strategy</label>
                    <select value={toolData.exec_strategy} onChange={e => setToolData({...toolData, exec_strategy: e.target.value})} className="w-full bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg px-4 py-2.5 focus:ring-2 focus:ring-emerald-500 outline-none transition-all">
                      <option value="webhook">Webhook (HTTP POST)</option>
                      <option value="local_process">Local Process (Worker-side)</option>
                      <option value="built_in">Built-in (Kernel internal)</option>
                    </select>
                  </div>
                  {toolData.exec_strategy === 'webhook' && (
                    <div>
                      <label className="block text-sm font-semibold text-slate-700 dark:text-slate-300 mb-1.5">Webhook URL</label>
                      <input type="text" value={toolData.exec_url} onChange={e => setToolData({...toolData, exec_url: e.target.value})} className="w-full bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg px-4 py-2 focus:ring-2 focus:ring-emerald-500 outline-none transition-all text-xs font-mono" placeholder="https://..." />
                    </div>
                  )}
                </div>
              </div>

              <div className="space-y-4">
                <h4 className="text-xs font-bold text-slate-400 uppercase tracking-widest border-b border-slate-100 dark:border-slate-700 pb-2 flex items-center justify-between">
                  Input Schema
                  <Code2 className="w-3 h-3" />
                </h4>
                <div className="relative group">
                  <textarea
                    value={toolSchema}
                    onChange={(e) => setToolSchema(e.target.value)}
                    rows={12}
                    className="w-full bg-slate-900 dark:bg-black border border-slate-800 rounded-xl px-4 py-4 font-mono text-[13px] text-emerald-400 focus:ring-2 focus:ring-emerald-500 outline-none resize-none shadow-2xl"
                  />
                  <div className="absolute top-3 right-3 text-[10px] bg-slate-800/80 px-2 py-1 rounded text-slate-500 font-bold uppercase tracking-widest opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none">JSON SCHEMA</div>
                </div>
              </div>

              <div className="flex justify-end space-x-4 pt-4 sticky bottom-0 bg-white dark:bg-slate-800 py-6 border-t border-slate-100 dark:border-slate-700 -mb-8">
                <button 
                  onClick={() => setIsToolModalOpen(false)}
                  className="px-6 py-2.5 text-slate-500 font-semibold hover:text-slate-800 dark:hover:text-slate-200 transition-colors"
                >
                  Cancel
                </button>
                <button 
                  onClick={handleSaveTool}
                  className="px-10 py-2.5 bg-emerald-600 hover:bg-emerald-700 text-white rounded-lg font-bold shadow-lg shadow-emerald-500/20 transition-all hover:scale-[1.02] active:scale-[0.98]"
                >
                  {toolModalMode === 'edit' ? 'Update Tool' : 'Register Tool'}
                </button>
              </div>
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
