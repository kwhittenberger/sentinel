import { useState, useEffect } from 'react';
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
  PieChart,
  Pie,
  Cell,
} from 'recharts';
import type { ComparisonStats } from './types';
import { fetchComparisonStats, fetchSanctuaryCorrelation } from './api';

interface ComparisonChartsProps {
  dateStart?: string;
  dateEnd?: string;
}

const COLORS = {
  enforcement: '#3b82f6', // blue
  crime: '#ef4444',       // red
  sanctuary: '#22c55e',   // green
  anti_sanctuary: '#f97316', // orange
  neutral: '#8b5cf6',     // purple
  unknown: '#6b7280',     // gray
};

export function ComparisonCharts({ dateStart, dateEnd }: ComparisonChartsProps) {
  const [comparisonStats, setComparisonStats] = useState<ComparisonStats | null>(null);
  const [sanctuaryData, setSanctuaryData] = useState<Record<string, unknown> | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function loadData() {
      setLoading(true);
      setError(null);
      try {
        const [comparison, sanctuary] = await Promise.all([
          fetchComparisonStats(dateStart, dateEnd),
          fetchSanctuaryCorrelation(dateStart, dateEnd),
        ]);
        setComparisonStats(comparison);
        setSanctuaryData(sanctuary);
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to load data');
      } finally {
        setLoading(false);
      }
    }
    loadData();
  }, [dateStart, dateEnd]);

  if (loading) {
    return <div className="comparison-charts loading">Loading comparison data...</div>;
  }

  if (error) {
    return <div className="comparison-charts error">Error: {error}</div>;
  }

  if (!comparisonStats) {
    return <div className="comparison-charts empty">No data available</div>;
  }

  // Prepare data for category comparison
  const categoryData = [
    {
      name: 'Incidents',
      Enforcement: comparisonStats.enforcement_incidents,
      Crime: comparisonStats.crime_incidents,
    },
    {
      name: 'Deaths',
      Enforcement: comparisonStats.enforcement_deaths,
      Crime: comparisonStats.crime_deaths,
    },
  ];

  // Prepare data for jurisdiction comparison (top 10 by total incidents)
  const jurisdictionData = [...(comparisonStats.by_jurisdiction || [])]
    .sort((a, b) => (b.enforcement_incidents + b.crime_incidents) - (a.enforcement_incidents + a.crime_incidents))
    .slice(0, 10)
    .map(j => ({
      name: j.name.length > 12 ? j.name.substring(0, 12) + '...' : j.name,
      Enforcement: j.enforcement_incidents,
      Crime: j.crime_incidents,
      EnforcementDeaths: j.enforcement_deaths,
      CrimeDeaths: j.crime_deaths,
    }));

  // Prepare sanctuary correlation data
  const sanctuaryByStatus = sanctuaryData?.by_sanctuary_status as Record<string, { incidents: number; deaths: number }> | undefined;
  const sanctuaryPieData = sanctuaryByStatus
    ? Object.entries(sanctuaryByStatus).map(([status, data]) => ({
        name: status.replace('_', ' '),
        value: data.incidents,
        deaths: data.deaths,
      }))
    : [];

  const PIE_COLORS = [COLORS.sanctuary, COLORS.anti_sanctuary, COLORS.neutral, COLORS.unknown];

  return (
    <div className="comparison-charts">
      <h2>Cross-Category Analysis</h2>

      <div className="charts-grid">
        {/* Category Comparison */}
        <div className="chart-card">
          <h3>Enforcement vs Crime Incidents</h3>
          <ResponsiveContainer width="100%" height={300}>
            <BarChart data={categoryData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#333" />
              <XAxis dataKey="name" stroke="#888" />
              <YAxis stroke="#888" />
              <Tooltip
                contentStyle={{ backgroundColor: '#1a1a1a', border: '1px solid #333' }}
              />
              <Legend />
              <Bar dataKey="Enforcement" fill={COLORS.enforcement} />
              <Bar dataKey="Crime" fill={COLORS.crime} />
            </BarChart>
          </ResponsiveContainer>
        </div>

        {/* Jurisdiction Breakdown */}
        <div className="chart-card">
          <h3>Top States by Incidents</h3>
          <ResponsiveContainer width="100%" height={300}>
            <BarChart data={jurisdictionData} layout="vertical">
              <CartesianGrid strokeDasharray="3 3" stroke="#333" />
              <XAxis type="number" stroke="#888" />
              <YAxis dataKey="name" type="category" stroke="#888" width={80} />
              <Tooltip
                contentStyle={{ backgroundColor: '#1a1a1a', border: '1px solid #333' }}
              />
              <Legend />
              <Bar dataKey="Enforcement" stackId="a" fill={COLORS.enforcement} />
              <Bar dataKey="Crime" stackId="a" fill={COLORS.crime} />
            </BarChart>
          </ResponsiveContainer>
        </div>

        {/* Sanctuary Policy Correlation */}
        {sanctuaryPieData.length > 0 && (
          <div className="chart-card">
            <h3>Incidents by Sanctuary Status</h3>
            <ResponsiveContainer width="100%" height={300}>
              <PieChart>
                <Pie
                  data={sanctuaryPieData}
                  cx="50%"
                  cy="50%"
                  labelLine={false}
                  label={({ name, percent }) => `${name} (${((percent ?? 0) * 100).toFixed(0)}%)`}
                  outerRadius={100}
                  fill="#8884d8"
                  dataKey="value"
                >
                  {sanctuaryPieData.map((_, index) => (
                    <Cell key={`cell-${index}`} fill={PIE_COLORS[index % PIE_COLORS.length]} />
                  ))}
                </Pie>
                <Tooltip
                  contentStyle={{ backgroundColor: '#1a1a1a', border: '1px solid #333' }}
                  formatter={(value, name, props) => {
                    const payload = props?.payload as { deaths?: number } | undefined;
                    return [
                      `${value} incidents${payload?.deaths ? ` (${payload.deaths} deaths)` : ''}`,
                      name,
                    ];
                  }}
                />
              </PieChart>
            </ResponsiveContainer>
          </div>
        )}

        {/* Summary Stats */}
        <div className="chart-card stats-card">
          <h3>Summary</h3>
          <div className="stats-grid">
            <div className="stat-item">
              <span className="stat-value" style={{ color: COLORS.enforcement }}>
                {comparisonStats.enforcement_incidents.toLocaleString()}
              </span>
              <span className="stat-label">Enforcement Incidents</span>
            </div>
            <div className="stat-item">
              <span className="stat-value" style={{ color: COLORS.crime }}>
                {comparisonStats.crime_incidents.toLocaleString()}
              </span>
              <span className="stat-label">Crime Incidents</span>
            </div>
            <div className="stat-item">
              <span className="stat-value" style={{ color: COLORS.enforcement }}>
                {comparisonStats.enforcement_deaths.toLocaleString()}
              </span>
              <span className="stat-label">Enforcement Deaths</span>
            </div>
            <div className="stat-item">
              <span className="stat-value" style={{ color: COLORS.crime }}>
                {comparisonStats.crime_deaths.toLocaleString()}
              </span>
              <span className="stat-label">Crime-Related Deaths</span>
            </div>
          </div>
        </div>
      </div>

      <style>{`
        .comparison-charts {
          padding: 1rem;
        }

        .comparison-charts h2 {
          margin-top: 0;
          margin-bottom: 1.5rem;
        }

        .charts-grid {
          display: grid;
          grid-template-columns: repeat(auto-fit, minmax(400px, 1fr));
          gap: 1.5rem;
        }

        .chart-card {
          background: #1a1a1a;
          border: 1px solid #333;
          border-radius: 8px;
          padding: 1rem;
        }

        .chart-card h3 {
          margin-top: 0;
          margin-bottom: 1rem;
          font-size: 1rem;
          color: #ccc;
        }

        .stats-card .stats-grid {
          display: grid;
          grid-template-columns: 1fr 1fr;
          gap: 1rem;
        }

        .stat-item {
          text-align: center;
          padding: 1rem;
          background: #222;
          border-radius: 4px;
        }

        .stat-value {
          display: block;
          font-size: 2rem;
          font-weight: bold;
        }

        .stat-label {
          display: block;
          font-size: 0.75rem;
          color: #888;
          margin-top: 0.25rem;
        }

        .loading, .error, .empty {
          text-align: center;
          padding: 2rem;
          color: #888;
        }

        .error {
          color: #ef4444;
        }
      `}</style>
    </div>
  );
}

export default ComparisonCharts;
