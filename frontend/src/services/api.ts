import {
  DependencyGraphData,
  FeedEvent,
  Incident,
  InvestigationDetail,
  PlatformStats,
  SystemHealthResponse,
} from '../types';

const API_BASE = '/api/v1';

async function fetchJson<T>(url: string, options?: RequestInit): Promise<T> {
  const res = await fetch(url, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...options?.headers,
    },
  });

  if (!res.ok) {
    let errorDetail = res.statusText;
    try {
      const data = await res.json();
      errorDetail = data.detail || data.message || JSON.stringify(data);
    } catch {
      // ignore json parse error
    }
    throw new Error(`API Error ${res.status}: ${errorDetail}`);
  }

  return res.json();
}

export const api = {
  // Stats & KPIs
  getStats: (): Promise<PlatformStats> =>
    fetchJson<PlatformStats>(`${API_BASE}/stats`),

  // Live Service Health
  getServiceHealth: (): Promise<SystemHealthResponse> =>
    fetchJson<SystemHealthResponse>(`${API_BASE}/health/services`),

  // Event Feed
  getRecentEvents: async (limit: number = 50): Promise<FeedEvent[]> => {
    try {
      const res = await fetchJson<any>(`${API_BASE}/stats/events?limit=${limit}`);
      if (Array.isArray(res)) return res;
      if (res && Array.isArray(res.items)) return res.items;
      return [];
    } catch {
      return [];
    }
  },

  // Incidents
  getIncidents: async (status?: string): Promise<Incident[]> => {
    try {
      const query = status ? `?status=${encodeURIComponent(status)}` : '';
      const res = await fetchJson<any>(`${API_BASE}/incidents${query}`);
      if (Array.isArray(res)) return res;
      if (res && Array.isArray(res.items)) return res.items;
      return [];
    } catch {
      return [];
    }
  },

  getIncidentById: (incidentId: string): Promise<Incident> =>
    fetchJson<Incident>(`${API_BASE}/incidents/${incidentId}`),

  // Autonomous Agent Investigations
  getInvestigation: (incidentId: string): Promise<InvestigationDetail> =>
    fetchJson<InvestigationDetail>(`${API_BASE}/investigations/${incidentId}`),

  triggerInvestigation: (incidentId: string, primaryService?: string): Promise<any> =>
    fetchJson(`${API_BASE}/agent/run`, {
      method: 'POST',
      body: JSON.stringify({
        incident_id: incidentId,
        primary_service: primaryService,
      }),
    }),

  submitApproval: (incidentId: string, approved: boolean, reviewerFeedback?: string): Promise<any> =>
    fetchJson(`${API_BASE}/agent/${incidentId}/approve`, {
      method: 'POST',
      body: JSON.stringify({
        approved,
        reviewer_feedback: reviewerFeedback || (approved ? 'Approved by operator via dashboard.' : 'Rejected by operator.'),
      }),
    }),

  // Repository & Dependency Graph
  getDependencyGraph: (): Promise<DependencyGraphData> =>
    fetchJson<DependencyGraphData>(`${API_BASE}/repositories/dependency-graph`),

  // Code / Symbol Search
  searchRepository: (query: string, service?: string): Promise<any> => {
    const sParam = service ? `&service=${encodeURIComponent(service)}` : '';
    return fetchJson(`${API_BASE}/repositories/search?q=${encodeURIComponent(query)}${sParam}`);
  },
};
