function methodologyBase(organizationId) {
  return `/v1/organizations/${organizationId}/methodology`;
}

function dossierBase(organizationId) {
  return `/v1/organizations/${organizationId}/dossiers`;
}

export async function listMethodologyBlueprints(api, organizationId, statusFilter) {
  const params = statusFilter && statusFilter !== 'active_review'
    ? { status: statusFilter }
    : {};
  const response = await api.get(`${methodologyBase(organizationId)}/blueprints`, {
    params,
  });
  const blueprints = response.data || [];
  if (statusFilter === 'active_review') {
    return blueprints.filter((blueprint) => blueprint.status !== 'archived');
  }
  return blueprints;
}

export async function getMethodologyBlueprint(api, organizationId, blueprintId) {
  const response = await api.get(
    `${methodologyBase(organizationId)}/blueprints/${blueprintId}`,
  );
  return response.data;
}

export async function getMethodologyResearchState(api, organizationId, blueprintId) {
  const response = await api.get(
    `${methodologyBase(organizationId)}/blueprints/${blueprintId}/research-state`,
  );
  return response.data;
}

export async function createMethodologyBlueprint(api, organizationId, payload) {
  const response = await api.post(
    `${methodologyBase(organizationId)}/blueprints`,
    payload,
  );
  return response.data;
}

export async function createMethodologyResearchRequest(api, organizationId, blueprintId, payload) {
  const response = await api.post(
    `${methodologyBase(organizationId)}/blueprints/${blueprintId}/research-requests`,
    payload,
  );
  return response.data;
}

export async function createMethodologyBlueprintVersion(
  api,
  organizationId,
  blueprintId,
  payload,
) {
  const response = await api.post(
    `${methodologyBase(organizationId)}/blueprints/${blueprintId}/versions`,
    payload,
  );
  return response.data;
}

export async function submitMethodologyBlueprintDraft(
  api,
  organizationId,
  blueprintId,
  versionId,
  payload,
) {
  const response = await api.post(
    `${methodologyBase(organizationId)}/blueprints/${blueprintId}/versions/${versionId}/draft`,
    payload,
  );
  return response.data;
}

export async function reviewMethodologyBlueprintVersion({
  api,
  organizationId,
  blueprintId,
  versionId,
  approved,
  payload,
}) {
  const action = approved ? 'approve' : 'reject';
  const response = await api.post(
    `${methodologyBase(organizationId)}/blueprints/${blueprintId}/versions/${versionId}/${action}`,
    payload,
  );
  return response.data;
}

export async function applyMethodologyBlueprint(api, organizationId, blueprintId, payload) {
  const response = await api.post(
    `${methodologyBase(organizationId)}/blueprints/${blueprintId}/apply`,
    payload,
  );
  return response.data;
}

export async function archiveMethodologyBlueprint(api, organizationId, blueprintId, payload) {
  const response = await api.delete(
    `${methodologyBase(organizationId)}/blueprints/${blueprintId}`,
    { data: payload },
  );
  return response.data;
}

export async function getDossierNotebook(api, organizationId, dossierId) {
  const response = await api.get(
    `${dossierBase(organizationId)}/${dossierId}/notebook`,
  );
  return response.data;
}

export async function transitionDossierLifecycle(api, organizationId, dossierId, payload) {
  const response = await api.post(
    `${dossierBase(organizationId)}/${dossierId}/lifecycle`,
    payload,
  );
  return response.data;
}

export async function updateDossierSource(api, organizationId, dossierId, sourceId, payload) {
  const response = await api.patch(
    `${dossierBase(organizationId)}/${dossierId}/sources/${sourceId}`,
    payload,
  );
  return response.data;
}

export async function upsertDossierNote(api, organizationId, dossierId, payload) {
  const response = await api.post(
    `${dossierBase(organizationId)}/${dossierId}/notes`,
    payload,
  );
  return response.data;
}

export async function upsertDossierConcept(api, organizationId, dossierId, payload) {
  const response = await api.post(
    `${dossierBase(organizationId)}/${dossierId}/concepts`,
    payload,
  );
  return response.data;
}

export async function upsertDossierClaim(api, organizationId, dossierId, payload) {
  const response = await api.post(
    `${dossierBase(organizationId)}/${dossierId}/claims`,
    payload,
  );
  return response.data;
}

export async function upsertDossierLink(api, organizationId, dossierId, payload) {
  const response = await api.post(
    `${dossierBase(organizationId)}/${dossierId}/links`,
    payload,
  );
  return response.data;
}

export async function answerInteractionRequest(api, requestId, payload) {
  const response = await api.post(`/v1/requests/${requestId}/answers`, payload);
  return response.data;
}
