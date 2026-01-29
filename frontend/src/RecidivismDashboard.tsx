import { useState, useEffect, useCallback } from 'react';

const API_BASE = '';

interface RecidivismSummary {
  total_recidivists: number;
  avg_incidents: number;
  max_incidents: number;
  avg_days_between: number;
  avg_total_span_days: number;
}

interface RecidivistActor {
  actor_id: string;
  canonical_name: string;
  total_incidents: number;
  first_incident_date: string | null;
  most_recent_incident_date: string | null;
  total_days_span: number | null;
  avg_days_between_incidents: number | null;
  stddev_days_between: number | null;
  recidivist_incidents: number;
  incident_progression: string[];
  outcome_progression: string[];
}

interface IncidentHistoryItem {
  actor_id: string;
  canonical_name: string;
  incident_id: string;
  incident_date: string | null;
  domain: string;
  category: string;
  incident_type: string;
  outcome: string | null;
  incident_number: number;
  days_since_last_incident: number | null;
}

interface RecidivismIndicator {
  actor_id: string;
  indicator_score: number;
  is_preliminary: boolean;
  model_version: string;
  disclaimer: string;
}

interface LifecyclePhase {
  actor_id: string;
  canonical_name: string;
  case_id: string | null;
  case_number: string | null;
  lifecycle_phase: string;
  phase_start_date: string | null;
  phase_end_date: string | null;
  events_in_phase: number;
}

type DetailTab = 'history' | 'lifecycle';

export function RecidivismDashboard() {
  const [summary, setSummary] = useState<RecidivismSummary | null>(null);
  const [actors, setActors] = useState<RecidivistActor[]>([]);
  const [selectedActor, setSelectedActor] = useState<RecidivistActor | null>(null);
  const [history, setHistory] = useState<IncidentHistoryItem[]>([]);
  const [indicator, setIndicator] = useState<RecidivismIndicator | null>(null);
  const [lifecycle, setLifecycle] = useState<LifecyclePhase[]>([]);
  const [detailTab, setDetailTab] = useState<DetailTab>('history');
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [minIncidents, setMinIncidents] = useState(2);

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const [summaryRes, actorsRes] = await Promise.all([
        fetch(`${API_BASE}/api/admin/recidivism/summary`),
        fetch(`${API_BASE}/api/admin/recidivism/actors?min_incidents=${minIncidents}`),
      ]);
      if (!summaryRes.ok || !actorsRes.ok) throw new Error('Failed to load data');
      const summaryData = await summaryRes.json();
      const actorsData = await actorsRes.json();
      setSummary(summaryData);
      setActors(actorsData.actors || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Load failed');
    } finally {
      setLoading(false);
    }
  }, [minIncidents]);

  useEffect(() => { loadData(); }, [loadData]);

  const handleSelectActor = async (actor: RecidivistActor) => {
    setSelectedActor(actor);
    setDetailTab('history');
    try {
      const [histRes, indRes, lcRes] = await Promise.all([
        fetch(`${API_BASE}/api/admin/recidivism/actors/${actor.actor_id}/history`),
        fetch(`${API_BASE}/api/admin/recidivism/actors/${actor.actor_id}/indicator`),
        fetch(`${API_BASE}/api/admin/recidivism/actors/${actor.actor_id}/lifecycle`),
      ]);
      if (histRes.ok) { const d = await histRes.json(); setHistory(d.history || []); }
      if (indRes.ok) { setIndicator(await indRes.json()); }
      if (lcRes.ok) { const d = await lcRes.json(); setLifecycle(d.lifecycle || []); }
    } catch { /* best effort */ }
  };

  const handleRefresh = async () => {
    setRefreshing(true);
    try {
      await fetch(`${API_BASE}/api/admin/recidivism/refresh`, { method: 'POST' });
      await loadData();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Refresh failed');
    } finally {
      setRefreshing(false);
    }
  };

  const formatDays = (d: number | null) => d != null ? `${Math.round(d)} days` : '—';
  const phaseLabel = (p: string) => p.replace(/^\d+_/, '').replace(/_/g, ' ');

  const scoreColor = (score: number) => {
    if (score >= 0.7) return '#ef4444';
    if (score >= 0.4) return '#f59e0b';
    return '#22c55e';
  };

  if (loading) return <div className="admin-loading">Loading recidivism data...</div>;

  return (
    <div className="admin-page">
      <div className="page-header">
        <h2>Recidivism Analytics</h2>
        <div className="page-actions">
          <label style={{ fontSize: 13, marginRight: 4 }}>Min incidents:</label>
          <select
            value={minIncidents}
            onChange={e => setMinIncidents(parseInt(e.target.value))}
            style={{ marginRight: 8, padding: '6px 10px', borderRadius: 6, border: '1px solid var(--border-color)', fontSize: 13 }}
          >
            {[2, 3, 5, 10].map(n => <option key={n} value={n}>{n}+</option>)}
          </select>
          <button className="action-btn" onClick={handleRefresh} disabled={refreshing}>
            {refreshing ? 'Refreshing...' : 'Refresh Analysis'}
          </button>
        </div>
      </div>

      {error && <div className="error-banner">{error}</div>}

      {/* Summary Cards */}
      {summary && (
        <div className="dashboard-stats" style={{ marginBottom: 24 }}>
          <div className="stat-card">
            <div className="stat-value">{summary.total_recidivists}</div>
            <div className="stat-label">Repeat Offenders</div>
          </div>
          <div className="stat-card">
            <div className="stat-value">{summary.avg_incidents}</div>
            <div className="stat-label">Avg Incidents</div>
          </div>
          <div className="stat-card">
            <div className="stat-value">{summary.max_incidents}</div>
            <div className="stat-label">Most Incidents</div>
          </div>
          <div className="stat-card">
            <div className="stat-value">{formatDays(summary.avg_days_between)}</div>
            <div className="stat-label">Avg Days Between</div>
          </div>
        </div>
      )}

      <div className="split-view">
        {/* Actor List */}
        <div className="list-panel">
          <div className="list-header">
            <h3>Repeat Offenders ({actors.length})</h3>
          </div>
          {actors.length === 0 ? (
            <div className="empty-state"><p>No repeat offenders found.</p></div>
          ) : (
            <div className="table-container" style={{ border: 'none' }}>
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Name</th>
                    <th>Incidents</th>
                    <th>Avg Gap</th>
                    <th>Span</th>
                  </tr>
                </thead>
                <tbody>
                  {actors.map(a => (
                    <tr
                      key={a.actor_id}
                      className={selectedActor?.actor_id === a.actor_id ? 'selected' : ''}
                      onClick={() => handleSelectActor(a)}
                      style={{ cursor: 'pointer' }}
                    >
                      <td style={{ fontWeight: 500 }}>{a.canonical_name}</td>
                      <td>
                        <span style={{
                          background: a.total_incidents >= 5 ? '#ef4444' : a.total_incidents >= 3 ? '#f59e0b' : '#6b7280',
                          color: '#fff', padding: '2px 8px', borderRadius: 12, fontSize: 11, fontWeight: 600,
                        }}>
                          {a.total_incidents}
                        </span>
                      </td>
                      <td style={{ fontSize: 12 }}>{formatDays(a.avg_days_between_incidents)}</td>
                      <td style={{ fontSize: 12 }}>{formatDays(a.total_days_span)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {/* Detail Panel */}
        <div className="detail-panel">
          {selectedActor ? (
            <>
              <div className="detail-header">
                <h3>{selectedActor.canonical_name}</h3>
              </div>
              <div className="detail-content">
                {/* Indicator Badge */}
                {indicator && (
                  <div style={{
                    display: 'flex', alignItems: 'center', gap: 12,
                    padding: 12, background: 'var(--bg-secondary)', borderRadius: 8, marginBottom: 16,
                  }}>
                    <div style={{
                      width: 48, height: 48, borderRadius: '50%',
                      background: scoreColor(indicator.indicator_score),
                      display: 'flex', alignItems: 'center', justifyContent: 'center',
                      color: '#fff', fontWeight: 700, fontSize: 16,
                    }}>
                      {(indicator.indicator_score * 100).toFixed(0)}
                    </div>
                    <div>
                      <div style={{ fontSize: 14, fontWeight: 600 }}>
                        Recidivism Indicator ({indicator.model_version})
                      </div>
                      <div style={{ fontSize: 11, color: 'var(--text-muted)', maxWidth: 400 }}>
                        {indicator.disclaimer}
                      </div>
                    </div>
                  </div>
                )}

                {/* Stats Grid */}
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 12, marginBottom: 16 }}>
                  <div className="stat-card" style={{ padding: 10, textAlign: 'center' }}>
                    <div style={{ fontSize: 20, fontWeight: 700 }}>{selectedActor.total_incidents}</div>
                    <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>Total Incidents</div>
                  </div>
                  <div className="stat-card" style={{ padding: 10, textAlign: 'center' }}>
                    <div style={{ fontSize: 20, fontWeight: 700 }}>{formatDays(selectedActor.avg_days_between_incidents)}</div>
                    <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>Avg Gap</div>
                  </div>
                  <div className="stat-card" style={{ padding: 10, textAlign: 'center' }}>
                    <div style={{ fontSize: 20, fontWeight: 700 }}>{formatDays(selectedActor.total_days_span)}</div>
                    <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>Total Span</div>
                  </div>
                </div>

                {/* Progression */}
                {selectedActor.incident_progression && selectedActor.incident_progression.length > 0 && (
                  <div style={{ marginBottom: 16 }}>
                    <h4 style={{ marginBottom: 8, fontSize: 13 }}>Incident Progression</h4>
                    <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
                      {selectedActor.incident_progression.map((type, i) => (
                        <span key={i} style={{
                          padding: '2px 8px', borderRadius: 12, fontSize: 11,
                          background: 'var(--bg-secondary)', border: '1px solid var(--border-color)',
                        }}>
                          {type}
                        </span>
                      ))}
                    </div>
                  </div>
                )}

                {/* Tabs */}
                <div style={{ display: 'flex', gap: 0, borderBottom: '1px solid var(--border-color)', marginBottom: 12 }}>
                  {(['history', 'lifecycle'] as DetailTab[]).map(t => (
                    <button
                      key={t}
                      onClick={() => setDetailTab(t)}
                      style={{
                        padding: '6px 16px', fontSize: 12, fontWeight: detailTab === t ? 600 : 400,
                        background: 'none', border: 'none',
                        borderBottom: detailTab === t ? '2px solid var(--accent-color)' : '2px solid transparent',
                        cursor: 'pointer', color: detailTab === t ? 'var(--text-primary)' : 'var(--text-muted)',
                      }}
                    >
                      {t === 'history' ? 'Incident History' : 'Lifecycle Timeline'}
                    </button>
                  ))}
                </div>

                {detailTab === 'history' ? (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                    {history.length === 0 ? (
                      <div className="empty-state"><p>No incident history.</p></div>
                    ) : (
                      history.map((h, i) => (
                        <div key={i} style={{
                          padding: 10, background: 'var(--bg-secondary)', borderRadius: 8, fontSize: 13,
                          borderLeft: `3px solid ${h.incident_number === 1 ? '#3b82f6' : '#ef4444'}`,
                        }}>
                          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
                            <span style={{ fontWeight: 600 }}>#{h.incident_number} — {h.incident_type}</span>
                            <span style={{ color: 'var(--text-muted)', fontSize: 12 }}>
                              {h.incident_date ? new Date(h.incident_date).toLocaleDateString() : '—'}
                            </span>
                          </div>
                          <div style={{ color: 'var(--text-secondary)', fontSize: 12 }}>
                            {h.domain} / {h.category}
                            {h.outcome && <> — <strong>{h.outcome}</strong></>}
                            {h.days_since_last_incident != null && (
                              <span style={{ marginLeft: 12, color: 'var(--text-muted)' }}>
                                ({h.days_since_last_incident} days since previous)
                              </span>
                            )}
                          </div>
                        </div>
                      ))
                    )}
                  </div>
                ) : (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                    {lifecycle.length === 0 ? (
                      <div className="empty-state"><p>No lifecycle data.</p></div>
                    ) : (
                      lifecycle.map((lc, i) => (
                        <div key={i} style={{
                          padding: 10, background: 'var(--bg-secondary)', borderRadius: 8, fontSize: 13,
                          display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                        }}>
                          <div>
                            <span style={{
                              fontWeight: 600, textTransform: 'capitalize',
                            }}>
                              {phaseLabel(lc.lifecycle_phase)}
                            </span>
                            {lc.case_number && (
                              <span style={{ marginLeft: 8, fontSize: 11, color: 'var(--text-muted)' }}>
                                Case: {lc.case_number}
                              </span>
                            )}
                          </div>
                          <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>
                            {lc.phase_start_date ? new Date(lc.phase_start_date).toLocaleDateString() : '—'}
                            {lc.events_in_phase > 1 && (
                              <span style={{ marginLeft: 8 }}>({lc.events_in_phase} events)</span>
                            )}
                          </div>
                        </div>
                      ))
                    )}
                  </div>
                )}
              </div>
            </>
          ) : (
            <div className="empty-state"><p>Select an actor to view recidivism details</p></div>
          )}
        </div>
      </div>
    </div>
  );
}

export default RecidivismDashboard;
