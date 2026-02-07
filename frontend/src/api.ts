import type {
  Incident,
  Stats,
  FilterOptions,
  Filters,
  AdminStatus,
  PipelineResult,
  CurationQueueItem,
  ComparisonStats,
  Person,
  DomainSummary,
  EventListItem,
  IncidentConnections,
  QueueMetrics,
  ExtractionStatus,
} from './types';

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
  if (filters.date_start) {
    params.set('date_start', filters.date_start);
  }
  if (filters.date_end) {
    params.set('date_end', filters.date_end);
  }
  if (filters.domain) {
    params.set('domain', filters.domain);
  }
  if (filters.category) {
    params.set('event_category', filters.category);
  }
  if (filters.severity) {
    params.set('severity', filters.severity);
  }
  // Unified filters
  if (filters.incident_category) {
    params.set('category', filters.incident_category);
  }
  if (filters.incident_types && filters.incident_types.length > 0) {
    params.set('incident_types', filters.incident_types.join(','));
  }
  if (filters.gang_affiliated !== undefined) {
    params.set('gang_affiliated', String(filters.gang_affiliated));
  }
  if (filters.prior_deportations_min !== undefined) {
    params.set('prior_deportations_min', String(filters.prior_deportations_min));
  }
  if (filters.search) {
    params.set('search', filters.search);
  }
  if (filters.event_id) {
    params.set('event_id', filters.event_id);
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
  if (filters.date_start) {
    params.set('date_start', filters.date_start);
  }
  if (filters.date_end) {
    params.set('date_end', filters.date_end);
  }
  if (filters.domain) {
    params.set('domain', filters.domain);
  }
  if (filters.category) {
    params.set('event_category', filters.category);
  }
  if (filters.severity) {
    params.set('severity', filters.severity);
  }
  if (filters.event_id) {
    params.set('event_id', filters.event_id);
  }
  // Category filter
  if (filters.incident_category) {
    params.set('category', filters.incident_category);
  }

  const response = await fetch(`${API_BASE}/stats?${params}`);
  return response.json();
}

export async function fetchFilterOptions(): Promise<FilterOptions> {
  const response = await fetch(`${API_BASE}/filters`);
  return response.json();
}

// Domain summary for filter dropdowns
export async function fetchDomainsSummary(): Promise<{ domains: DomainSummary[] }> {
  const response = await fetch(`${API_BASE}/domains-summary`);
  return response.json();
}

// Event list for filter dropdown
export async function fetchEventList(): Promise<EventListItem[]> {
  const response = await fetch(`${API_BASE}/events?limit=200`);
  return response.json();
}

// Incident connections (event siblings + duplicate links)
export async function fetchIncidentConnections(incidentId: string): Promise<IncidentConnections> {
  const response = await fetch(`${API_BASE}/incidents/${incidentId}/connections`);
  if (!response.ok) throw new Error('Failed to fetch connections');
  return response.json();
}

// Admin API functions
export async function fetchAdminStatus(): Promise<AdminStatus> {
  const response = await fetch(`${API_BASE}/admin/status`);
  return response.json();
}

export async function runPipelineFetch(source?: string, forceRefresh = false): Promise<PipelineResult> {
  const params = new URLSearchParams();
  if (source) params.set('source', source);
  if (forceRefresh) params.set('force_refresh', 'true');

  const response = await fetch(`${API_BASE}/admin/pipeline/fetch?${params}`, {
    method: 'POST',
  });
  return response.json();
}

export async function runPipelineProcess(): Promise<PipelineResult> {
  const response = await fetch(`${API_BASE}/admin/pipeline/process`, {
    method: 'POST',
  });
  return response.json();
}

export async function runFullPipeline(forceRefresh = false): Promise<PipelineResult> {
  const params = new URLSearchParams();
  if (forceRefresh) params.set('force_refresh', 'true');

  const response = await fetch(`${API_BASE}/admin/pipeline/run?${params}`, {
    method: 'POST',
  });
  return response.json();
}

// Curation Queue API functions
export async function fetchCurationQueue(status = 'pending'): Promise<{ items: CurationQueueItem[]; total: number }> {
  const response = await fetch(`${API_BASE}/admin/queue?status=${status}`);
  return response.json();
}

export async function approveArticle(articleId: string, overrides?: Record<string, unknown>): Promise<{ success: boolean; incident_id?: string }> {
  const response = await fetch(`${API_BASE}/admin/queue/${articleId}/approve`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ overrides }),
  });
  return response.json();
}

export async function rejectArticle(articleId: string, reason: string): Promise<{ success: boolean }> {
  const response = await fetch(`${API_BASE}/admin/queue/${articleId}/reject`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ reason }),
  });
  return response.json();
}

// Analytics API functions
export async function fetchComparisonStats(dateStart?: string, dateEnd?: string): Promise<ComparisonStats> {
  const params = new URLSearchParams();
  if (dateStart) params.set('date_start', dateStart);
  if (dateEnd) params.set('date_end', dateEnd);

  const response = await fetch(`${API_BASE}/stats/comparison?${params}`);
  return response.json();
}

export async function fetchSanctuaryCorrelation(dateStart?: string, dateEnd?: string): Promise<Record<string, unknown>> {
  const params = new URLSearchParams();
  if (dateStart) params.set('date_start', dateStart);
  if (dateEnd) params.set('date_end', dateEnd);

  const response = await fetch(`${API_BASE}/stats/sanctuary?${params}`);
  return response.json();
}

// Person API functions
export async function fetchPersons(params?: { role?: string; gang_affiliated?: boolean; limit?: number }): Promise<{ persons: Person[]; total: number }> {
  const searchParams = new URLSearchParams();
  if (params?.role) searchParams.set('role', params.role);
  if (params?.gang_affiliated !== undefined) searchParams.set('gang_affiliated', String(params.gang_affiliated));
  if (params?.limit) searchParams.set('limit', String(params.limit));

  const response = await fetch(`${API_BASE}/persons?${searchParams}`);
  return response.json();
}

export async function fetchPerson(personId: string): Promise<Person> {
  const response = await fetch(`${API_BASE}/persons/${personId}`);
  return response.json();
}

// Health check
export async function checkHealth(): Promise<{ status: string; database: string }> {
  const response = await fetch(`${API_BASE}/health`);
  return response.json();
}

// Queue stats for sidebar
export async function fetchQueueStats(): Promise<{ pending: number; in_review: number; approved: number; rejected: number }> {
  const [pending, approved, rejected] = await Promise.all([
    fetch(`${API_BASE}/admin/queue?status=pending`).then(r => r.json()),
    fetch(`${API_BASE}/admin/queue?status=approved&limit=1`).then(r => r.json()).catch(() => ({ total: 0 })),
    fetch(`${API_BASE}/admin/queue?status=rejected&limit=1`).then(r => r.json()).catch(() => ({ total: 0 })),
  ]);
  return {
    pending: pending.total || 0,
    in_review: 0, // Will be added when we track this
    approved: approved.total || 0,
    rejected: rejected.total || 0,
  };
}

// Pipeline config for sidebar
export async function fetchPipelineConfig(): Promise<Record<string, unknown>> {
  const response = await fetch(`${API_BASE}/admin/pipeline/config`);
  return response.json();
}

// LLM extraction status
export async function fetchLLMStatus(): Promise<{ available: boolean; model: string | null }> {
  const response = await fetch(`${API_BASE}/admin/llm-extraction/status`);
  return response.json();
}

// Submit article for curation
export async function submitArticle(data: { url: string; title?: string; content: string; source_name?: string; run_extraction?: boolean }): Promise<{ success: boolean; article_id?: string; extraction_result?: unknown }> {
  const response = await fetch(`${API_BASE}/admin/queue/submit`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
  return response.json();
}

// Check duplicate
export async function checkDuplicate(article: Record<string, unknown>): Promise<{ is_duplicate: boolean; match_type?: string; confidence?: number }> {
  const response = await fetch(`${API_BASE}/admin/duplicates/check`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ article }),
  });
  return response.json();
}

// Settings API functions
export async function fetchSettings(): Promise<Record<string, unknown>> {
  const response = await fetch(`${API_BASE}/admin/settings`);
  return response.json();
}

export async function fetchAutoApprovalSettings(): Promise<Record<string, unknown>> {
  const response = await fetch(`${API_BASE}/admin/settings/auto-approval`);
  return response.json();
}

export async function updateAutoApprovalSettings(config: Record<string, unknown>): Promise<Record<string, unknown>> {
  const response = await fetch(`${API_BASE}/admin/settings/auto-approval`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(config),
  });
  return response.json();
}

export async function fetchDuplicateSettings(): Promise<Record<string, unknown>> {
  const response = await fetch(`${API_BASE}/admin/settings/duplicate`);
  return response.json();
}

export async function updateDuplicateSettings(config: Record<string, unknown>): Promise<Record<string, unknown>> {
  const response = await fetch(`${API_BASE}/admin/settings/duplicate`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(config),
  });
  return response.json();
}

export async function fetchPipelineSettings(): Promise<Record<string, unknown>> {
  const response = await fetch(`${API_BASE}/admin/settings/pipeline`);
  return response.json();
}

export async function updatePipelineSettings(config: Record<string, unknown>): Promise<Record<string, unknown>> {
  const response = await fetch(`${API_BASE}/admin/settings/pipeline`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(config),
  });
  return response.json();
}

// Incident Browser API functions
export async function fetchAdminIncidents(params: {
  category?: string;
  state?: string;
  search?: string;
  date_start?: string;
  date_end?: string;
  page?: number;
  page_size?: number;
}): Promise<{ incidents: unknown[]; total: number; page: number; total_pages: number }> {
  const searchParams = new URLSearchParams();
  if (params.category) searchParams.set('category', params.category);
  if (params.state) searchParams.set('state', params.state);
  if (params.search) searchParams.set('search', params.search);
  if (params.date_start) searchParams.set('date_start', params.date_start);
  if (params.date_end) searchParams.set('date_end', params.date_end);
  if (params.page) searchParams.set('page', String(params.page));
  if (params.page_size) searchParams.set('page_size', String(params.page_size));

  const response = await fetch(`${API_BASE}/admin/incidents?${searchParams}`);
  return response.json();
}

export async function fetchAdminIncident(incidentId: string): Promise<unknown> {
  const response = await fetch(`${API_BASE}/admin/incidents/${incidentId}`);
  return response.json();
}

export async function updateIncident(incidentId: string, updates: Record<string, unknown>): Promise<{ success: boolean }> {
  const response = await fetch(`${API_BASE}/admin/incidents/${incidentId}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(updates),
  });
  return response.json();
}

export async function deleteIncident(incidentId: string, hardDelete = false): Promise<{ success: boolean }> {
  const params = new URLSearchParams();
  if (hardDelete) params.set('hard_delete', 'true');
  const response = await fetch(`${API_BASE}/admin/incidents/${incidentId}?${params}`, {
    method: 'DELETE',
  });
  return response.json();
}

export async function exportIncidents(params: {
  format?: 'json' | 'csv';
  category?: string;
  state?: string;
  date_start?: string;
  date_end?: string;
}): Promise<Response> {
  const searchParams = new URLSearchParams();
  if (params.format) searchParams.set('format', params.format);
  if (params.category) searchParams.set('category', params.category);
  if (params.state) searchParams.set('state', params.state);
  if (params.date_start) searchParams.set('date_start', params.date_start);
  if (params.date_end) searchParams.set('date_end', params.date_end);

  return fetch(`${API_BASE}/admin/incidents/export?${searchParams}`);
}

// Job Queue API functions
export async function fetchJobs(status?: string, limit = 50): Promise<{ jobs: unknown[]; total: number }> {
  const params = new URLSearchParams();
  if (status) params.set('status', status);
  params.set('limit', String(limit));

  const response = await fetch(`${API_BASE}/admin/jobs?${params}`);
  return response.json();
}

export async function createJob(jobType: string, jobParams?: Record<string, unknown>): Promise<{ success: boolean; job_id?: string }> {
  const response = await fetch(`${API_BASE}/admin/jobs`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ job_type: jobType, params: jobParams }),
  });
  return response.json();
}

export async function fetchJob(jobId: string): Promise<unknown> {
  const response = await fetch(`${API_BASE}/admin/jobs/${jobId}`);
  return response.json();
}

export async function cancelJob(jobId: string): Promise<{ success: boolean }> {
  const response = await fetch(`${API_BASE}/admin/jobs/${jobId}`, {
    method: 'DELETE',
  });
  return response.json();
}

// Tiered Queue API functions
export async function fetchTieredQueue(category?: string): Promise<{ high: unknown[]; medium: unknown[]; low: unknown[] }> {
  const params = new URLSearchParams();
  if (category) params.set('category', category);

  const response = await fetch(`${API_BASE}/admin/queue/tiered?${params}`);
  return response.json();
}

export async function bulkApprove(tier: string, category?: string, limit = 50): Promise<{ success: boolean; approved_count: number; incident_ids: string[] }> {
  const response = await fetch(`${API_BASE}/admin/queue/bulk-approve`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ tier, category, limit }),
  });
  return response.json();
}

export async function bulkReject(tier: string, reason: string, category?: string, limit = 50): Promise<{ success: boolean; rejected_count: number }> {
  const response = await fetch(`${API_BASE}/admin/queue/bulk-reject`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ tier, reason, category, limit }),
  });
  return response.json();
}

export async function fetchAISuggestions(articleId: string): Promise<{ article_id: string; suggestions: unknown[] }> {
  const response = await fetch(`${API_BASE}/admin/queue/${articleId}/suggestions`);
  return response.json();
}

// Extraction status and batch operations
export async function fetchExtractionStatus(): Promise<ExtractionStatus> {
  const response = await fetch(`${API_BASE}/admin/queue/extraction-status`);
  return response.json();
}

export interface BatchResult {
  success: boolean;
  processed?: number;
  extracted?: number;
  relevant?: number;
  not_relevant?: number;
  errors?: number;
  extract_recommended?: number;
  reject_recommended?: number;
  review_recommended?: number;
  auto_rejected?: number;
  rejected_count?: number;
  auto_approved?: number;
  needs_review?: number;
  items?: Array<{
    id: string;
    title: string;
    is_relevant?: boolean;
    confidence?: number;
    category?: string;
    error?: string;
  }>;
  error?: string;
  approved?: number;
  approved_count?: number;
}

export async function runBatchExtract(limit: number): Promise<BatchResult> {
  const response = await fetch(`${API_BASE}/admin/queue/batch-extract`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ limit }),
  });
  return response.json();
}

export async function runTriage(limit: number, autoReject = false): Promise<BatchResult> {
  const response = await fetch(`${API_BASE}/admin/queue/triage`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ limit, auto_reject: autoReject }),
  });
  return response.json();
}

export async function runAutoApprove(limit: number): Promise<BatchResult> {
  const response = await fetch(`${API_BASE}/admin/queue/auto-approve`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ limit }),
  });
  return response.json();
}

export async function rejectNotRelevant(): Promise<BatchResult> {
  const response = await fetch(`${API_BASE}/admin/queue/bulk-reject-by-criteria`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ reject_not_relevant: true }),
  });
  return response.json();
}

export async function upgradeSchema(limit: number): Promise<BatchResult> {
  const response = await fetch(`${API_BASE}/admin/queue/batch-extract`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ limit, re_extract: true }),
  });
  return response.json();
}

// Analytics API functions
export async function fetchAnalyticsOverview(dateStart?: string, dateEnd?: string): Promise<Record<string, unknown>> {
  const params = new URLSearchParams();
  if (dateStart) params.set('date_start', dateStart);
  if (dateEnd) params.set('date_end', dateEnd);

  const response = await fetch(`${API_BASE}/admin/analytics/overview?${params}`);
  return response.json();
}

export async function fetchConversionFunnel(dateStart?: string, dateEnd?: string): Promise<{ funnel: unknown[]; rejected: number; pending: number }> {
  const params = new URLSearchParams();
  if (dateStart) params.set('date_start', dateStart);
  if (dateEnd) params.set('date_end', dateEnd);

  const response = await fetch(`${API_BASE}/admin/analytics/conversion?${params}`);
  return response.json();
}

export async function fetchSourceAnalytics(dateStart?: string, dateEnd?: string): Promise<{ sources: unknown[] }> {
  const params = new URLSearchParams();
  if (dateStart) params.set('date_start', dateStart);
  if (dateEnd) params.set('date_end', dateEnd);

  const response = await fetch(`${API_BASE}/admin/analytics/sources?${params}`);
  return response.json();
}

export async function fetchGeographicAnalytics(dateStart?: string, dateEnd?: string): Promise<{ states: unknown[] }> {
  const params = new URLSearchParams();
  if (dateStart) params.set('date_start', dateStart);
  if (dateEnd) params.set('date_end', dateEnd);

  const response = await fetch(`${API_BASE}/admin/analytics/geographic?${params}`);
  return response.json();
}

// Feed Management API functions
export async function fetchFeeds(): Promise<{ feeds: unknown[] }> {
  const response = await fetch(`${API_BASE}/admin/feeds`);
  return response.json();
}

export async function createFeed(
  name: string,
  url: string,
  intervalMinutes = 60,
  sourceType = 'news',
  tier = 3,
): Promise<{ success: boolean; feed_id?: string }> {
  const response = await fetch(`${API_BASE}/admin/feeds`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, url, interval_minutes: intervalMinutes, source_type: sourceType, tier }),
  });
  return response.json();
}

export async function updateFeed(feedId: string, updates: Record<string, unknown>): Promise<{ success: boolean }> {
  const response = await fetch(`${API_BASE}/admin/feeds/${feedId}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(updates),
  });
  return response.json();
}

export async function deleteFeed(feedId: string): Promise<{ success: boolean }> {
  const response = await fetch(`${API_BASE}/admin/feeds/${feedId}`, {
    method: 'DELETE',
  });
  return response.json();
}

export async function fetchFeed(feedId: string): Promise<{ success: boolean; message: string }> {
  const response = await fetch(`${API_BASE}/admin/feeds/${feedId}/fetch`, {
    method: 'POST',
  });
  return response.json();
}

export async function toggleFeed(feedId: string, active: boolean): Promise<{ success: boolean; active: boolean }> {
  const response = await fetch(`${API_BASE}/admin/feeds/${feedId}/toggle`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ active }),
  });
  return response.json();
}

// Pipeline stages metadata
export async function fetchPipelineStages(): Promise<{
  id: string; name: string; slug: string;
  description: string | null; default_order: number; is_active: boolean;
}[]> {
  const response = await fetch(`${API_BASE}/admin/pipeline/stages`);
  return response.json();
}

// Metrics API functions
export async function fetchMetricsOverview(): Promise<QueueMetrics> {
  const response = await fetch(`${API_BASE}/metrics/overview`);
  return response.json();
}

export async function fetchTaskPerformance(period = '24h'): Promise<{ tasks: { name: string; total: number; successful: number; failed: number; avg_duration_ms: number; p95_duration_ms: number; total_items: number }[] }> {
  const response = await fetch(`${API_BASE}/metrics/task-performance?period=${period}`);
  return response.json();
}

// Enhanced job action API functions
export async function deleteJob(jobId: string): Promise<{ success: boolean; deleted: string }> {
  const response = await fetch(`${API_BASE}/admin/jobs/${jobId}/delete`, {
    method: 'DELETE',
  });
  if (!response.ok) {
    const err = await response.json().catch(() => ({ detail: 'Delete failed' }));
    throw new Error(err.detail || 'Delete failed');
  }
  return response.json();
}

export async function retryJob(jobId: string): Promise<{ success: boolean; new_job_id: string }> {
  const response = await fetch(`${API_BASE}/admin/jobs/${jobId}/retry`, {
    method: 'POST',
  });
  if (!response.ok) {
    const err = await response.json().catch(() => ({ detail: 'Retry failed' }));
    throw new Error(err.detail || 'Retry failed');
  }
  return response.json();
}

export async function unstickJob(jobId: string): Promise<{ success: boolean; unstuck: string }> {
  const response = await fetch(`${API_BASE}/admin/jobs/${jobId}/unstick`, {
    method: 'POST',
  });
  if (!response.ok) {
    const err = await response.json().catch(() => ({ detail: 'Unstick failed' }));
    throw new Error(err.detail || 'Unstick failed');
  }
  return response.json();
}

// Prompt improvement generation
export interface PromptImprovementResult {
  analysis: string;
  suggested_prompt_additions: Array<{
    target: string;
    addition: string;
    rationale: string;
  }>;
  suggested_field_instructions: Record<string, string>;
}

export async function generatePromptImprovement(data: {
  article_content: string;
  config_a_extraction: Record<string, any>;
  config_b_extraction: Record<string, any>;
  overall_preferred_config: string;
  field_preferences: Record<string, 'A' | 'B'>;
  current_system_prompt?: string;
  current_user_prompt_template?: string;
}): Promise<PromptImprovementResult> {
  const response = await fetch(`${API_BASE}/admin/prompt-tests/generate-prompt-improvement`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
  if (!response.ok) {
    const err = await response.json().catch(() => ({ detail: 'Failed to generate prompt improvement' }));
    throw new Error(err.detail || 'Failed to generate prompt improvement');
  }
  return response.json();
}
