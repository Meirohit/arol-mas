const BASE = import.meta.env.VITE_API_BASE || "";

async function request(path, options) {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `Request failed (${res.status})`);
  }
  return res.json();
}

export const api = {
  getPools: () => request("/api/pools"),
  getPresets: () => request("/api/presets"),
  getTools: () => request("/api/tools"),
  validate: (pool) => request(`/api/validate?pool=${encodeURIComponent(pool)}`),
  runReport: (kind, pool) =>
    request("/api/report", { method: "POST", body: JSON.stringify({ kind, pool }) }),
  ask: (query, pool) =>
    request("/api/ask", { method: "POST", body: JSON.stringify({ query, pool }) }),
  reportFileUrl: (reportId, fmt) => `${BASE}/api/reports/${reportId}/${fmt}`,
};
