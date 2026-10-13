export class ApiError extends Error {
  constructor(message, status = 0) {
    super(message || "AccessSprint could not complete that request.");
    this.name = "ApiError";
    this.status = status;
  }
}

export async function request(path, options = {}, fetchImpl = globalThis.fetch) {
  const headers = { ...(options.headers || {}) };
  let body = options.body;
  if (body !== undefined && body !== null && typeof body !== "string") {
    body = JSON.stringify(body);
    headers["Content-Type"] = headers["Content-Type"] || "application/json";
  }
  let response;
  try {
    response = await fetchImpl(path, { ...options, headers, body });
  } catch (error) {
    throw new ApiError("AccessSprint could not reach its local server. Keep the launcher open and retry.", 0);
  }
  if (response.status === 204) return null;
  let payload;
  try {
    payload = await response.json();
  } catch {
    payload = {};
  }
  if (!response.ok) throw new ApiError(payload.error || `Request failed with status ${response.status}.`, response.status);
  return payload;
}

export const api = {
  health: () => request("/api/health"),
  settings: () => request("/api/settings"),
  saveSettings: settings => request("/api/settings", { method: "POST", body: settings }),
  testModel: () => request("/api/ai/test", { method: "POST", body: {} }),
  listAudits: async ({ includeArchived = false } = {}) => (await request(`/api/audits${includeArchived ? "?include_archived=1" : ""}`)).audits,
  getAudit: async id => (await request(`/api/audits/${encodeURIComponent(id)}`)).audit,
  createAudit: async payload => (await request("/api/audits", { method: "POST", body: payload })).audit,
  updateAudit: async (id, payload) => (await request(`/api/audits/${encodeURIComponent(id)}`, { method: "PATCH", body: payload })).audit,
  deleteAudit: id => request(`/api/audits/${encodeURIComponent(id)}`, { method: "DELETE" }),
  archiveAudit: (id, archived) => request(`/api/audits/${encodeURIComponent(id)}/archive`, { method: "POST", body: { archived } }),
  startScan: async id => (await request(`/api/audits/${encodeURIComponent(id)}/scans`, { method: "POST", body: {} })).scan,
  getScan: async id => (await request(`/api/scans/${encodeURIComponent(id)}`)).scan,
  compareScans: async (auditId, baselineId, currentId) => {
    const query = new URLSearchParams({ baseline: baselineId, current: currentId });
    return (await request(`/api/audits/${encodeURIComponent(auditId)}/scans/compare?${query}`)).comparison;
  },
  reviewFinding: async (auditId, findingId, changes) =>
    (await request(`/api/audits/${encodeURIComponent(auditId)}/findings/${encodeURIComponent(findingId)}`,
      { method: "PATCH", body: changes })).finding,
  updateManualCheck: async (auditId, checkId, changes) =>
    (await request(`/api/audits/${encodeURIComponent(auditId)}/manual-checks/${encodeURIComponent(checkId)}`,
      { method: "PATCH", body: changes })).manual_check,
  explainFinding: async (auditId, findingId) =>
    (await request("/api/ai/explain", { method: "POST", body: { audit_id: auditId, finding_id: findingId } })).result,
  report: async id => (await request(`/api/audits/${encodeURIComponent(id)}/report`)).report,
  exportBackup: async id => (await request(`/api/audits/${encodeURIComponent(id)}/backup`)).backup,
  importBackup: async backup => (await request("/api/backups/import", { method: "POST", body: backup })).audit,
};
