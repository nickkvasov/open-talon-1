import React, { useEffect, useState } from 'react';
import { Building2, Plus, Users, AlertTriangle, Trash2 } from 'lucide-react';
import { useApi } from '../api/useApi';
import { buildAdminActor } from '../config/adminActor';

export default function Organizations() {
  const api = useApi();
  const [organizations, setOrganizations] = useState([]);
  const [selectedOrganizationId, setSelectedOrganizationId] = useState('');
  const [memberships, setMemberships] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [formData, setFormData] = useState({
    slug: '',
    name: '',
    description: '',
    metadata: '{}',
  });
  const [membershipForm, setMembershipForm] = useState({
    user_id: '',
    role: 'member',
    metadata: '{}',
  });

  const fetchOrganizations = async () => {
    try {
      setLoading(true);
      const res = await api.get('/v1/organizations');
      setOrganizations(res.data);
      if (!selectedOrganizationId && res.data.length > 0) {
        setSelectedOrganizationId(res.data[0].organization_id);
      }
      setError(null);
    } catch (err) {
      setError(err.message || 'Failed to fetch organizations');
    } finally {
      setLoading(false);
    }
  };

  const fetchMemberships = async (organizationId) => {
    if (!organizationId) {
      setMemberships([]);
      return;
    }
    try {
      const res = await api.get(`/v1/organizations/${organizationId}/members`);
      setMemberships(res.data);
    } catch (err) {
      setError(err.message || 'Failed to fetch organization memberships');
    }
  };

  useEffect(() => {
    void fetchOrganizations();
  }, [api]);

  useEffect(() => {
    void fetchMemberships(selectedOrganizationId);
  }, [api, selectedOrganizationId]);

  const handleCreate = async (event) => {
    event.preventDefault();
    try {
      await api.post('/v1/organizations', {
        actor: buildAdminActor(),
        slug: formData.slug,
        name: formData.name,
        description: formData.description || null,
        metadata: JSON.parse(formData.metadata || '{}'),
      });
      setFormData({
        slug: '',
        name: '',
        description: '',
        metadata: '{}',
      });
      await fetchOrganizations();
    } catch (err) {
      alert('Failed to create organization: ' + err.message);
    }
  };

  const handleAddMember = async (event) => {
    event.preventDefault();
    if (!selectedOrganizationId) {
      alert('Select an organization first.');
      return;
    }
    try {
      await api.post(`/v1/organizations/${selectedOrganizationId}/members`, {
        actor: buildAdminActor(),
        user_id: membershipForm.user_id,
        role: membershipForm.role,
        metadata: JSON.parse(membershipForm.metadata || '{}'),
      });
      setMembershipForm({
        user_id: '',
        role: 'member',
        metadata: '{}',
      });
      await fetchMemberships(selectedOrganizationId);
    } catch (err) {
      alert('Failed to add organization member: ' + err.message);
    }
  };

  const handleRemoveMember = async (userId) => {
    if (!selectedOrganizationId) {
      return;
    }
    try {
      await api.delete(`/v1/organizations/${selectedOrganizationId}/members/${userId}`, {
        data: {
          actor: buildAdminActor(),
          metadata: {},
        },
      });
      await fetchMemberships(selectedOrganizationId);
    } catch (err) {
      alert('Failed to remove organization member: ' + err.message);
    }
  };

  if (loading) return <div className="p-8 text-slate-500">Loading organizations...</div>;

  const selectedOrganization = organizations.find(
    (organization) => organization.organization_id === selectedOrganizationId
  ) || null;

  return (
    <div className="p-8 space-y-6">
      <div className="bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 shadow-sm p-6 rounded-xl flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-900 dark:text-white flex items-center gap-3">
            <Building2 className="w-6 h-6 text-blue-500" />
            Organizations
          </h1>
          <p className="text-slate-500 mt-1">Manage the tenant layer that owns projects, workspaces, and org-scoped resources.</p>
        </div>
      </div>

      {error && (
        <div className="bg-rose-50 dark:bg-rose-900/20 text-rose-600 dark:text-rose-400 p-4 rounded-lg flex items-center border border-rose-200 dark:border-rose-800">
          <AlertTriangle className="w-5 h-5 mr-3" />
          {error}
        </div>
      )}

      <div className="grid grid-cols-1 xl:grid-cols-[2fr,1fr] gap-6">
        <div className="bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 shadow-sm rounded-xl overflow-hidden">
          <div className="px-6 py-4 border-b border-slate-200 dark:border-slate-700">
            <h2 className="text-lg font-semibold text-slate-900 dark:text-white">Active Organizations</h2>
          </div>
          <div className="divide-y divide-slate-200 dark:divide-slate-700">
            {organizations.map((organization) => (
              <button
                key={organization.organization_id}
                type="button"
                onClick={() => setSelectedOrganizationId(organization.organization_id)}
                className={`w-full px-6 py-4 flex items-start justify-between gap-4 text-left ${selectedOrganizationId === organization.organization_id ? 'bg-blue-50 dark:bg-blue-900/20' : 'hover:bg-slate-50 dark:hover:bg-slate-700/30'}`}
              >
                <div>
                  <div className="font-semibold text-slate-900 dark:text-white">{organization.name}</div>
                  <div className="text-sm text-slate-500 dark:text-slate-400">{organization.description || 'No description'}</div>
                </div>
                <div className="text-right">
                  <div className="text-xs font-mono text-blue-500">{organization.slug}</div>
                  <div className="text-xs text-slate-400 mt-1">{organization.organization_id.slice(0, 8)}</div>
                </div>
              </button>
            ))}
            {organizations.length === 0 && (
              <div className="px-6 py-8 text-sm text-slate-500">No organizations yet.</div>
            )}
          </div>
        </div>

        <div className="space-y-6">
          <form onSubmit={handleCreate} className="bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 shadow-sm rounded-xl p-6 space-y-4">
            <div className="flex items-center gap-2 text-slate-900 dark:text-white font-semibold">
              <Plus className="w-4 h-4 text-blue-500" />
              Create Organization
            </div>
            <div>
              <label className="block text-sm font-medium text-slate-600 dark:text-slate-300 mb-1">Slug</label>
              <input value={formData.slug} onChange={(e) => setFormData({ ...formData, slug: e.target.value })} className="w-full rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 px-3 py-2 text-sm" required />
            </div>
            <div>
              <label className="block text-sm font-medium text-slate-600 dark:text-slate-300 mb-1">Name</label>
              <input value={formData.name} onChange={(e) => setFormData({ ...formData, name: e.target.value })} className="w-full rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 px-3 py-2 text-sm" required />
            </div>
            <div>
              <label className="block text-sm font-medium text-slate-600 dark:text-slate-300 mb-1">Description</label>
              <textarea value={formData.description} onChange={(e) => setFormData({ ...formData, description: e.target.value })} className="w-full rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 px-3 py-2 text-sm min-h-24" />
            </div>
            <div>
              <label className="block text-sm font-medium text-slate-600 dark:text-slate-300 mb-1">Metadata JSON</label>
              <textarea value={formData.metadata} onChange={(e) => setFormData({ ...formData, metadata: e.target.value })} className="w-full rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 px-3 py-2 text-sm min-h-24 font-mono" />
            </div>
            <button type="submit" className="w-full bg-blue-600 hover:bg-blue-700 text-white px-4 py-2 rounded-lg flex items-center justify-center gap-2">
              <Users className="w-4 h-4" />
              Create
            </button>
          </form>

          <div className="bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 shadow-sm rounded-xl p-6 space-y-4">
            <div>
              <div className="flex items-center gap-2 text-slate-900 dark:text-white font-semibold">
                <Users className="w-4 h-4 text-blue-500" />
                Organization Memberships
              </div>
              <p className="text-sm text-slate-500 mt-1">
                {selectedOrganization ? `Manage members in ${selectedOrganization.name}.` : 'Select an organization to manage its members.'}
              </p>
            </div>

            <form onSubmit={handleAddMember} className="space-y-3">
              <div>
                <label className="block text-sm font-medium text-slate-600 dark:text-slate-300 mb-1">User ID</label>
                <input value={membershipForm.user_id} onChange={(e) => setMembershipForm({ ...membershipForm, user_id: e.target.value })} className="w-full rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 px-3 py-2 text-sm font-mono" disabled={!selectedOrganization} required />
              </div>
              <div>
                <label className="block text-sm font-medium text-slate-600 dark:text-slate-300 mb-1">Role</label>
                <select value={membershipForm.role} onChange={(e) => setMembershipForm({ ...membershipForm, role: e.target.value })} className="w-full rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 px-3 py-2 text-sm" disabled={!selectedOrganization}>
                  <option value="owner">owner</option>
                  <option value="admin">admin</option>
                  <option value="member">member</option>
                </select>
              </div>
              <div>
                <label className="block text-sm font-medium text-slate-600 dark:text-slate-300 mb-1">Metadata JSON</label>
                <textarea value={membershipForm.metadata} onChange={(e) => setMembershipForm({ ...membershipForm, metadata: e.target.value })} className="w-full rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 px-3 py-2 text-sm min-h-20 font-mono" disabled={!selectedOrganization} />
              </div>
              <button type="submit" disabled={!selectedOrganization} className="w-full bg-slate-900 dark:bg-slate-100 text-white dark:text-slate-900 px-4 py-2 rounded-lg disabled:opacity-50">
                Add Member
              </button>
            </form>

            <div className="divide-y divide-slate-200 dark:divide-slate-700 border border-slate-200 dark:border-slate-700 rounded-lg overflow-hidden">
              {memberships.map((membership) => (
                <div key={membership.user_id} className="px-4 py-3 flex items-center justify-between gap-3">
                  <div>
                    <div className="font-mono text-xs text-slate-500">{membership.user_id}</div>
                    <div className="text-sm font-medium text-slate-900 dark:text-white">{membership.role}</div>
                  </div>
                  <button type="button" onClick={() => handleRemoveMember(membership.user_id)} className="p-2 text-slate-400 hover:text-rose-500 hover:bg-rose-50 dark:hover:bg-rose-900/30 rounded-lg transition-all">
                    <Trash2 className="w-4 h-4" />
                  </button>
                </div>
              ))}
              {memberships.length === 0 && (
                <div className="px-4 py-6 text-sm text-slate-500">
                  {selectedOrganization ? 'No members found for this organization.' : 'Select an organization to view memberships.'}
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
