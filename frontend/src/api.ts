import type { Incident, Stats, FilterOptions, Filters } from './types';

const API_BASE = '/api';

export async function fetchIncidents(filters: Filters): Promise<{ incidents: Incident[]; total: number }> {
  const params = new URLSearchParams();

  if (filters.tiers.length > 0) {
    params.set('tiers', filters.tiers.join(','));
  }
  if (filters.states.length > 0) {
    params.set('states', filters.states.join(','));
  }
  if (filters.categories.length > 0) {
    params.set('categories', filters.categories.join(','));
  }
  if (filters.non_immigrant_only) {
    params.set('non_immigrant_only', 'true');
  }
  if (filters.date_start) {
    params.set('date_start', filters.date_start);
  }
  if (filters.date_end) {
    params.set('date_end', filters.date_end);
  }

  const response = await fetch(`${API_BASE}/incidents?${params}`);
  return response.json();
}

export async function fetchStats(filters: Filters): Promise<Stats> {
  const params = new URLSearchParams();

  if (filters.tiers.length > 0) {
    params.set('tiers', filters.tiers.join(','));
  }
  if (filters.states.length > 0) {
    params.set('states', filters.states.join(','));
  }
  if (filters.non_immigrant_only) {
    params.set('non_immigrant_only', 'true');
  }

  const response = await fetch(`${API_BASE}/stats?${params}`);
  return response.json();
}

export async function fetchFilterOptions(): Promise<FilterOptions> {
  const response = await fetch(`${API_BASE}/filters`);
  return response.json();
}
