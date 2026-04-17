import React, { useEffect, useState } from 'react';
import { KeySquare, AlertTriangle, Plus, Trash2, CheckCircle2 } from 'lucide-react';
import { useApi } from '../api/useApi';
import ConfirmationModal from '../components/Common/ConfirmationModal';

export default function ApiKeys() {
  const api = useApi();
  const [keys, setKeys] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  
  const [showCreate, setShowCreate] = useState(false);
  const [newName, setNewName] = useState('');
  const [newDays, setNewDays] = useState(30);
  const [createdKey, setCreatedKey] = useState(null);

  const [confirmModal, setConfirmModal] = useState({ 
    isOpen: false, 
    title: '', 
    message: '', 
    onConfirm: () => {} 
  });

  const getKeyLabel = (key) => key.label || key.name || '';

  const fetchKeys = async () => {
    try {
      const res = await api.get('/v1/admin/api-keys');
      setKeys(res.data);
      setError(null);
    } catch (err) {
      setError(err.message || 'Failed to fetch API keys');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchKeys();
  }, [api]);

  const handleCreate = async (e) => {
    e.preventDefault();
    try {
      const res = await api.post('/v1/admin/api-keys', {
        label: newName,
        ttl_seconds: parseInt(newDays, 10) ? Math.floor(parseInt(newDays, 10) * 86400) : null
      });
      setCreatedKey(res.data);
      setNewName('');
      setShowCreate(false);
      fetchKeys();
    } catch (err) {
      alert(err.message || 'Failed to create key');
    }
  };

  const handleRevoke = async (keyId, e) => {
    if (e) {
      e.preventDefault();
      e.stopPropagation();
    }
    
    setConfirmModal({
      isOpen: true,
      title: 'Revoke API Key?',
      message: 'Are you sure you want to revoke this API key? Any applications or scripts using this key will immediately lose access.',
      onConfirm: async () => {
        try {
          await api.delete(`/v1/admin/api-keys/${keyId}`);
          fetchKeys();
        } catch (err) {
          alert('Failed to revoke key: ' + err.message);
        }
      }
    });
  };

  if (loading) return <div className="p-8 text-slate-500">Loading API keys...</div>;

  return (
    <div className="p-8 space-y-6 max-w-5xl">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold tracking-tight text-slate-900 dark:text-white">API Keys Management</h1>
        <button 
          onClick={() => setShowCreate(!showCreate)}
          className="bg-blue-500 hover:bg-sky-600 text-white font-medium py-2 px-4 rounded transition-colors inline-flex items-center text-sm gap-2"
        >
          <Plus className="w-4 h-4" /> New API Key
        </button>
      </div>

      {error && (
        <div className="bg-red-50 dark:bg-red-900/20 text-red-500 p-4 rounded-lg flex items-center">
          <AlertTriangle className="w-5 h-5 mr-3" />
          {error}
        </div>
      )}

      {createdKey && createdKey.raw_key && (
        <div className="bg-emerald-50 dark:bg-emerald-900/20 border border-emerald-200 dark:border-emerald-800 text-emerald-900 dark:text-emerald-300 p-6 rounded-xl relative">
          <div className="flex items-start gap-4">
            <CheckCircle2 className="w-6 h-6 text-emerald-500 shrink-0" />
            <div>
              <h3 className="font-bold text-lg mb-2">API Key Created Successfully</h3>
              <p className="mb-4 text-sm">Please copy this highly sensitive key now. You will not be able to see it again.</p>
              <div className="bg-white dark:bg-black/40 px-4 py-3 rounded font-mono text-sm break-all border border-emerald-100 dark:border-emerald-900/50 select-all">
                {createdKey.raw_key}
              </div>
            </div>
          </div>
          <button 
            onClick={() => setCreatedKey(null)}
            className="absolute top-4 right-4 text-emerald-400 hover:text-emerald-600 text-2xl leading-none"
          >
            ×
          </button>
        </div>
      )}

      {showCreate && (
        <div className="bg-white dark:bg-slate-800 border border-slate-200 dark:border-blue-500 shadow-lg shadow-blue-500/10 rounded-xl p-6 mb-6 max-w-md transition-all">
          <h2 className="text-lg font-bold dark:text-white mb-4">Generate New Key</h2>
          <form onSubmit={handleCreate} className="space-y-4">
            <div>
              <label htmlFor="api-key-name" className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1">
                Key Name
              </label>
              <input 
                id="api-key-name"
                type="text" 
                required
                value={newName}
                onChange={e => setNewName(e.target.value)}
                className="w-full bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded px-3 py-2 text-sm dark:text-white focus:outline-none focus:ring-1 focus:ring-[var(--color-blue-500)]"
                placeholder="e.g. CI/CD Pipeline"
              />
            </div>
            <div>
              <label htmlFor="api-key-expiration-days" className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1">
                Expiration (Days)
              </label>
              <input 
                id="api-key-expiration-days"
                type="number" 
                min="1" max="365"
                value={newDays}
                onChange={e => setNewDays(e.target.value)}
                className="w-full bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded px-3 py-2 text-sm dark:text-white focus:outline-none focus:ring-1 focus:ring-[var(--color-blue-500)]"
              />
            </div>
            <div className="flex gap-3 pt-2">
              <button type="submit" className="bg-blue-500 hover:bg-sky-600 text-white py-2 px-4 rounded text-sm font-medium transition-colors">
                Generate
              </button>
              <button type="button" onClick={() => setShowCreate(false)} className="text-slate-500 hover:text-slate-700 dark:hover:text-slate-300 text-sm font-medium">
                Cancel
              </button>
            </div>
          </form>
        </div>
      )}

      <div className="bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 shadow-sm rounded-xl transition-all duration-200 overflow-hidden">
        <table className="w-full text-left text-sm text-slate-600 dark:text-slate-300">
          <thead className="bg-slate-50 dark:bg-slate-800/50 text-xs uppercase text-slate-500 dark:text-slate-400 border-b border-slate-200 dark:border-slate-700/50">
            <tr>
              <th className="px-6 py-4 font-medium">Key Name</th>
              <th className="px-6 py-4 font-medium">Prefix</th>
              <th className="px-6 py-4 font-medium">Created</th>
              <th className="px-6 py-4 font-medium">Expires</th>
              <th className="px-6 py-4 text-right font-medium">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100 dark:divide-slate-800/50">
            {keys.length === 0 ? (
              <tr>
                <td colSpan="5" className="px-6 py-8 text-center text-slate-400">No API keys generated yet.</td>
              </tr>
            ) : keys.map(k => (
              <tr key={k.key_id} className="hover:bg-slate-50/50 dark:hover:bg-slate-800/30 transition-colors">
                <td className="px-6 py-4 font-medium dark:text-slate-200 w-1/3">
                  <div className="flex items-center gap-2">
                    <KeySquare className="w-4 h-4 text-slate-400 shrink-0" />
                    <span className="truncate block" title={getKeyLabel(k)}>
                      {getKeyLabel(k)}
                    </span>
                  </div>
                </td>
                <td className="px-6 py-4 font-mono text-xs text-slate-500">{k.prefix}...</td>
                <td className="px-6 py-4">{new Date(k.created_at).toLocaleDateString()}</td>
                <td className="px-6 py-4">
                  {k.expires_at ? new Date(k.expires_at).toLocaleDateString() : 'Never'}
                </td>
                <td className="px-6 py-4 text-right">
                  <button 
                    type="button"
                    onClick={(e) => handleRevoke(k.key_id, e)}
                    className="text-red-500 hover:text-red-700 dark:text-red-400 dark:hover:text-red-300 transition-colors p-1"
                    title="Revoke Key"
                  >
                    <Trash2 className="w-4 h-4" />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

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
