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
  // dateRange: optional { startDate, endDate } - the backend
  // (webapi/server.py AskRequest/ReportRequest) has always accepted
  // start_date/end_date and can even span multiple pool folders
  // (load_period_streaming), but the frontend never sent them. Any
  // question scoped to a specific day or range only worked from the CLI
  // until now.
  runReport: (kind, pool, dateRange) =>
    request("/api/report", {
      method: "POST",
      body: JSON.stringify({
        kind,
        pool,
        start_date: dateRange?.startDate || null,
        end_date: dateRange?.endDate || null,
      }),
    }),
  ask: (query, pool, dateRange) =>
    request("/api/ask", {
      method: "POST",
      body: JSON.stringify({
        query,
        pool,
        start_date: dateRange?.startDate || null,
        end_date: dateRange?.endDate || null,
      }),
    }),
  reportFileUrl: (reportId, fmt) => `${BASE}/api/reports/${reportId}/${fmt}`,
};
