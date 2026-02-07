import { useState, useEffect, useCallback } from 'react';

const API_BASE = '/api';

interface OverviewStats {
  total_incidents: number;
  enforcement_incidents: number;
  crime_incidents: number;
  total_deaths: number;
  states_affected: number;
  queue_stats: Record<string, number>;
  ingested_total: number;
  approved_total: number;
  rejected_total: number;
  pending_review: number;
}

interface FunnelStage {
  stage: string;
  count: number;
}

interface SourceStats {
  source_name: string;
  total: number;
  approved: number;
  rejected: number;
  avg_confidence: number | null;
  approval_rate: number;
}

interface StateStats {
  state: string;
  total: number;
  enforcement: number;
  crime: number;
  deaths: number;
}

interface AnalyticsDashboardProps {
  onClose?: () => void;
}

export function AnalyticsDashboard({ onClose }: AnalyticsDashboardProps) {
  const [loading, setLoading] = useState(true);
  const [dateStart, setDateStart] = useState('');
  const [dateEnd, setDateEnd] = useState('');
  const [overview, setOverview] = useState<OverviewStats | null>(null);
  const [funnel, setFunnel] = useState<FunnelStage[]>([]);
  const [sources, setSources] = useState<SourceStats[]>([]);
  const [states, setStates] = useState<StateStats[]>([]);

  const loadAnalytics = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (dateStart) params.set('date_start', dateStart);
      if (dateEnd) params.set('date_end', dateEnd);

      const [overviewRes, conversionRes, sourcesRes, geoRes] = await Promise.all([
        fetch(`${API_BASE}/admin/analytics/overview?${params}`),
        fetch(`${API_BASE}/admin/analytics/conversion?${params}`),
        fetch(`${API_BASE}/admin/analytics/sources?${params}`),
        fetch(`${API_BASE}/admin/analytics/geographic?${params}`),
      ]);

      if (overviewRes.ok) {
        setOverview(await overviewRes.json());
      }
      if (conversionRes.ok) {
        const data = await conversionRes.json();
        setFunnel(data.funnel || []);
      }
      if (sourcesRes.ok) {
        const data = await sourcesRes.json();
        setSources(data.sources || []);
      }
      if (geoRes.ok) {
        const data = await geoRes.json();
        setStates(data.states || []);
      }
    } finally {
      setLoading(false);
    }
  }, [dateStart, dateEnd]);

  useEffect(() => {
    loadAnalytics();
  }, [loadAnalytics]);

  const getMaxFunnelCount = () => {
    return Math.max(...funnel.map(f => f.count), 1);
  };

  const getMaxStateTotal = () => {
    return Math.max(...states.map(s => s.total), 1);
  };

  return (
    <div className="analytics-dashboard">
      <div className="dashboard-header">
        <h2>Analytics</h2>
        <div className="header-actions">
          <div className="date-range">
            <input
              type="date"
              value={dateStart}
              onChange={e => setDateStart(e.target.value)}
              className="date-input"
            />
            <span className="date-sep">to</span>
            <input
              type="date"
              value={dateEnd}
              onChange={e => setDateEnd(e.target.value)}
              className="date-input"
            />
            <button className="action-btn" onClick={loadAnalytics}>
              Apply
            </button>
          </div>
          {onClose && (
            <button className="admin-close-btn" onClick={onClose} aria-label="Close analytics dashboard">&times;</button>
          )}
        </div>
      </div>

      {loading ? (
        <div className="admin-loading">Loading analytics...</div>
      ) : (
        <div className="analytics-content">
          {/* Overview Stats */}
          {overview && (
            <div className="stats-grid">
              <div className="stat-card">
                <div className="stat-value">{overview.total_incidents}</div>
                <div className="stat-label">Total Incidents</div>
              </div>
              <div className="stat-card">
                <div className="stat-value">{overview.enforcement_incidents}</div>
                <div className="stat-label">Enforcement</div>
              </div>
              <div className="stat-card">
                <div className="stat-value">{overview.crime_incidents}</div>
                <div className="stat-label">Crime</div>
              </div>
              <div className="stat-card danger">
                <div className="stat-value">{overview.total_deaths}</div>
                <div className="stat-label">Deaths</div>
              </div>
              <div className="stat-card">
                <div className="stat-value">{overview.states_affected}</div>
                <div className="stat-label">States Affected</div>
              </div>
              <div className="stat-card highlight">
                <div className="stat-value">{overview.pending_review}</div>
                <div className="stat-label">Pending Review</div>
              </div>
            </div>
          )}

          <div className="analytics-grid">
            {/* Conversion Funnel */}
            <div className="analytics-card">
              <h3>Conversion Funnel</h3>
              <div className="funnel-chart">
                {funnel.map((stage, index) => (
                  <div key={stage.stage} className="funnel-stage">
                    <div className="stage-label">{stage.stage}</div>
                    <div className="stage-bar-container">
                      <div
                        className="stage-bar"
                        style={{
                          width: `${(stage.count / getMaxFunnelCount()) * 100}%`,
                          backgroundColor: index === 0 ? '#3b82f6' : index === 1 ? '#22c55e' : '#10b981'
                        }}
                      />
                      <span className="stage-count">{stage.count}</span>
                    </div>
                  </div>
                ))}
              </div>
              {overview && (
                <div className="funnel-summary">
                  <div className="summary-item">
                    <span className="label">Approval Rate:</span>
                    <span className="value">
                      {overview.ingested_total > 0
                        ? ((overview.approved_total / overview.ingested_total) * 100).toFixed(1)
                        : 0}%
                    </span>
                  </div>
                  <div className="summary-item">
                    <span className="label">Rejection Rate:</span>
                    <span className="value">
                      {overview.ingested_total > 0
                        ? ((overview.rejected_total / overview.ingested_total) * 100).toFixed(1)
                        : 0}%
                    </span>
                  </div>
                </div>
              )}
            </div>

            {/* Category Breakdown */}
            {overview && (
              <div className="analytics-card">
                <h3>Category Distribution</h3>
                <div className="category-chart">
                  <div className="pie-container">
                    <div
                      className="pie-chart"
                      style={{
                        background: `conic-gradient(
                          #3b82f6 0% ${(overview.enforcement_incidents / (overview.total_incidents || 1)) * 100}%,
                          #22c55e ${(overview.enforcement_incidents / (overview.total_incidents || 1)) * 100}% 100%
                        )`
                      }}
                    />
                  </div>
                  <div className="pie-legend">
                    <div className="legend-item">
                      <span className="legend-color" style={{ backgroundColor: '#3b82f6' }} />
                      <span>Enforcement ({overview.enforcement_incidents})</span>
                    </div>
                    <div className="legend-item">
                      <span className="legend-color" style={{ backgroundColor: '#22c55e' }} />
                      <span>Crime ({overview.crime_incidents})</span>
                    </div>
                  </div>
                </div>
              </div>
            )}
          </div>

          {/* Source Breakdown */}
          {sources.length > 0 && (
            <div className="analytics-card full-width">
              <h3>Source Performance</h3>
              <table className="analytics-table">
                <thead>
                  <tr>
                    <th>Source</th>
                    <th>Total</th>
                    <th>Approved</th>
                    <th>Rejected</th>
                    <th>Approval Rate</th>
                    <th>Avg Confidence</th>
                  </tr>
                </thead>
                <tbody>
                  {sources.map(source => (
                    <tr key={source.source_name}>
                      <td>{source.source_name}</td>
                      <td>{source.total}</td>
                      <td className="success">{source.approved}</td>
                      <td className="danger">{source.rejected}</td>
                      <td>
                        <div className="progress-cell">
                          <div
                            className="mini-bar"
                            style={{ width: `${source.approval_rate * 100}%` }}
                          />
                          <span>{(source.approval_rate * 100).toFixed(0)}%</span>
                        </div>
                      </td>
                      <td>
                        {source.avg_confidence ? `${(source.avg_confidence * 100).toFixed(0)}%` : '-'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {/* Geographic Breakdown */}
          {states.length > 0 && (
            <div className="analytics-card full-width">
              <h3>Geographic Distribution</h3>
              <div className="state-bars">
                {states.slice(0, 15).map(state => (
                  <div key={state.state} className="state-bar">
                    <div className="state-label">{state.state}</div>
                    <div className="state-bar-container">
                      <div
                        className="bar-segment enforcement"
                        style={{ width: `${(state.enforcement / getMaxStateTotal()) * 100}%` }}
                        title={`Enforcement: ${state.enforcement}`}
                      />
                      <div
                        className="bar-segment crime"
                        style={{
                          width: `${(state.crime / getMaxStateTotal()) * 100}%`,
                          left: `${(state.enforcement / getMaxStateTotal()) * 100}%`
                        }}
                        title={`Crime: ${state.crime}`}
                      />
                    </div>
                    <div className="state-total">{state.total}</div>
                  </div>
                ))}
              </div>
              <div className="bar-legend">
                <div className="legend-item">
                  <span className="legend-color enforcement" />
                  <span>Enforcement</span>
                </div>
                <div className="legend-item">
                  <span className="legend-color crime" />
                  <span>Crime</span>
                </div>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default AnalyticsDashboard;
