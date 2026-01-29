import { useState, useEffect, useCallback } from 'react';
import { SplitPane } from './SplitPane';
import { HighlightedArticle, collectHighlightsFromRecord } from './articleHighlight';
import type { IncidentSource } from './types';

const API_BASE = '/api';

interface FieldGaps {
  [key: string]: number;
}

interface EnrichmentStats {
  total_incidents: number;
  field_gaps: FieldGaps;
  total_missing_fields: number;
  incidents_with_articles: number;
  incidents_with_actors: number;
  recent_enrichments: Record<string, { incidents_enriched: number; fields_filled: number }>;
}

interface EnrichmentRun {
  id: string;
  job_id: string | null;
  strategy: string;
  params: Record<string, unknown>;
  total_incidents: number;
  incidents_enriched: number;
  fields_filled: number;
  started_at: string;
  completed_at: string | null;
  status: string;
}

interface EnrichmentLogEntry {
  id: string;
  run_id: string;
  incident_id: string;
  field_name: string;
  old_value: string | null;
  new_value: string;
  source_type: string;
  source_incident_id: string | null;
  source_article_id: string | null;
  confidence: number;
  applied: boolean;
  reverted: boolean;
  created_at: string;
  run_strategy: string;
}

interface Candidate {
  id: string;
  date: string;
  state: string;
  city: string | null;
  category: string;
  title: string | null;
  description: string | null;
  victim_name: string | null;
  outcome_category: string | null;
  outcome_detail: string | null;
  address: string | null;
  latitude: number | null;
  longitude: number | null;
  curation_status: string | null;
  article_count: number;
  actor_count: number;
  missing_count: number;
}

// Full incident record from /api/admin/incidents/{id}
interface FullIncident extends Record<string, unknown> {
  id: string;
  category: string;
  date: string;
  state: string;
  city?: string;
  address?: string;
  title?: string;
  description?: string;
  notes?: string;
  incident_type?: string;
  victim_name?: string;
  victim_age?: number;
  victim_category?: string;
  outcome_category?: string;
  outcome_detail?: string;
  latitude?: number;
  longitude?: number;
  source_url?: string;
  source_name?: string;
  source_tier?: string;
  curation_status?: string;
  extraction_confidence?: number;
  offender_immigration_status?: string;
  prior_deportations?: number;
  gang_affiliated?: boolean;
  sources?: IncidentSource[];
}

const FIELD_LABELS: Record<string, string> = {
  city: 'City',
  county: 'County',
  description: 'Description',
  victim_name: 'Victim Name',
  outcome_category: 'Outcome Category',
  outcome_description: 'Outcome Detail',
  latitude: 'Latitude',
  longitude: 'Longitude',
};

// Enrichable fields mapped to the column name on the full incident record
const ENRICHABLE_FIELD_KEYS: Record<string, string> = {
  city: 'city',
  county: 'address',
  description: 'description',
  victim_name: 'victim_name',
  outcome_category: 'outcome_category',
  outcome_description: 'outcome_detail',
  latitude: 'latitude',
  longitude: 'longitude',
};

interface LinkedArticle {
  id: string;
  title: string | null;
  content: string | null;
  source_name: string | null;
  source_url: string;
  published_date: string | null;
  extraction_confidence: number | null;
}

const ALL_FIELDS = Object.keys(FIELD_LABELS);

type TabView = 'stats' | 'run' | 'history' | 'audit';

const CANDIDATES_PAGE_SIZE = 25;

export function EnrichmentPanel() {
  const [tab, setTab] = useState<TabView>('stats');
  const [stats, setStats] = useState<EnrichmentStats | null>(null);
  const [runs, setRuns] = useState<EnrichmentRun[]>([]);
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null);

  // Run controls
  const [strategy, setStrategy] = useState('cross_incident');
  const [limit, setLimit] = useState(100);
  const [autoApply, setAutoApply] = useState(true);
  const [minConfidence, setMinConfidence] = useState(0.7);
  const [selectedFields, setSelectedFields] = useState<string[]>(ALL_FIELDS);
  const [running, setRunning] = useState(false);

  // Audit view
  const [auditIncidentId, setAuditIncidentId] = useState('');
  const [auditLog, setAuditLog] = useState<EnrichmentLogEntry[]>([]);
  const [auditLoading, setAuditLoading] = useState(false);

  // Candidate browser
  const [selectedCandidate, setSelectedCandidate] = useState<Candidate | null>(null);
  const [fullIncident, setFullIncident] = useState<FullIncident | null>(null);
  const [fullIncidentLoading, setFullIncidentLoading] = useState(false);
  const [linkedArticles, setLinkedArticles] = useState<LinkedArticle[]>([]);
  const [articlesLoading, setArticlesLoading] = useState(false);
  const [expandedArticles, setExpandedArticles] = useState<Set<string>>(new Set());
  const [candidateLog, setCandidateLog] = useState<EnrichmentLogEntry[]>([]);
  const [candidateLogLoading, setCandidateLogLoading] = useState(false);
  const [candidatePage, setCandidatePage] = useState(0);
  const [candidateTotalCount, setCandidateTotalCount] = useState(0);

  const loadStats = useCallback(async () => {
    try {
      const response = await fetch(`${API_BASE}/admin/enrichment/stats`);
      if (response.ok) {
        const data = await response.json();
        setStats(data);
      }
    } catch (err) {
      console.error('Failed to load enrichment stats:', err);
    }
  }, []);

  const loadRuns = useCallback(async () => {
    try {
      const response = await fetch(`${API_BASE}/admin/enrichment/runs?limit=20`);
      if (response.ok) {
        const data = await response.json();
        setRuns(data.runs || []);
      }
    } catch (err) {
      console.error('Failed to load enrichment runs:', err);
    }
  }, []);

  const loadCandidates = useCallback(async (page?: number) => {
    const p = page ?? candidatePage;
    const offset = p * CANDIDATES_PAGE_SIZE;
    try {
      const response = await fetch(
        `${API_BASE}/admin/enrichment/candidates?limit=${CANDIDATES_PAGE_SIZE}&offset=${offset}`
      );
      if (response.ok) {
        const data = await response.json();
        setCandidates(data.candidates || []);
        setCandidateTotalCount(data.total_count ?? data.total ?? 0);
      }
    } catch (err) {
      console.error('Failed to load candidates:', err);
    }
  }, [candidatePage]);

  const loadCandidateLog = useCallback(async (incidentId: string) => {
    setCandidateLogLoading(true);
    try {
      const response = await fetch(`${API_BASE}/admin/enrichment/log/${incidentId}`);
      if (response.ok) {
        const data = await response.json();
        setCandidateLog(data.entries || []);
      } else {
        setCandidateLog([]);
      }
    } catch (err) {
      console.error('Failed to load candidate log:', err);
      setCandidateLog([]);
    } finally {
      setCandidateLogLoading(false);
    }
  }, []);

  const loadFullIncident = useCallback(async (incidentId: string) => {
    setFullIncidentLoading(true);
    try {
      const response = await fetch(`${API_BASE}/admin/incidents/${incidentId}`);
      if (response.ok) {
        const data = await response.json();
        setFullIncident(data);
      } else {
        setFullIncident(null);
      }
    } catch (err) {
      console.error('Failed to load full incident:', err);
      setFullIncident(null);
    } finally {
      setFullIncidentLoading(false);
    }
  }, []);

  const loadLinkedArticles = useCallback(async (incidentId: string) => {
    setArticlesLoading(true);
    setExpandedArticles(new Set());
    try {
      const response = await fetch(`${API_BASE}/admin/incidents/${incidentId}/articles`);
      if (response.ok) {
        const data = await response.json();
        setLinkedArticles(data.articles || []);
      } else {
        setLinkedArticles([]);
      }
    } catch (err) {
      console.error('Failed to load linked articles:', err);
      setLinkedArticles([]);
    } finally {
      setArticlesLoading(false);
    }
  }, []);

  useEffect(() => {
    setLoading(true);
    Promise.all([loadStats(), loadRuns(), loadCandidates(0)]).finally(() => setLoading(false));
  }, [loadStats, loadRuns, loadCandidates]);

  // Reload candidates when page changes
  useEffect(() => {
    loadCandidates();
  }, [candidatePage, loadCandidates]);

  const handleSelectCandidate = (c: Candidate) => {
    setSelectedCandidate(c);
    loadFullIncident(c.id);
    loadLinkedArticles(c.id);
    loadCandidateLog(c.id);
  };

  const handleCandidatePageChange = (newPage: number) => {
    setCandidatePage(newPage);
    setSelectedCandidate(null);
    setFullIncident(null);
    setLinkedArticles([]);
    setCandidateLog([]);
  };

  const toggleArticleExpanded = (articleId: string) => {
    setExpandedArticles(prev => {
      const next = new Set(prev);
      if (next.has(articleId)) {
        next.delete(articleId);
      } else {
        next.add(articleId);
      }
      return next;
    });
  };

  const startEnrichment = async () => {
    setRunning(true);
    setMessage(null);
    try {
      const response = await fetch(`${API_BASE}/admin/enrichment/run`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          strategy,
          limit,
          auto_apply: autoApply,
          min_confidence: minConfidence,
          target_fields: selectedFields.length === ALL_FIELDS.length ? null : selectedFields,
        }),
      });

      if (response.ok) {
        const data = await response.json();
        setMessage({ type: 'success', text: `Enrichment job queued (ID: ${data.job_id})` });
        await loadRuns();
      } else {
        const data = await response.json().catch(() => ({}));
        setMessage({ type: 'error', text: data.detail || 'Failed to start enrichment' });
      }
    } catch (err) {
      setMessage({ type: 'error', text: String(err) });
    } finally {
      setRunning(false);
    }
  };

  const loadAuditLog = async () => {
    if (!auditIncidentId.trim()) return;
    setAuditLoading(true);
    try {
      const response = await fetch(`${API_BASE}/admin/enrichment/log/${auditIncidentId}`);
      if (response.ok) {
        const data = await response.json();
        setAuditLog(data.entries || []);
      } else {
        setMessage({ type: 'error', text: 'Failed to load audit log' });
      }
    } catch (err) {
      setMessage({ type: 'error', text: String(err) });
    } finally {
      setAuditLoading(false);
    }
  };

  const revertEntry = async (logId: string) => {
    try {
      const response = await fetch(`${API_BASE}/admin/enrichment/revert/${logId}`, {
        method: 'POST',
      });
      if (response.ok) {
        setMessage({ type: 'success', text: 'Enrichment reverted' });
        await loadAuditLog();
        await loadStats();
      } else {
        const data = await response.json().catch(() => ({}));
        setMessage({ type: 'error', text: data.detail || 'Failed to revert' });
      }
    } catch (err) {
      setMessage({ type: 'error', text: String(err) });
    }
  };

  const toggleField = (field: string) => {
    setSelectedFields(prev =>
      prev.includes(field) ? prev.filter(f => f !== field) : [...prev, field]
    );
  };

  const formatDate = (iso: string) => new Date(iso).toLocaleString();

  const totalPages = Math.max(1, Math.ceil(candidateTotalCount / CANDIDATES_PAGE_SIZE));

  const renderCandidateList = () => (
    <div className="candidate-list">
      <div className="candidate-list-items">
        {candidates.map(c => (
          <div
            key={c.id}
            className={`candidate-item ${selectedCandidate?.id === c.id ? 'selected' : ''}`}
            onClick={() => handleSelectCandidate(c)}
          >
            <div className="candidate-item-header">
              <span className="candidate-item-title">
                {c.title || c.description?.slice(0, 60) || `${c.state} - ${c.date}`}
              </span>
              <span className="nav-badge">{c.missing_count}</span>
            </div>
            <div className="candidate-item-meta">
              <span>{c.date}</span>
              <span>{c.state || 'Unknown'}</span>
              <span className={`category-badge ${c.category}`}>{c.category}</span>
            </div>
          </div>
        ))}
        {candidates.length === 0 && (
          <div style={{ padding: '20px', textAlign: 'center', color: 'var(--text-muted)' }}>
            No candidates found
          </div>
        )}
      </div>
      <div className="candidate-pagination">
        <button
          className="action-btn small"
          disabled={candidatePage === 0}
          onClick={() => handleCandidatePageChange(candidatePage - 1)}
        >
          Prev
        </button>
        <span>
          Page {candidatePage + 1} of {totalPages}
          {candidateTotalCount > 0 && ` (${candidateTotalCount} total)`}
        </span>
        <button
          className="action-btn small"
          disabled={candidatePage >= totalPages - 1}
          onClick={() => handleCandidatePageChange(candidatePage + 1)}
        >
          Next
        </button>
      </div>
    </div>
  );

  const renderCandidateDetail = () => {
    if (!selectedCandidate) {
      return (
        <div className="candidate-detail empty">
          Select a candidate to view details
        </div>
      );
    }

    if (fullIncidentLoading) {
      return (
        <div className="candidate-detail empty">
          Loading incident data...
        </div>
      );
    }

    const inc = fullIncident;
    const c = selectedCandidate;

    // Determine missing enrichable fields from the full incident record
    const missingFields: string[] = [];
    const presentFields: string[] = [];
    for (const [fieldKey, colKey] of Object.entries(ENRICHABLE_FIELD_KEYS)) {
      const val = inc ? inc[colKey] : c[colKey as keyof Candidate];
      if (val === null || val === undefined || val === '') {
        missingFields.push(fieldKey);
      } else {
        presentFields.push(fieldKey);
      }
    }

    return (
      <div className="candidate-detail">
        {/* Header */}
        <div className="candidate-detail-header">
          <div>
            <span className={`category-badge ${c.category}`}>{c.category}</span>
            <span className="candidate-detail-date">{c.date}</span>
            <span className="candidate-detail-location">
              {[inc?.city || c.city, inc?.state || c.state].filter(Boolean).join(', ') || 'Unknown location'}
            </span>
          </div>
          <span className="nav-badge">{c.missing_count} missing</span>
        </div>

        {/* Title */}
        {(inc?.title || c.title) && (
          <h3 style={{ margin: '12px 0 8px', fontSize: '15px' }}>
            {inc?.title || c.title}
          </h3>
        )}

        {/* Description */}
        {(inc?.description || c.description) && (
          <div className="detail-section">
            <h4>Description</h4>
            <p style={{ fontSize: '13px', lineHeight: 1.6, color: 'var(--text-secondary)', margin: 0 }}>
              {inc?.description || c.description}
            </p>
          </div>
        )}

        {/* Notes */}
        {inc?.notes && (
          <div className="detail-section">
            <h4>Notes</h4>
            <p style={{ fontSize: '13px', lineHeight: 1.6, color: 'var(--text-secondary)', margin: 0 }}>
              {inc.notes}
            </p>
          </div>
        )}

        {/* Key Fields */}
        <div className="detail-section">
          <h4>Incident Data</h4>
          <table className="candidate-fields-table">
            <tbody>
              <tr>
                <td className="field-label">Incident Type</td>
                <td className="field-value">{inc?.incident_type || '--'}</td>
              </tr>
              {c.category === 'enforcement' && (
                <>
                  <tr>
                    <td className="field-label">Victim Name</td>
                    <td className={inc?.victim_name ? 'field-value' : 'field-missing'}>
                      {inc?.victim_name || 'Missing'}
                    </td>
                  </tr>
                  <tr>
                    <td className="field-label">Victim Category</td>
                    <td className="field-value">{inc?.victim_category || '--'}</td>
                  </tr>
                  <tr>
                    <td className="field-label">Victim Age</td>
                    <td className="field-value">{inc?.victim_age ?? '--'}</td>
                  </tr>
                </>
              )}
              {c.category === 'crime' && (
                <>
                  <tr>
                    <td className="field-label">Immigration Status</td>
                    <td className="field-value">{inc?.offender_immigration_status || '--'}</td>
                  </tr>
                  <tr>
                    <td className="field-label">Prior Deportations</td>
                    <td className="field-value">{inc?.prior_deportations ?? '--'}</td>
                  </tr>
                  <tr>
                    <td className="field-label">Gang Affiliated</td>
                    <td className="field-value">{inc?.gang_affiliated ? 'Yes' : inc?.gang_affiliated === false ? 'No' : '--'}</td>
                  </tr>
                </>
              )}
              <tr>
                <td className="field-label">Outcome</td>
                <td className={inc?.outcome_category ? 'field-value' : 'field-missing'}>
                  {inc?.outcome_category || 'Missing'}
                  {inc?.outcome_detail && ` - ${inc.outcome_detail}`}
                </td>
              </tr>
              <tr>
                <td className="field-label">City</td>
                <td className={inc?.city ? 'field-value' : 'field-missing'}>
                  {inc?.city || 'Missing'}
                </td>
              </tr>
              <tr>
                <td className="field-label">Address</td>
                <td className={inc?.address ? 'field-value' : 'field-missing'}>
                  {inc?.address || 'Missing'}
                </td>
              </tr>
              <tr>
                <td className="field-label">Coordinates</td>
                <td className={(inc?.latitude != null) ? 'field-value' : 'field-missing'}>
                  {(inc?.latitude != null && inc?.longitude != null)
                    ? `${inc.latitude}, ${inc.longitude}`
                    : 'Missing'}
                </td>
              </tr>
              <tr>
                <td className="field-label">Source Tier</td>
                <td className="field-value">{inc?.source_tier || '--'}</td>
              </tr>
              <tr>
                <td className="field-label">Confidence</td>
                <td className="field-value">
                  {inc?.extraction_confidence != null
                    ? `${(Number(inc.extraction_confidence) * 100).toFixed(0)}%`
                    : '--'}
                </td>
              </tr>
              <tr>
                <td className="field-label">Curation Status</td>
                <td className="field-value">{inc?.curation_status || c.curation_status || '--'}</td>
              </tr>
            </tbody>
          </table>
        </div>

        {/* Missing Fields Summary */}
        <div className="detail-section">
          <h4>Missing Enrichable Fields ({missingFields.length})</h4>
          {missingFields.length > 0 ? (
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
              {missingFields.map(f => (
                <span key={f} className="missing-field-badge">{FIELD_LABELS[f]}</span>
              ))}
            </div>
          ) : (
            <p className="no-data">All enrichable fields have values</p>
          )}
        </div>

        {/* Articles */}
        <div className="detail-section">
          <h4>Articles ({articlesLoading ? '...' : linkedArticles.length})</h4>
          {(() => {
            const highlights = inc ? collectHighlightsFromRecord(inc) : [];
            return articlesLoading ? (
              <p className="no-data">Loading articles...</p>
            ) : linkedArticles.length > 0 ? (
              <div className="article-cards">
                {linkedArticles.map(article => {
                  const isExpanded = expandedArticles.has(article.id);
                  return (
                    <div key={article.id} className="article-card">
                      <div
                        className="article-card-header"
                        onClick={() => article.content ? toggleArticleExpanded(article.id) : undefined}
                        style={{ cursor: article.content ? 'pointer' : 'default' }}
                      >
                        <div className="article-card-title">
                          {article.content && (
                            <span className="article-expand-icon">{isExpanded ? '\u25BC' : '\u25B6'}</span>
                          )}
                          {article.source_url ? (
                            <a href={article.source_url} target="_blank" rel="noopener noreferrer">
                              {article.title || article.source_url}
                            </a>
                          ) : (
                            <span>{article.title || 'Untitled article'}</span>
                          )}
                        </div>
                        <div className="article-card-meta">
                          {article.source_name && <span>{article.source_name}</span>}
                          {article.published_date && <span>{article.published_date}</span>}
                          {article.extraction_confidence != null && (
                            <span>{(article.extraction_confidence * 100).toFixed(0)}% conf</span>
                          )}
                        </div>
                      </div>
                      {isExpanded && article.content && (
                        <div className="article-card-content">
                          <HighlightedArticle content={article.content} highlights={highlights} />
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            ) : inc?.source_url ? (
              <div className="candidate-source-item">
                <a href={inc.source_url as string} target="_blank" rel="noopener noreferrer">
                  {(inc.source_name as string) || (inc.source_url as string)}
                </a>
              </div>
            ) : (
              <p className="no-data">No linked articles</p>
            );
          })()}
        </div>

        {/* Context counts */}
        <div className="candidate-context-row">
          <div className="candidate-context-item">
            Linked Articles: <strong>{c.article_count}</strong>
          </div>
          <div className="candidate-context-item">
            Linked Actors: <strong>{c.actor_count}</strong>
          </div>
        </div>

        {/* Enrichment History */}
        <div className="detail-section">
          <h4>Enrichment History</h4>
          {candidateLogLoading ? (
            <p className="no-data">Loading history...</p>
          ) : candidateLog.length === 0 ? (
            <p className="no-data">No enrichment history for this incident</p>
          ) : (
            <div className="table-container">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Field</th>
                    <th>New Value</th>
                    <th>Source</th>
                    <th>Confidence</th>
                    <th>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {candidateLog.map(entry => (
                    <tr key={entry.id}>
                      <td>{FIELD_LABELS[entry.field_name] || entry.field_name}</td>
                      <td style={{ maxWidth: '180px', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                        {entry.new_value}
                      </td>
                      <td>{entry.source_type}</td>
                      <td>{(entry.confidence * 100).toFixed(0)}%</td>
                      <td>
                        {entry.reverted ? (
                          <span style={{ color: 'var(--color-danger)' }}>Reverted</span>
                        ) : entry.applied ? (
                          <span style={{ color: 'var(--color-success)' }}>Applied</span>
                        ) : (
                          <span style={{ color: 'var(--text-muted)' }}>Pending</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    );
  };

  return (
    <div className="admin-page">
      <div className="page-header">
        <h2>Enrichment</h2>
        <div className="page-actions">
          <button className="action-btn" onClick={() => { loadStats(); loadRuns(); loadCandidates(); }}>
            Refresh
          </button>
        </div>
      </div>

      {/* Tabs */}
      <div style={{ display: 'flex', gap: '4px', marginBottom: '16px', borderBottom: '1px solid var(--border-color)', paddingBottom: '8px' }}>
        {([
          ['stats', 'Stats'],
          ['run', 'Run Enrichment'],
          ['history', 'Run History'],
          ['audit', 'Audit Log'],
        ] as [TabView, string][]).map(([key, label]) => (
          <button
            key={key}
            className={`action-btn ${tab === key ? 'primary' : ''}`}
            onClick={() => setTab(key)}
            style={{ fontSize: '13px' }}
          >
            {label}
          </button>
        ))}
      </div>

      {message && (
        <div className={`operation-result ${message.type === 'success' ? 'success' : 'error'}`} style={{ marginBottom: '16px' }}>
          {message.text}
        </div>
      )}

      {loading ? (
        <div className="admin-loading">Loading...</div>
      ) : (
        <div className="page-content">
          {/* Stats Tab */}
          {tab === 'stats' && stats && (
            <div>
              <div className="dashboard-stats">
                <div className="stat-card">
                  <div className="stat-value">{stats.total_incidents}</div>
                  <div className="stat-label">Total Incidents</div>
                </div>
                <div className="stat-card highlight">
                  <div className="stat-value">{stats.total_missing_fields}</div>
                  <div className="stat-label">Missing Fields</div>
                </div>
                <div className="stat-card">
                  <div className="stat-value">{stats.incidents_with_articles}</div>
                  <div className="stat-label">With Articles</div>
                </div>
                <div className="stat-card">
                  <div className="stat-value">{stats.incidents_with_actors}</div>
                  <div className="stat-label">With Actors</div>
                </div>
              </div>

              <div className="dashboard-grid" style={{ marginTop: '16px' }}>
                <div className="dashboard-card">
                  <h3>Missing Fields by Type</h3>
                  <div className="tier-bars">
                    {Object.entries(stats.field_gaps)
                      .sort(([, a], [, b]) => b - a)
                      .map(([field, count]) => (
                        <div key={field} className="tier-bar">
                          <div className="tier-label" style={{ minWidth: '140px' }}>
                            {FIELD_LABELS[field] || field}
                          </div>
                          <div className="tier-progress">
                            <div
                              className="tier-fill tier-3"
                              style={{ width: `${Math.min(100, (count / stats.total_incidents) * 100)}%` }}
                            />
                          </div>
                          <div className="tier-count">{count}</div>
                        </div>
                      ))}
                  </div>
                </div>

                <div className="dashboard-card">
                  <h3>Recent Enrichments (30d)</h3>
                  {Object.keys(stats.recent_enrichments).length > 0 ? (
                    <div className="table-container">
                      <table className="data-table">
                        <thead>
                          <tr>
                            <th>Strategy</th>
                            <th>Incidents</th>
                            <th>Fields</th>
                          </tr>
                        </thead>
                        <tbody>
                          {Object.entries(stats.recent_enrichments).map(([strat, data]) => (
                            <tr key={strat}>
                              <td>{strat}</td>
                              <td>{data.incidents_enriched}</td>
                              <td>{data.fields_filled}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  ) : (
                    <p className="no-data">No enrichments in the last 30 days</p>
                  )}
                </div>
              </div>

              {/* Enrichment Candidates Browser */}
              <div className="content-section" style={{ marginTop: '16px' }}>
                <h3>Enrichment Candidates</h3>
                <div className="enrichment-candidates-split">
                  <SplitPane
                    storageKey="enrichment-candidates"
                    left={renderCandidateList()}
                    right={renderCandidateDetail()}
                    defaultLeftWidth={380}
                    minLeftWidth={260}
                    maxLeftWidth={550}
                  />
                </div>
              </div>
            </div>
          )}

          {/* Run Tab */}
          {tab === 'run' && (
            <div className="dashboard-card">
              <h3>Run Enrichment</h3>

              <div style={{ display: 'grid', gap: '16px', maxWidth: '600px' }}>
                {/* Strategy */}
                <div>
                  <label style={{ display: 'block', marginBottom: '4px', fontWeight: 600, fontSize: '13px' }}>
                    Strategy
                  </label>
                  <select
                    value={strategy}
                    onChange={e => setStrategy(e.target.value)}
                    style={{ width: '100%', padding: '8px', borderRadius: '4px', border: '1px solid var(--border-color)', background: 'var(--bg-primary)', color: 'var(--text-primary)' }}
                  >
                    <option value="cross_incident">Cross-Incident Merge</option>
                    <option value="llm_reextract">LLM Re-extraction</option>
                    <option value="full">Both (Full)</option>
                  </select>
                  <p style={{ fontSize: '12px', color: 'var(--text-muted)', marginTop: '4px' }}>
                    {strategy === 'cross_incident' && 'Copy fields from related incidents sharing actors, dates, or locations.'}
                    {strategy === 'llm_reextract' && 'Use Claude to re-extract specific missing fields from linked articles.'}
                    {strategy === 'full' && 'Run both strategies: cross-incident merge first, then LLM re-extraction.'}
                  </p>
                </div>

                {/* Limit */}
                <div>
                  <label style={{ display: 'block', marginBottom: '4px', fontWeight: 600, fontSize: '13px' }}>
                    Incident Limit: {limit}
                  </label>
                  <input
                    type="range"
                    min={10}
                    max={500}
                    step={10}
                    value={limit}
                    onChange={e => setLimit(Number(e.target.value))}
                    style={{ width: '100%' }}
                  />
                </div>

                {/* Min Confidence */}
                <div>
                  <label style={{ display: 'block', marginBottom: '4px', fontWeight: 600, fontSize: '13px' }}>
                    Min Confidence: {(minConfidence * 100).toFixed(0)}%
                  </label>
                  <input
                    type="range"
                    min={0.3}
                    max={1.0}
                    step={0.05}
                    value={minConfidence}
                    onChange={e => setMinConfidence(Number(e.target.value))}
                    style={{ width: '100%' }}
                  />
                </div>

                {/* Auto Apply */}
                <div>
                  <label style={{ display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer' }}>
                    <input
                      type="checkbox"
                      checked={autoApply}
                      onChange={e => setAutoApply(e.target.checked)}
                    />
                    <span style={{ fontWeight: 600, fontSize: '13px' }}>Auto-apply changes</span>
                  </label>
                  <p style={{ fontSize: '12px', color: 'var(--text-muted)', marginTop: '4px' }}>
                    If enabled, high-confidence enrichments are applied immediately. Otherwise they are recorded for manual review.
                  </p>
                </div>

                {/* Target Fields */}
                <div>
                  <label style={{ display: 'block', marginBottom: '8px', fontWeight: 600, fontSize: '13px' }}>
                    Target Fields
                  </label>
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px' }}>
                    {ALL_FIELDS.map(field => (
                      <label key={field} style={{
                        display: 'flex', alignItems: 'center', gap: '4px',
                        padding: '4px 8px', borderRadius: '4px',
                        border: '1px solid var(--border-color)',
                        background: selectedFields.includes(field) ? 'var(--accent-bg)' : 'transparent',
                        cursor: 'pointer', fontSize: '12px',
                      }}>
                        <input
                          type="checkbox"
                          checked={selectedFields.includes(field)}
                          onChange={() => toggleField(field)}
                          style={{ display: 'none' }}
                        />
                        {FIELD_LABELS[field]}
                      </label>
                    ))}
                  </div>
                </div>

                {/* Start Button */}
                <div>
                  <button
                    className="action-btn primary"
                    onClick={startEnrichment}
                    disabled={running || selectedFields.length === 0}
                    style={{ width: '100%' }}
                  >
                    {running ? 'Starting...' : 'Start Enrichment'}
                  </button>
                </div>
              </div>
            </div>
          )}

          {/* History Tab */}
          {tab === 'history' && (
            <div>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
                <h3 style={{ margin: 0 }}>Run History</h3>
                <button className="action-btn" onClick={loadRuns}>Refresh</button>
              </div>

              {runs.length === 0 ? (
                <p className="no-data">No enrichment runs yet</p>
              ) : (
                <div className="table-container">
                  <table className="data-table">
                    <thead>
                      <tr>
                        <th>Started</th>
                        <th>Strategy</th>
                        <th>Status</th>
                        <th>Incidents</th>
                        <th>Enriched</th>
                        <th>Fields</th>
                        <th>Duration</th>
                      </tr>
                    </thead>
                    <tbody>
                      {runs.map(run => {
                        const duration = run.completed_at && run.started_at
                          ? Math.round((new Date(run.completed_at).getTime() - new Date(run.started_at).getTime()) / 1000)
                          : null;
                        return (
                          <tr key={run.id}>
                            <td>{formatDate(run.started_at)}</td>
                            <td>{run.strategy}</td>
                            <td>
                              <span className={`status-badge ${run.status}`}>
                                {run.status}
                              </span>
                            </td>
                            <td>{run.total_incidents}</td>
                            <td>{run.incidents_enriched}</td>
                            <td>{run.fields_filled}</td>
                            <td>{duration !== null ? `${duration}s` : '--'}</td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )}

          {/* Audit Tab */}
          {tab === 'audit' && (
            <div>
              <h3>Incident Audit Log</h3>
              <div style={{ display: 'flex', gap: '8px', marginBottom: '16px' }}>
                <input
                  type="text"
                  placeholder="Enter incident ID (UUID)"
                  value={auditIncidentId}
                  onChange={e => setAuditIncidentId(e.target.value)}
                  style={{
                    flex: 1, padding: '8px', borderRadius: '4px',
                    border: '1px solid var(--border-color)',
                    background: 'var(--bg-primary)', color: 'var(--text-primary)',
                  }}
                />
                <button
                  className="action-btn primary"
                  onClick={loadAuditLog}
                  disabled={auditLoading || !auditIncidentId.trim()}
                >
                  {auditLoading ? 'Loading...' : 'Load Log'}
                </button>
              </div>

              {auditLog.length > 0 && (
                <div className="table-container">
                  <table className="data-table">
                    <thead>
                      <tr>
                        <th>Date</th>
                        <th>Field</th>
                        <th>New Value</th>
                        <th>Source</th>
                        <th>Confidence</th>
                        <th>Status</th>
                        <th>Actions</th>
                      </tr>
                    </thead>
                    <tbody>
                      {auditLog.map(entry => (
                        <tr key={entry.id}>
                          <td style={{ fontSize: '12px' }}>{formatDate(entry.created_at)}</td>
                          <td>{FIELD_LABELS[entry.field_name] || entry.field_name}</td>
                          <td style={{ maxWidth: '200px', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                            {entry.new_value}
                          </td>
                          <td>
                            {entry.source_type}
                            {entry.source_incident_id && (
                              <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
                                {entry.source_incident_id.slice(0, 8)}...
                              </div>
                            )}
                          </td>
                          <td>{(entry.confidence * 100).toFixed(0)}%</td>
                          <td>
                            {entry.reverted ? (
                              <span style={{ color: 'var(--color-danger)' }}>Reverted</span>
                            ) : entry.applied ? (
                              <span style={{ color: 'var(--color-success)' }}>Applied</span>
                            ) : (
                              <span style={{ color: 'var(--text-muted)' }}>Pending</span>
                            )}
                          </td>
                          <td>
                            {entry.applied && !entry.reverted && (
                              <button
                                className="action-btn small"
                                onClick={() => revertEntry(entry.id)}
                                style={{ fontSize: '11px' }}
                              >
                                Revert
                              </button>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default EnrichmentPanel;
