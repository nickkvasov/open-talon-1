import React, { useEffect, useState } from 'react';
import { Activity, AlertTriangle, Database, ActivitySquare, Clock } from 'lucide-react';
import { useApi } from '../api/useApi';

export default function Dashboard() {
  const api = useApi();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    let active = true;
    const fetchOverview = async () => {
      try {
        const res = await api.get('/v1/admin/runtime/overview');
        if (active) {
          setData(res.data);
          setError(null);
          setLoading(false);
        }
      } catch (err) {
        if (active) {
          setError(err.message || 'Failed to fetch runtime overview');
          setLoading(false);
        }
      }
    };
    fetchOverview();
    const interval = setInterval(fetchOverview, 5000);
    return () => {
      active = false;
      clearInterval(interval);
    };
  }, [api]);

  if (loading && !data) return <div className="p-8 text-slate-500">Loading overview...</div>;
  
  return (
    <div className="p-8 space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold tracking-tight text-slate-900 dark:text-white">Runtime Overview</h1>
      </div>
      
      {error && (
        <div className="bg-red-50 dark:bg-red-900/20 text-red-500 p-4 rounded-lg flex items-center">
          <AlertTriangle className="w-5 h-5 mr-3" />
          {error}
        </div>
      )}

      {data && (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          {/* Token Usage Card */}
          <div className="bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 shadow-sm p-6 rounded-xl">
            <div className="flex items-center space-x-3 text-slate-500 dark:text-slate-400 mb-4">
              <Database className="w-5 h-5" />
              <h3 className="font-medium">Total Token Usage</h3>
            </div>
            <p className="text-4xl font-bold text-slate-800 dark:text-white">
              {data.token_totals?.global_total_tokens?.toLocaleString() || 0}
            </p>
            <div className="mt-4 space-y-2">
              {data.token_totals?.by_workspace?.map((ws) => (
                <div key={ws.workspace_id} className="flex justify-between text-sm border-b border-slate-100 dark:border-slate-800 pb-1 last:border-0">
                  <span className="text-slate-500 truncate w-32" title={ws.workspace_id}>{ws.workspace_id.slice(0, 8)}...</span>
                  <span className="font-medium dark:text-slate-200">{ws.total_tokens.toLocaleString()}</span>
                </div>
              ))}
              {(!data.token_totals?.by_workspace || data.token_totals.by_workspace.length === 0) && (
                <div className="text-sm text-slate-400 italic">No workspace token data yet.</div>
              )}
            </div>
          </div>

          {/* Queues Card */}
          <div className="bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 shadow-sm p-6 rounded-xl">
            <div className="flex items-center space-x-3 text-slate-500 dark:text-slate-400 mb-4">
              <ActivitySquare className="w-5 h-5" />
              <h3 className="font-medium">Active Queues</h3>
            </div>
            <div className="space-y-4">
              <div className="flex justify-between items-center">
                <span className="text-slate-600 dark:text-slate-300">Tasks</span>
                <span className="font-bold dark:text-white">{data.tasks?.pending || 0} / {data.tasks?.claimed || 0}</span>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-slate-600 dark:text-slate-300">Run Steps</span>
                <span className="font-bold dark:text-white">{data.run_steps?.pending || 0} / {data.run_steps?.claimed || 0}</span>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-slate-600 dark:text-slate-300">Tool Calls</span>
                <span className="font-bold dark:text-white">{data.tool_calls?.pending || 0} / {data.tool_calls?.claimed || 0}</span>
              </div>
            </div>
          </div>

          {/* Failures Card */}
          <div className="bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 shadow-sm p-6 rounded-xl border-red-200 dark:border-red-900/50">
            <div className="flex items-center space-x-3 text-red-500 mb-4">
              <AlertTriangle className="w-5 h-5" />
              <h3 className="font-medium">Failed Executions (24h)</h3>
            </div>
            <div className="space-y-4">
              <div className="flex justify-between items-center">
                <span className="text-slate-600 dark:text-slate-300">Tasks</span>
                <span className="font-bold text-red-600 dark:text-red-400">{data.failed_last_24h?.tasks || 0}</span>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-slate-600 dark:text-slate-300">Run Steps</span>
                <span className="font-bold text-red-600 dark:text-red-400">{data.failed_last_24h?.run_steps || 0}</span>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-slate-600 dark:text-slate-300">Tool Calls</span>
                <span className="font-bold text-red-600 dark:text-red-400">{data.failed_last_24h?.tool_calls || 0}</span>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
