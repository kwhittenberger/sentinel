import type { Stats } from '../types';

interface StatsBarProps {
  stats: Stats;
  statsCollapsed: boolean;
  toggleStats: () => void;
}

export function StatsBar({ stats, statsCollapsed, toggleStats }: StatsBarProps) {
  return (
    <div className={`stats-section ${statsCollapsed ? 'stats-collapsed' : ''}`}>
      <button className="stats-toggle-btn" onClick={toggleStats} title={statsCollapsed ? 'Expand stats' : 'Collapse stats'} aria-label={statsCollapsed ? 'Expand stats' : 'Collapse stats'}>
        {statsCollapsed ? '\u25BC' : '\u25B2'}
      </button>
      {statsCollapsed ? (
        <div className="stats-bar-compact">
          <span><strong>{stats.total_incidents}</strong> incidents</span>
          <span><strong>{stats.incident_stats?.fatal_outcomes ?? 0}</strong> fatal</span>
          <span><strong>{stats.incident_stats?.serious_injuries ?? 0}</strong> serious</span>
          <span><strong>{stats.incident_stats?.events_tracked ?? 0}</strong> events</span>
          <span>
            {stats.incident_stats?.avg_confidence != null
              ? <><strong>{(stats.incident_stats.avg_confidence * 100).toFixed(0)}%</strong> confidence</>
              : '\u2014'}
          </span>
        </div>
      ) : (
        <div className="stats-grid">
          <div className="stat-card">
            <div className="stat-value">{stats.total_incidents}</div>
            <div className="stat-label">Total Incidents</div>
          </div>
          <div className="stat-card">
            <div className="stat-value">{stats.incident_stats?.fatal_outcomes ?? 0}</div>
            <div className="stat-label">Fatal Outcomes</div>
          </div>
          <div className="stat-card">
            <div className="stat-value">{stats.incident_stats?.serious_injuries ?? 0}</div>
            <div className="stat-label">Serious Injuries</div>
          </div>
          <div className="stat-card">
            <div className="stat-value">
              {stats.incident_stats?.domain_counts
                ? Object.keys(stats.incident_stats.domain_counts).length
                : 0}
            </div>
            <div className="stat-label">Domains</div>
            {stats.incident_stats?.domain_counts && (
              <div className="stat-domain-bars">
                {Object.entries(stats.incident_stats.domain_counts).slice(0, 3).map(([name, count]) => (
                  <div key={name} className="stat-domain-row">
                    <span className="stat-domain-name">{name}</span>
                    <span className="stat-domain-count">{count}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
          <div className="stat-card">
            <div className="stat-value">{stats.incident_stats?.events_tracked ?? 0}</div>
            <div className="stat-label">Events Tracked</div>
          </div>
          <div className="stat-card">
            <div className="stat-value">
              {stats.incident_stats?.avg_confidence != null
                ? `${(stats.incident_stats.avg_confidence * 100).toFixed(0)}%`
                : '\u2014'}
            </div>
            <div className="stat-label">Avg Confidence</div>
          </div>
        </div>
      )}
    </div>
  );
}
