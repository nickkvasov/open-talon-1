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
import { buildAdminActor } from '../config/adminActor';

const defaultAgentData = () => ({
  display_name: '', description: '', role: 'assistant', capabilities: 'execute_code',
  endpoint_kind: 'local', endpoint_model: '', endpoint_provider: '',
  system_prompt: 'You are a helpful assistant.', instructions: '', completion_criteria: '',
  harness_summary: '',
  operating_principles: '[]',
  planning_guidance: '[]',
  planning_plan_before_act: true,
  planning_incremental_execution: true,
  planning_one_goal_at_a_time: true,
  planning_explicit_uncertainty: true,
  tool_selection_principles: '[]',
  tool_read_before_write: true,
  tool_inspect_schema_before_use: true,
  tool_prefer_existing_workspace_tools: true,
  tool_cite_tool_results_in_reasoning: true,
  tool_verify_side_effects_after_mutation: true,
  tool_fallback_when_no_tool_fits: '',
  memory_use_run_memory: true,
  memory_use_thread_memory: true,
  memory_use_workspace_memory: true,
  compaction_enabled: true,
  compaction_strategy: 'full_context',
  compaction_overflow_behavior: 'auto_fallback',
  compaction_max_estimated_input_tokens: 12000,
  compaction_recent_message_count: 12,
  compaction_min_recent_message_count: 4,
  compaction_max_run_memory_entries: 6,
  compaction_max_thread_memory_entries: 6,
  compaction_max_workspace_memory_entries: 6,
  compaction_summary_max_chars: 3000,
  compaction_retrieval_limit: 5,
  compaction_retrieval_provider_key: '',
  collaboration_ask_user_when: '[]',
  collaboration_escalate_when: '[]',
  collaboration_delegation_guidance: '[]',
  collaboration_handoff_guidance: '[]',
  validation_required_checks: '[]',
  validation_require_evidence_for_claims: true,
  validation_require_tool_results_for_completion: false,
  validation_require_tests_before_done: false,
  stop_completion_conditions: '[]',
  stop_stop_conditions: '[]',
  stop_max_turns: '',
  skill_refs: '[]'
});

export default function SwarmResources() {
  const api = useApi();
  const [agents, setAgents] = useState([]);
  const [tools, setTools] = useState([]);
  const [organizations, setOrganizations] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [scopeMode, setScopeMode] = useState('global');
  const [selectedOrganizationId, setSelectedOrganizationId] = useState('');

  // Modal states
  const [isAgentModalOpen, setIsAgentModalOpen] = useState(false);
  const [isToolModalOpen, setIsToolModalOpen] = useState(false);
  const [agentModalMode, setAgentModalMode] = useState('create');
  const [toolModalMode, setToolModalMode] = useState('create');
  const [editingAgent, setEditingAgent] = useState(null);
  const [editingTool, setEditingTool] = useState(null);
  
  const [agentData, setAgentData] = useState(defaultAgentData());

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

  const fetchResources = async () => {
    try {
      setLoading(true);
      if (scopeMode === 'organization' && !selectedOrganizationId) {
        setAgents([]);
        setTools([]);
        setError(null);
        return;
      }
      const agentsEndpoint =
        scopeMode === 'organization'
          ? `/v1/organizations/${selectedOrganizationId}/agents`
          : '/v1/agents';
      const toolsEndpoint =
        scopeMode === 'organization'
          ? `/v1/organizations/${selectedOrganizationId}/tools`
          : '/v1/tools';
      const [agentsRes, toolsRes] = await Promise.all([
        api.get(agentsEndpoint),
        api.get(toolsEndpoint)
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
    void fetchOrganizations();
  }, [api]);

  useEffect(() => {
    if (scopeMode === 'organization' && !selectedOrganizationId && organizations.length === 1) {
      setSelectedOrganizationId(organizations[0].organization_id);
    }
  }, [organizations, scopeMode, selectedOrganizationId]);

  useEffect(() => {
    void fetchResources();
  }, [api, scopeMode, selectedOrganizationId]);

  const resetAgentForm = () => {
    setAgentData(defaultAgentData());
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
    const harness = agent.harness || {};
    const planning = harness.planning || {};
    const toolUsePolicy = harness.tool_use_policy || {};
    const memoryPolicy = harness.memory_policy || {};
    const compactionPolicy = harness.compaction_policy || {};
    const collaborationPolicy = harness.collaboration_policy || {};
    const validationPolicy = harness.validation_policy || {};
    const stopPolicy = harness.stop_policy || {};
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
      completion_criteria: agent.interaction_contract?.completion_criteria?.join(', ') || '',
      harness_summary: harness.summary || '',
      operating_principles: JSON.stringify(harness.operating_principles || [], null, 2),
      planning_guidance: JSON.stringify(planning.guidance || [], null, 2),
      planning_plan_before_act: planning.plan_before_act ?? true,
      planning_incremental_execution: planning.incremental_execution ?? true,
      planning_one_goal_at_a_time: planning.one_goal_at_a_time ?? true,
      planning_explicit_uncertainty: planning.explicit_uncertainty ?? true,
      tool_selection_principles: JSON.stringify(toolUsePolicy.selection_principles || [], null, 2),
      tool_read_before_write: toolUsePolicy.read_before_write ?? true,
      tool_inspect_schema_before_use: toolUsePolicy.inspect_schema_before_use ?? true,
      tool_prefer_existing_workspace_tools: toolUsePolicy.prefer_existing_workspace_tools ?? true,
      tool_cite_tool_results_in_reasoning: toolUsePolicy.cite_tool_results_in_reasoning ?? true,
      tool_verify_side_effects_after_mutation: toolUsePolicy.verify_side_effects_after_mutation ?? true,
      tool_fallback_when_no_tool_fits: toolUsePolicy.fallback_when_no_tool_fits || '',
      memory_use_run_memory: memoryPolicy.use_run_memory ?? true,
      memory_use_thread_memory: memoryPolicy.use_thread_memory ?? true,
      memory_use_workspace_memory: memoryPolicy.use_workspace_memory ?? true,
      compaction_enabled: compactionPolicy.enabled ?? true,
      compaction_strategy: compactionPolicy.strategy || 'full_context',
      compaction_overflow_behavior: compactionPolicy.overflow_behavior || 'auto_fallback',
      compaction_max_estimated_input_tokens: compactionPolicy.max_estimated_input_tokens ?? 12000,
      compaction_recent_message_count: compactionPolicy.recent_message_count ?? 12,
      compaction_min_recent_message_count: compactionPolicy.min_recent_message_count ?? 4,
      compaction_max_run_memory_entries: compactionPolicy.max_run_memory_entries ?? 6,
      compaction_max_thread_memory_entries: compactionPolicy.max_thread_memory_entries ?? 6,
      compaction_max_workspace_memory_entries: compactionPolicy.max_workspace_memory_entries ?? 6,
      compaction_summary_max_chars: compactionPolicy.summary_max_chars ?? 3000,
      compaction_retrieval_limit: compactionPolicy.retrieval_limit ?? 5,
      compaction_retrieval_provider_key: compactionPolicy.retrieval_provider_key || '',
      collaboration_ask_user_when: JSON.stringify(collaborationPolicy.ask_user_when || [], null, 2),
      collaboration_escalate_when: JSON.stringify(collaborationPolicy.escalate_when || [], null, 2),
      collaboration_delegation_guidance: JSON.stringify(collaborationPolicy.delegation_guidance || [], null, 2),
      collaboration_handoff_guidance: JSON.stringify(collaborationPolicy.handoff_guidance || [], null, 2),
      validation_required_checks: JSON.stringify(validationPolicy.required_checks || [], null, 2),
      validation_require_evidence_for_claims: validationPolicy.require_evidence_for_claims ?? true,
      validation_require_tool_results_for_completion: validationPolicy.require_tool_results_for_completion ?? false,
      validation_require_tests_before_done: validationPolicy.require_tests_before_done ?? false,
      stop_completion_conditions: JSON.stringify(stopPolicy.completion_conditions || [], null, 2),
      stop_stop_conditions: JSON.stringify(stopPolicy.stop_conditions || [], null, 2),
      stop_max_turns: stopPolicy.max_turns != null ? String(stopPolicy.max_turns) : '',
      skill_refs: JSON.stringify(harness.skill_refs || [], null, 2),
    });
    setIsAgentModalOpen(true);
  };

  const parseJsonField = (raw, fallback, label) => {
    if (!raw.trim()) {
      return fallback;
    }
    try {
      return JSON.parse(raw);
    } catch {
      throw new Error(`${label} must be valid JSON`);
    }
  };

  const buildAgentHarness = () => {
    const operatingPrinciples = parseJsonField(agentData.operating_principles, [], 'Operating principles');
    const planningGuidance = parseJsonField(agentData.planning_guidance, [], 'Planning guidance');
    const toolSelectionPrinciples = parseJsonField(agentData.tool_selection_principles, [], 'Tool selection principles');
    const askUserWhen = parseJsonField(agentData.collaboration_ask_user_when, [], 'Ask-user guidance');
    const escalateWhen = parseJsonField(agentData.collaboration_escalate_when, [], 'Escalation guidance');
    const delegationGuidance = parseJsonField(agentData.collaboration_delegation_guidance, [], 'Delegation guidance');
    const handoffGuidance = parseJsonField(agentData.collaboration_handoff_guidance, [], 'Handoff guidance');
    const requiredChecks = parseJsonField(agentData.validation_required_checks, [], 'Validation checks');
    const completionConditions = parseJsonField(agentData.stop_completion_conditions, [], 'Completion conditions');
    const stopConditions = parseJsonField(agentData.stop_stop_conditions, [], 'Stop conditions');
    const skillRefs = parseJsonField(agentData.skill_refs, [], 'Skill refs');
    const retrievalProviderKey = agentData.compaction_strategy === 'summary_plus_retrieval'
      ? agentData.compaction_retrieval_provider_key.trim() || null
      : null;
    const planningDefaults = agentData.planning_plan_before_act
      && agentData.planning_incremental_execution
      && agentData.planning_one_goal_at_a_time
      && agentData.planning_explicit_uncertainty;
    const toolDefaults = agentData.tool_read_before_write
      && agentData.tool_inspect_schema_before_use
      && agentData.tool_prefer_existing_workspace_tools
      && agentData.tool_cite_tool_results_in_reasoning
      && agentData.tool_verify_side_effects_after_mutation;
    const memoryDefaults = agentData.memory_use_run_memory
      && agentData.memory_use_thread_memory
      && agentData.memory_use_workspace_memory;
    const compactionDefaults = agentData.compaction_enabled
      && agentData.compaction_strategy === 'full_context'
      && agentData.compaction_overflow_behavior === 'auto_fallback'
      && agentData.compaction_max_estimated_input_tokens === 12000
      && agentData.compaction_recent_message_count === 12
      && agentData.compaction_min_recent_message_count === 4
      && agentData.compaction_max_run_memory_entries === 6
      && agentData.compaction_max_thread_memory_entries === 6
      && agentData.compaction_max_workspace_memory_entries === 6
      && agentData.compaction_summary_max_chars === 3000
      && agentData.compaction_retrieval_limit === 5
      && !retrievalProviderKey;
    const validationDefaults = agentData.validation_require_evidence_for_claims
      && !agentData.validation_require_tool_results_for_completion
      && !agentData.validation_require_tests_before_done;
    const hasHarness = Boolean(
      agentData.harness_summary.trim()
      || operatingPrinciples.length
      || planningGuidance.length
      || !planningDefaults
      || toolSelectionPrinciples.length
      || !toolDefaults
      || agentData.tool_fallback_when_no_tool_fits.trim()
      || !memoryDefaults
      || !compactionDefaults
      || askUserWhen.length
      || escalateWhen.length
      || delegationGuidance.length
      || handoffGuidance.length
      || requiredChecks.length
      || !validationDefaults
      || completionConditions.length
      || stopConditions.length
      || agentData.stop_max_turns.trim()
      || skillRefs.length
    );
    if (!hasHarness) {
      return null;
    }
    return {
      version: 1,
      summary: agentData.harness_summary.trim() || null,
      operating_principles: operatingPrinciples,
      planning: {
        plan_before_act: agentData.planning_plan_before_act,
        incremental_execution: agentData.planning_incremental_execution,
        one_goal_at_a_time: agentData.planning_one_goal_at_a_time,
        explicit_uncertainty: agentData.planning_explicit_uncertainty,
        guidance: planningGuidance,
      },
      tool_use_policy: {
        selection_principles: toolSelectionPrinciples,
        read_before_write: agentData.tool_read_before_write,
        inspect_schema_before_use: agentData.tool_inspect_schema_before_use,
        prefer_existing_workspace_tools: agentData.tool_prefer_existing_workspace_tools,
        cite_tool_results_in_reasoning: agentData.tool_cite_tool_results_in_reasoning,
        verify_side_effects_after_mutation: agentData.tool_verify_side_effects_after_mutation,
        fallback_when_no_tool_fits: agentData.tool_fallback_when_no_tool_fits.trim() || null,
      },
      memory_policy: {
        use_run_memory: agentData.memory_use_run_memory,
        use_thread_memory: agentData.memory_use_thread_memory,
        use_workspace_memory: agentData.memory_use_workspace_memory,
      },
      compaction_policy: {
        enabled: agentData.compaction_enabled,
        strategy: agentData.compaction_strategy,
        overflow_behavior: agentData.compaction_overflow_behavior,
        max_estimated_input_tokens: agentData.compaction_max_estimated_input_tokens,
        recent_message_count: agentData.compaction_recent_message_count,
        min_recent_message_count: agentData.compaction_min_recent_message_count,
        max_run_memory_entries: agentData.compaction_max_run_memory_entries,
        max_thread_memory_entries: agentData.compaction_max_thread_memory_entries,
        max_workspace_memory_entries: agentData.compaction_max_workspace_memory_entries,
        summary_max_chars: agentData.compaction_summary_max_chars,
        retrieval_limit: agentData.compaction_retrieval_limit,
        retrieval_provider_key: retrievalProviderKey,
      },
      collaboration_policy: {
        ask_user_when: askUserWhen,
        escalate_when: escalateWhen,
        delegation_guidance: delegationGuidance,
        handoff_guidance: handoffGuidance,
      },
      validation_policy: {
        required_checks: requiredChecks,
        require_evidence_for_claims: agentData.validation_require_evidence_for_claims,
        require_tool_results_for_completion: agentData.validation_require_tool_results_for_completion,
        require_tests_before_done: agentData.validation_require_tests_before_done,
      },
      stop_policy: {
        completion_conditions: completionConditions,
        stop_conditions: stopConditions,
        max_turns: agentData.stop_max_turns.trim() ? Number(agentData.stop_max_turns) : null,
      },
      skill_refs: skillRefs,
      metadata: {},
    };
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
              actor: buildAdminActor()
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
              actor: buildAdminActor()
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
        actor: buildAdminActor(),
        display_name: agentData.display_name,
        description: agentData.description,
        role: agentData.role,
        capabilities: agentData.capabilities.split(',').map(s => s.trim()).filter(Boolean),
        endpoint: { kind: agentData.endpoint_kind, model: agentData.endpoint_model || null, provider: agentData.endpoint_provider || null },
        system_prompt: agentData.system_prompt,
        harness: buildAgentHarness(),
        interaction_contract: {
          instructions: agentData.instructions.split(',').map(s => s.trim()).filter(Boolean),
          completion_criteria: agentData.completion_criteria.split(',').map(s => s.trim()).filter(Boolean),
          response_contract: { content_type: 'text/markdown', json_mode: false }
        }
      };

      if (agentModalMode === 'create') {
        if (scopeMode === 'organization' && !selectedOrganizationId) {
          throw new Error('Select an organization before creating an org-scoped agent.');
        }
        await api.post(
          scopeMode === 'organization'
            ? `/v1/organizations/${selectedOrganizationId}/agents`
            : '/v1/agents',
          payload
        );
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
        actor: buildAdminActor(),
        name: toolData.name,
        description: toolData.description,
        parameter_contract: { strategy: toolData.param_strategy },
        input_schema: JSON.parse(toolSchema),
        execution: { strategy: toolData.exec_strategy, config: toolData.exec_url ? { url: toolData.exec_url } : {} }
      };

      if (toolModalMode === 'create') {
        if (scopeMode === 'organization' && !selectedOrganizationId) {
          throw new Error('Select an organization before creating an org-scoped tool.');
        }
        await api.post(
          scopeMode === 'organization'
            ? `/v1/organizations/${selectedOrganizationId}/tools`
            : '/v1/tools',
          payload
        );
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
          <p className="text-slate-500 mt-1">
            Manage {scopeMode === 'organization' ? 'organization-scoped' : 'platform-global'} agent and tool definitions
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
                      <span className="text-[10px] bg-slate-100 dark:bg-slate-700 text-slate-500 px-2 py-0.5 rounded-full uppercase tracking-tight">
                        {agent.scope || 'global'}
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
                      <span className="text-[10px] bg-slate-100 dark:bg-slate-700 text-slate-500 px-2 py-0.5 rounded-full uppercase tracking-tight">
                        {tool.scope || 'global'}
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

              <div className="space-y-4">
                <h4 className="text-xs font-bold text-slate-400 uppercase tracking-widest border-b border-slate-100 dark:border-slate-700 pb-2">
                  Agent Harness
                </h4>
                <div className="p-6 bg-slate-50 dark:bg-slate-900 rounded-xl border border-slate-100 dark:border-slate-700 space-y-6">
                  <div>
                    <label className="block text-sm font-semibold text-slate-700 dark:text-slate-300 mb-1.5">Harness Summary</label>
                    <textarea
                      value={agentData.harness_summary}
                      onChange={e => setAgentData({...agentData, harness_summary: e.target.value})}
                      rows={2}
                      className="w-full bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg px-4 py-2.5 focus:ring-2 focus:ring-blue-500 outline-none transition-all text-sm resize-none"
                      placeholder="Operational scaffold for this agent..."
                    />
                  </div>
                  <div>
                    <label className="block text-sm font-semibold text-slate-700 dark:text-slate-300 mb-1.5 font-mono">Operating Principles (JSON array)</label>
                    <textarea
                      value={agentData.operating_principles}
                      onChange={e => setAgentData({...agentData, operating_principles: e.target.value})}
                      rows={4}
                      className="w-full bg-slate-950 border border-slate-800 rounded-lg px-4 py-3 font-mono text-xs text-cyan-300 focus:ring-2 focus:ring-blue-500 outline-none resize-none"
                    />
                  </div>
                  <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                    <div className="space-y-3">
                      <h5 className="text-sm font-bold text-slate-900 dark:text-white">Planning Policy</h5>
                      <div className="grid grid-cols-2 gap-2 text-sm text-slate-600 dark:text-slate-300">
                        <label className="flex items-center gap-2"><input type="checkbox" checked={agentData.planning_plan_before_act} onChange={e => setAgentData({...agentData, planning_plan_before_act: e.target.checked})} />Plan before act</label>
                        <label className="flex items-center gap-2"><input type="checkbox" checked={agentData.planning_incremental_execution} onChange={e => setAgentData({...agentData, planning_incremental_execution: e.target.checked})} />Incremental execution</label>
                        <label className="flex items-center gap-2"><input type="checkbox" checked={agentData.planning_one_goal_at_a_time} onChange={e => setAgentData({...agentData, planning_one_goal_at_a_time: e.target.checked})} />One goal at a time</label>
                        <label className="flex items-center gap-2"><input type="checkbox" checked={agentData.planning_explicit_uncertainty} onChange={e => setAgentData({...agentData, planning_explicit_uncertainty: e.target.checked})} />Explicit uncertainty</label>
                      </div>
                      <label className="block text-sm font-semibold text-slate-700 dark:text-slate-300 mb-1.5 font-mono">Planning Guidance (JSON array)</label>
                      <textarea
                        value={agentData.planning_guidance}
                        onChange={e => setAgentData({...agentData, planning_guidance: e.target.value})}
                        rows={5}
                        className="w-full bg-slate-950 border border-slate-800 rounded-lg px-4 py-3 font-mono text-xs text-cyan-300 focus:ring-2 focus:ring-blue-500 outline-none resize-none"
                      />
                    </div>
                    <div className="space-y-3">
                      <h5 className="text-sm font-bold text-slate-900 dark:text-white">Tool-Use Policy</h5>
                      <div className="grid grid-cols-1 gap-2 text-sm text-slate-600 dark:text-slate-300">
                        <label className="flex items-center gap-2"><input type="checkbox" checked={agentData.tool_read_before_write} onChange={e => setAgentData({...agentData, tool_read_before_write: e.target.checked})} />Read before write</label>
                        <label className="flex items-center gap-2"><input type="checkbox" checked={agentData.tool_inspect_schema_before_use} onChange={e => setAgentData({...agentData, tool_inspect_schema_before_use: e.target.checked})} />Inspect schema before use</label>
                        <label className="flex items-center gap-2"><input type="checkbox" checked={agentData.tool_prefer_existing_workspace_tools} onChange={e => setAgentData({...agentData, tool_prefer_existing_workspace_tools: e.target.checked})} />Prefer existing workspace tools</label>
                        <label className="flex items-center gap-2"><input type="checkbox" checked={agentData.tool_cite_tool_results_in_reasoning} onChange={e => setAgentData({...agentData, tool_cite_tool_results_in_reasoning: e.target.checked})} />Cite tool results in reasoning</label>
                        <label className="flex items-center gap-2"><input type="checkbox" checked={agentData.tool_verify_side_effects_after_mutation} onChange={e => setAgentData({...agentData, tool_verify_side_effects_after_mutation: e.target.checked})} />Verify side effects after mutation</label>
                      </div>
                      <label className="block text-sm font-semibold text-slate-700 dark:text-slate-300 mb-1.5 font-mono">Selection Principles (JSON array)</label>
                      <textarea
                        value={agentData.tool_selection_principles}
                        onChange={e => setAgentData({...agentData, tool_selection_principles: e.target.value})}
                        rows={4}
                        className="w-full bg-slate-950 border border-slate-800 rounded-lg px-4 py-3 font-mono text-xs text-cyan-300 focus:ring-2 focus:ring-blue-500 outline-none resize-none"
                      />
                      <label className="block text-sm font-semibold text-slate-700 dark:text-slate-300 mb-1.5">Fallback When No Tool Fits</label>
                      <textarea
                        value={agentData.tool_fallback_when_no_tool_fits}
                        onChange={e => setAgentData({...agentData, tool_fallback_when_no_tool_fits: e.target.value})}
                        rows={2}
                        className="w-full bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg px-4 py-2.5 focus:ring-2 focus:ring-blue-500 outline-none transition-all text-sm resize-none"
                      />
                    </div>
                  </div>
                  <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                    <div className="space-y-3">
                      <h5 className="text-sm font-bold text-slate-900 dark:text-white">Memory Policy</h5>
                      <div className="grid grid-cols-1 gap-2 text-sm text-slate-600 dark:text-slate-300">
                        <label className="flex items-center gap-2"><input type="checkbox" checked={agentData.memory_use_run_memory} onChange={e => setAgentData({...agentData, memory_use_run_memory: e.target.checked})} />Use run memory</label>
                        <label className="flex items-center gap-2"><input type="checkbox" checked={agentData.memory_use_thread_memory} onChange={e => setAgentData({...agentData, memory_use_thread_memory: e.target.checked})} />Use thread memory</label>
                        <label className="flex items-center gap-2"><input type="checkbox" checked={agentData.memory_use_workspace_memory} onChange={e => setAgentData({...agentData, memory_use_workspace_memory: e.target.checked})} />Use workspace memory</label>
                      </div>
                      <h5 className="pt-2 text-sm font-bold text-slate-900 dark:text-white">Compaction Policy</h5>
                      <div className="space-y-4 rounded-xl border border-slate-200 bg-white p-4 dark:border-slate-700 dark:bg-slate-800">
                        <label className="flex items-center gap-2 text-sm text-slate-600 dark:text-slate-300">
                          <input
                            type="checkbox"
                            checked={agentData.compaction_enabled}
                            onChange={e => setAgentData({...agentData, compaction_enabled: e.target.checked})}
                          />
                          Enable context compaction
                        </label>
                        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                          <div>
                            <label className="mb-1.5 block text-sm font-semibold text-slate-700 dark:text-slate-300">Preset</label>
                            <select
                              value={agentData.compaction_strategy}
                              onChange={e => setAgentData({...agentData, compaction_strategy: e.target.value})}
                              className="w-full rounded-lg border border-slate-200 bg-slate-50 px-4 py-2.5 text-sm outline-none transition-all focus:ring-2 focus:ring-blue-500 dark:border-slate-700 dark:bg-slate-900"
                            >
                              <option value="full_context">full_context</option>
                              <option value="recent_window">recent_window</option>
                              <option value="rolling_summary">rolling_summary</option>
                              <option value="summary_plus_retrieval">summary_plus_retrieval</option>
                            </select>
                          </div>
                          <div>
                            <label className="mb-1.5 block text-sm font-semibold text-slate-700 dark:text-slate-300">Overflow Behavior</label>
                            <select
                              value={agentData.compaction_overflow_behavior}
                              onChange={e => setAgentData({...agentData, compaction_overflow_behavior: e.target.value})}
                              className="w-full rounded-lg border border-slate-200 bg-slate-50 px-4 py-2.5 text-sm outline-none transition-all focus:ring-2 focus:ring-blue-500 dark:border-slate-700 dark:bg-slate-900"
                            >
                              <option value="auto_fallback">auto_fallback</option>
                            </select>
                          </div>
                        </div>
                        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                          <div>
                            <label className="mb-1.5 block text-sm font-semibold text-slate-700 dark:text-slate-300">Max Estimated Input Tokens</label>
                            <input type="number" min="1" value={agentData.compaction_max_estimated_input_tokens} onChange={e => setAgentData({...agentData, compaction_max_estimated_input_tokens: Number(e.target.value)})} className="w-full rounded-lg border border-slate-200 bg-slate-50 px-4 py-2.5 text-sm outline-none transition-all focus:ring-2 focus:ring-blue-500 dark:border-slate-700 dark:bg-slate-900" />
                          </div>
                          <div>
                            <label className="mb-1.5 block text-sm font-semibold text-slate-700 dark:text-slate-300">Recent Message Count</label>
                            <input type="number" min="0" value={agentData.compaction_recent_message_count} onChange={e => setAgentData({...agentData, compaction_recent_message_count: Number(e.target.value)})} className="w-full rounded-lg border border-slate-200 bg-slate-50 px-4 py-2.5 text-sm outline-none transition-all focus:ring-2 focus:ring-blue-500 dark:border-slate-700 dark:bg-slate-900" />
                          </div>
                          <div>
                            <label className="mb-1.5 block text-sm font-semibold text-slate-700 dark:text-slate-300">Minimum Recent Messages</label>
                            <input type="number" min="0" value={agentData.compaction_min_recent_message_count} onChange={e => setAgentData({...agentData, compaction_min_recent_message_count: Number(e.target.value)})} className="w-full rounded-lg border border-slate-200 bg-slate-50 px-4 py-2.5 text-sm outline-none transition-all focus:ring-2 focus:ring-blue-500 dark:border-slate-700 dark:bg-slate-900" />
                          </div>
                          <div>
                            <label className="mb-1.5 block text-sm font-semibold text-slate-700 dark:text-slate-300">Max Run Memory Entries</label>
                            <input type="number" min="0" value={agentData.compaction_max_run_memory_entries} onChange={e => setAgentData({...agentData, compaction_max_run_memory_entries: Number(e.target.value)})} className="w-full rounded-lg border border-slate-200 bg-slate-50 px-4 py-2.5 text-sm outline-none transition-all focus:ring-2 focus:ring-blue-500 dark:border-slate-700 dark:bg-slate-900" />
                          </div>
                          <div>
                            <label className="mb-1.5 block text-sm font-semibold text-slate-700 dark:text-slate-300">Max Thread Memory Entries</label>
                            <input type="number" min="0" value={agentData.compaction_max_thread_memory_entries} onChange={e => setAgentData({...agentData, compaction_max_thread_memory_entries: Number(e.target.value)})} className="w-full rounded-lg border border-slate-200 bg-slate-50 px-4 py-2.5 text-sm outline-none transition-all focus:ring-2 focus:ring-blue-500 dark:border-slate-700 dark:bg-slate-900" />
                          </div>
                          <div>
                            <label className="mb-1.5 block text-sm font-semibold text-slate-700 dark:text-slate-300">Max Workspace Memory Entries</label>
                            <input type="number" min="0" value={agentData.compaction_max_workspace_memory_entries} onChange={e => setAgentData({...agentData, compaction_max_workspace_memory_entries: Number(e.target.value)})} className="w-full rounded-lg border border-slate-200 bg-slate-50 px-4 py-2.5 text-sm outline-none transition-all focus:ring-2 focus:ring-blue-500 dark:border-slate-700 dark:bg-slate-900" />
                          </div>
                          <div>
                            <label className="mb-1.5 block text-sm font-semibold text-slate-700 dark:text-slate-300">Summary Max Chars</label>
                            <input type="number" min="1" value={agentData.compaction_summary_max_chars} onChange={e => setAgentData({...agentData, compaction_summary_max_chars: Number(e.target.value)})} className="w-full rounded-lg border border-slate-200 bg-slate-50 px-4 py-2.5 text-sm outline-none transition-all focus:ring-2 focus:ring-blue-500 dark:border-slate-700 dark:bg-slate-900" />
                          </div>
                          <div>
                            <label className="mb-1.5 block text-sm font-semibold text-slate-700 dark:text-slate-300">Retrieval Limit</label>
                            <input type="number" min="0" value={agentData.compaction_retrieval_limit} onChange={e => setAgentData({...agentData, compaction_retrieval_limit: Number(e.target.value)})} className="w-full rounded-lg border border-slate-200 bg-slate-50 px-4 py-2.5 text-sm outline-none transition-all focus:ring-2 focus:ring-blue-500 dark:border-slate-700 dark:bg-slate-900" />
                          </div>
                        </div>
                        {agentData.compaction_strategy === 'summary_plus_retrieval' && (
                          <div>
                            <label className="mb-1.5 block text-sm font-semibold text-slate-700 dark:text-slate-300">Retrieval Provider Key</label>
                            <input
                              type="text"
                              value={agentData.compaction_retrieval_provider_key}
                              onChange={e => setAgentData({...agentData, compaction_retrieval_provider_key: e.target.value})}
                              className="w-full rounded-lg border border-slate-200 bg-slate-50 px-4 py-2.5 text-sm outline-none transition-all focus:ring-2 focus:ring-blue-500 dark:border-slate-700 dark:bg-slate-900"
                              placeholder="Leave blank to use the default thread-memory provider"
                            />
                          </div>
                        )}
                      </div>
                      <h5 className="pt-2 text-sm font-bold text-slate-900 dark:text-white">Validation Policy</h5>
                      <div className="grid grid-cols-1 gap-2 text-sm text-slate-600 dark:text-slate-300">
                        <label className="flex items-center gap-2"><input type="checkbox" checked={agentData.validation_require_evidence_for_claims} onChange={e => setAgentData({...agentData, validation_require_evidence_for_claims: e.target.checked})} />Require evidence for claims</label>
                        <label className="flex items-center gap-2"><input type="checkbox" checked={agentData.validation_require_tool_results_for_completion} onChange={e => setAgentData({...agentData, validation_require_tool_results_for_completion: e.target.checked})} />Require tool results for completion</label>
                        <label className="flex items-center gap-2"><input type="checkbox" checked={agentData.validation_require_tests_before_done} onChange={e => setAgentData({...agentData, validation_require_tests_before_done: e.target.checked})} />Require tests before done</label>
                      </div>
                      <label className="block text-sm font-semibold text-slate-700 dark:text-slate-300 mb-1.5 font-mono">Required Checks (JSON array)</label>
                      <textarea
                        value={agentData.validation_required_checks}
                        onChange={e => setAgentData({...agentData, validation_required_checks: e.target.value})}
                        rows={4}
                        className="w-full bg-slate-950 border border-slate-800 rounded-lg px-4 py-3 font-mono text-xs text-cyan-300 focus:ring-2 focus:ring-blue-500 outline-none resize-none"
                      />
                    </div>
                    <div className="space-y-3">
                      <h5 className="text-sm font-bold text-slate-900 dark:text-white">Collaboration and Stop Policies</h5>
                      <label className="block text-sm font-semibold text-slate-700 dark:text-slate-300 mb-1.5 font-mono">Ask User When (JSON array)</label>
                      <textarea value={agentData.collaboration_ask_user_when} onChange={e => setAgentData({...agentData, collaboration_ask_user_when: e.target.value})} rows={3} className="w-full bg-slate-950 border border-slate-800 rounded-lg px-4 py-3 font-mono text-xs text-cyan-300 focus:ring-2 focus:ring-blue-500 outline-none resize-none" />
                      <label className="block text-sm font-semibold text-slate-700 dark:text-slate-300 mb-1.5 font-mono">Escalate When (JSON array)</label>
                      <textarea value={agentData.collaboration_escalate_when} onChange={e => setAgentData({...agentData, collaboration_escalate_when: e.target.value})} rows={3} className="w-full bg-slate-950 border border-slate-800 rounded-lg px-4 py-3 font-mono text-xs text-cyan-300 focus:ring-2 focus:ring-blue-500 outline-none resize-none" />
                      <label className="block text-sm font-semibold text-slate-700 dark:text-slate-300 mb-1.5 font-mono">Delegation Guidance (JSON array)</label>
                      <textarea value={agentData.collaboration_delegation_guidance} onChange={e => setAgentData({...agentData, collaboration_delegation_guidance: e.target.value})} rows={3} className="w-full bg-slate-950 border border-slate-800 rounded-lg px-4 py-3 font-mono text-xs text-cyan-300 focus:ring-2 focus:ring-blue-500 outline-none resize-none" />
                      <label className="block text-sm font-semibold text-slate-700 dark:text-slate-300 mb-1.5 font-mono">Handoff Guidance (JSON array)</label>
                      <textarea value={agentData.collaboration_handoff_guidance} onChange={e => setAgentData({...agentData, collaboration_handoff_guidance: e.target.value})} rows={3} className="w-full bg-slate-950 border border-slate-800 rounded-lg px-4 py-3 font-mono text-xs text-cyan-300 focus:ring-2 focus:ring-blue-500 outline-none resize-none" />
                      <label className="block text-sm font-semibold text-slate-700 dark:text-slate-300 mb-1.5 font-mono">Completion Conditions (JSON array)</label>
                      <textarea value={agentData.stop_completion_conditions} onChange={e => setAgentData({...agentData, stop_completion_conditions: e.target.value})} rows={3} className="w-full bg-slate-950 border border-slate-800 rounded-lg px-4 py-3 font-mono text-xs text-cyan-300 focus:ring-2 focus:ring-blue-500 outline-none resize-none" />
                      <label className="block text-sm font-semibold text-slate-700 dark:text-slate-300 mb-1.5 font-mono">Stop Conditions (JSON array)</label>
                      <textarea value={agentData.stop_stop_conditions} onChange={e => setAgentData({...agentData, stop_stop_conditions: e.target.value})} rows={3} className="w-full bg-slate-950 border border-slate-800 rounded-lg px-4 py-3 font-mono text-xs text-cyan-300 focus:ring-2 focus:ring-blue-500 outline-none resize-none" />
                      <label className="block text-sm font-semibold text-slate-700 dark:text-slate-300 mb-1.5">Max Turns</label>
                      <input
                        type="number"
                        min="1"
                        value={agentData.stop_max_turns}
                        onChange={e => setAgentData({...agentData, stop_max_turns: e.target.value})}
                        className="w-full bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg px-4 py-2.5 focus:ring-2 focus:ring-blue-500 outline-none transition-all text-sm"
                      />
                      <label className="block text-sm font-semibold text-slate-700 dark:text-slate-300 mb-1.5 font-mono">Skill Refs (JSON array)</label>
                      <textarea value={agentData.skill_refs} onChange={e => setAgentData({...agentData, skill_refs: e.target.value})} rows={3} className="w-full bg-slate-950 border border-slate-800 rounded-lg px-4 py-3 font-mono text-xs text-cyan-300 focus:ring-2 focus:ring-blue-500 outline-none resize-none" />
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
