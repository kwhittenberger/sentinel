import { useState, useEffect, useCallback } from 'react';

const API_BASE = '';

interface ProsecutorStat {
  prosecutor_id: string | null;
  prosecutor_name: string;
  total_cases: number;
  convictions: number;
  acquittals: number;
  dismissals: number;
  plea_bargains: number;
  conviction_rate: number;
  charges_amended: number;
  charges_dismissed_count: number;
  avg_bail_requested: number | null;
  avg_sentence_days: number | null;
  data_completeness_pct: number;
  refreshed_at: string | null;
}

export function ProsecutorDashboard() {
  const [stats, setStats] = useState<ProsecutorStat[]>([]);
  const [selectedProsecutor, setSelectedProsecutor] = useState<ProsecutorStat | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadStats = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/api/admin/prosecutor-stats`);
      if (!res.ok) throw new Error('Failed to load prosecutor stats');
      const data = await res.json();
      setStats(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load stats');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadStats();
  }, [loadStats]);

  const handleRefresh = async () => {
    setRefreshing(true);
    try {
      await fetch(`${API_BASE}/api/admin/prosecutor-stats/refresh`, { method: 'POST' });
      await loadStats();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to refresh stats');
    } finally {
      setRefreshing(false);
    }
  };

  const formatRate = (rate: number) => `${(rate * 100).toFixed(1)}%`;
  const formatDays = (days: number | null) => days != null ? `${Math.round(days)} days` : 'N/A';
  const formatMoney = (amount: number | null) => amount != null ? `$${amount.toLocaleString(undefined, { maximumFractionDigits: 0 })}` : 'N/A';

  if (loading) {
    return <div className="admin-loading">Loading prosecutor stats...</div>;
  }

  return (
    <div className="admin-page">
      <div className="page-header">
        <h2>Prosecutor Dashboard</h2>
        <div className="page-actions">
          <button
            className="action-btn"
            onClick={handleRefresh}
            disabled={refreshing}
          >
            {refreshing ? 'Refreshing...' : 'Refresh Stats'}
          </button>
        </div>
      </div>

      {error && <div className="error-banner">{error}</div>}

      {stats.length === 0 ? (
        <div className="empty-state">
          <p>No prosecutor data available. Stats are populated from prosecutorial actions.</p>
        </div>
      ) : (
        <>
          {/* Summary Cards */}
          <div className="dashboard-stats" style={{ marginBottom: 24 }}>
            <div className="stat-card">
              <div className="stat-value">{stats.length}</div>
              <div className="stat-label">Prosecutors</div>
            </div>
            <div className="stat-card">
              <div className="stat-value">
                {stats.reduce((sum, s) => sum + s.total_cases, 0)}
              </div>
              <div className="stat-label">Total Cases</div>
            </div>
            <div className="stat-card">
              <div className="stat-value">
                {stats.length > 0
                  ? formatRate(stats.reduce((sum, s) => sum + s.conviction_rate, 0) / stats.length)
                  : 'N/A'}
              </div>
              <div className="stat-label">Avg Conviction Rate</div>
            </div>
            <div className="stat-card">
              <div className="stat-value">
                {stats.reduce((sum, s) => sum + s.dismissals, 0)}
              </div>
              <div className="stat-label">Total Dismissals</div>
            </div>
          </div>

          <div className="split-view">
            {/* Prosecutors Table */}
            <div className="list-panel" style={{ minWidth: 400 }}>
              <div className="list-header">
                <h3>Prosecutors ({stats.length})</h3>
              </div>
              <div className="table-container" style={{ border: 'none' }}>
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Name</th>
                      <th>Cases</th>
                      <th>Conv %</th>
                      <th>Dismiss</th>
                    </tr>
                  </thead>
                  <tbody>
                    {stats.map((s) => (
                      <tr
                        key={s.prosecutor_id || s.prosecutor_name}
                        className={selectedProsecutor?.prosecutor_id === s.prosecutor_id ? 'selected' : ''}
                        onClick={() => setSelectedProsecutor(s)}
                        style={{ cursor: 'pointer' }}
                      >
                        <td style={{ fontWeight: 500 }}>{s.prosecutor_name}</td>
                        <td>{s.total_cases}</td>
                        <td style={{ fontWeight: 600, color: s.conviction_rate > 0.8 ? '#ef4444' : s.conviction_rate > 0.5 ? '#f59e0b' : '#22c55e' }}>
                          {formatRate(s.conviction_rate)}
                        </td>
                        <td>{s.dismissals}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>

            {/* Prosecutor Detail */}
            <div className="detail-panel">
              {selectedProsecutor ? (
                <>
                  <div className="detail-header">
                    <h3>{selectedProsecutor.prosecutor_name}</h3>
                  </div>

                  <div className="detail-content">
                    {/* Case Outcomes */}
                    <div className="detail-section">
                      <h4 style={{ marginBottom: 12 }}>Case Outcomes</h4>
                      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 12 }}>
                        <div className="stat-card" style={{ padding: 12, textAlign: 'center' }}>
                          <div style={{ fontSize: 24, fontWeight: 700 }}>{selectedProsecutor.convictions}</div>
                          <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>Convictions</div>
                        </div>
                        <div className="stat-card" style={{ padding: 12, textAlign: 'center' }}>
                          <div style={{ fontSize: 24, fontWeight: 700 }}>{selectedProsecutor.acquittals}</div>
                          <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>Acquittals</div>
                        </div>
                        <div className="stat-card" style={{ padding: 12, textAlign: 'center' }}>
                          <div style={{ fontSize: 24, fontWeight: 700 }}>{selectedProsecutor.dismissals}</div>
                          <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>Dismissals</div>
                        </div>
                        <div className="stat-card" style={{ padding: 12, textAlign: 'center' }}>
                          <div style={{ fontSize: 24, fontWeight: 700 }}>{selectedProsecutor.plea_bargains}</div>
                          <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>Pleas</div>
                        </div>
                        <div className="stat-card" style={{ padding: 12, textAlign: 'center' }}>
                          <div style={{ fontSize: 24, fontWeight: 700 }}>{selectedProsecutor.charges_amended}</div>
                          <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>Amended</div>
                        </div>
                        <div className="stat-card" style={{ padding: 12, textAlign: 'center' }}>
                          <div style={{ fontSize: 24, fontWeight: 700 }}>{selectedProsecutor.charges_dismissed_count}</div>
                          <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>Charges Dropped</div>
                        </div>
                      </div>
                    </div>

                    {/* Key Metrics */}
                    <div className="detail-section" style={{ marginTop: 20 }}>
                      <h4 style={{ marginBottom: 12 }}>Key Metrics</h4>
                      <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13 }}>
                          <span style={{ color: 'var(--text-secondary)' }}>Conviction Rate</span>
                          <span style={{ fontWeight: 600 }}>{formatRate(selectedProsecutor.conviction_rate)}</span>
                        </div>
                        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13 }}>
                          <span style={{ color: 'var(--text-secondary)' }}>Avg Sentence</span>
                          <span style={{ fontWeight: 600 }}>{formatDays(selectedProsecutor.avg_sentence_days)}</span>
                        </div>
                        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13 }}>
                          <span style={{ color: 'var(--text-secondary)' }}>Avg Bail Requested</span>
                          <span style={{ fontWeight: 600 }}>{formatMoney(selectedProsecutor.avg_bail_requested)}</span>
                        </div>
                        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13 }}>
                          <span style={{ color: 'var(--text-secondary)' }}>Data Completeness</span>
                          <span style={{ fontWeight: 600 }}>{selectedProsecutor.data_completeness_pct}%</span>
                        </div>
                      </div>
                    </div>

                    {/* Conviction Rate Bar */}
                    <div className="detail-section" style={{ marginTop: 20 }}>
                      <h4 style={{ marginBottom: 12 }}>Outcome Distribution</h4>
                      {selectedProsecutor.total_cases > 0 && (
                        <div>
                          <div style={{ display: 'flex', height: 24, borderRadius: 4, overflow: 'hidden', marginBottom: 8 }}>
                            <div style={{
                              width: `${(selectedProsecutor.convictions / selectedProsecutor.total_cases) * 100}%`,
                              background: '#ef4444',
                            }} />
                            <div style={{
                              width: `${(selectedProsecutor.plea_bargains / selectedProsecutor.total_cases) * 100}%`,
                              background: '#f59e0b',
                            }} />
                            <div style={{
                              width: `${(selectedProsecutor.acquittals / selectedProsecutor.total_cases) * 100}%`,
                              background: '#22c55e',
                            }} />
                            <div style={{
                              width: `${(selectedProsecutor.dismissals / selectedProsecutor.total_cases) * 100}%`,
                              background: '#3b82f6',
                            }} />
                          </div>
                          <div style={{ display: 'flex', gap: 16, fontSize: 11, flexWrap: 'wrap' }}>
                            <span><span style={{ display: 'inline-block', width: 10, height: 10, background: '#ef4444', borderRadius: 2, marginRight: 4 }} />Convicted</span>
                            <span><span style={{ display: 'inline-block', width: 10, height: 10, background: '#f59e0b', borderRadius: 2, marginRight: 4 }} />Plea</span>
                            <span><span style={{ display: 'inline-block', width: 10, height: 10, background: '#22c55e', borderRadius: 2, marginRight: 4 }} />Acquitted</span>
                            <span><span style={{ display: 'inline-block', width: 10, height: 10, background: '#3b82f6', borderRadius: 2, marginRight: 4 }} />Dismissed</span>
                          </div>
                        </div>
                      )}
                    </div>
                  </div>
                </>
              ) : (
                <div className="empty-state">
                  <p>Select a prosecutor to view details</p>
                </div>
              )}
            </div>
          </div>
        </>
      )}
    </div>
  );
}

export default ProsecutorDashboard;
