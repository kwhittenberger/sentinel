import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, PieChart, Pie, Cell, LineChart, Line, ResponsiveContainer } from 'recharts';
import type { Stats, Incident } from './types';

interface ChartsProps {
  stats: Stats | null;
  incidents: Incident[];
}

const COLORS = ['#3b82f6', '#f97316', '#dc2626', '#10b981', '#8b5cf6', '#ec4899', '#06b6d4', '#f59e0b'];

export function Charts({ stats, incidents }: ChartsProps) {
  if (!stats) return <div className="charts-loading">Loading charts...</div>;

  // Prepare data for state bar chart
  const stateData = Object.entries(stats.by_state)
    .map(([state, count]) => ({ state, count }))
    .slice(0, 10);

  // Prepare data for incident type pie chart
  const typeData = Object.entries(stats.by_incident_type)
    .map(([type, count]) => ({
      name: type.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase()),
      value: count
    }))
    .sort((a, b) => b.value - a.value)
    .slice(0, 8);

  // Prepare data for timeline
  const timelineData = incidents.reduce((acc, inc) => {
    if (!inc.date) return acc;
    const month = inc.date.substring(0, 7); // YYYY-MM
    if (!acc[month]) acc[month] = { month, total: 0, deaths: 0 };
    acc[month].total++;
    if (inc.is_death) acc[month].deaths++;
    return acc;
  }, {} as Record<string, { month: string; total: number; deaths: number }>);

  const timelineArray = Object.values(timelineData)
    .sort((a, b) => a.month.localeCompare(b.month));

  // Prepare tier breakdown
  const tierData = [1, 2, 3, 4].map(tier => ({
    tier: `Tier ${tier}`,
    count: stats.by_tier[tier] || 0,
    description: tier === 1 ? 'Deaths' : tier === 2 ? 'Force' : tier === 3 ? 'Confrontations' : 'Related'
  }));

  return (
    <div className="charts-container">
      <div className="charts-grid">
        {/* Timeline Chart */}
        <div className="chart-card chart-wide">
          <h3>Incidents Over Time</h3>
          <ResponsiveContainer width="100%" height={250}>
            <LineChart data={timelineArray} margin={{ top: 5, right: 30, left: 0, bottom: 5 }}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="month" tick={{ fontSize: 11 }} />
              <YAxis tick={{ fontSize: 11 }} />
              <Tooltip />
              <Legend />
              <Line type="monotone" dataKey="total" stroke="#3b82f6" strokeWidth={2} name="Total Incidents" />
              <Line type="monotone" dataKey="deaths" stroke="#dc2626" strokeWidth={2} name="Deaths" />
            </LineChart>
          </ResponsiveContainer>
        </div>

        {/* State Bar Chart */}
        <div className="chart-card">
          <h3>Top States by Incidents</h3>
          <ResponsiveContainer width="100%" height={250}>
            <BarChart data={stateData} layout="vertical" margin={{ top: 5, right: 30, left: 60, bottom: 5 }}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis type="number" tick={{ fontSize: 11 }} />
              <YAxis type="category" dataKey="state" tick={{ fontSize: 11 }} width={55} />
              <Tooltip />
              <Bar dataKey="count" fill="#3b82f6" name="Incidents" />
            </BarChart>
          </ResponsiveContainer>
        </div>

        {/* Incident Type Pie Chart */}
        <div className="chart-card">
          <h3>Incidents by Type</h3>
          <ResponsiveContainer width="100%" height={250}>
            <PieChart>
              <Pie
                data={typeData}
                cx="50%"
                cy="50%"
                innerRadius={40}
                outerRadius={80}
                paddingAngle={2}
                dataKey="value"
                label={({ name, percent }) => {
                  const n = name ?? '';
                  const p = percent ?? 0;
                  return `${String(n).slice(0, 15)}${String(n).length > 15 ? '...' : ''} (${(p * 100).toFixed(0)}%)`;
                }}
                labelLine={false}
              >
                {typeData.map((_, index) => (
                  <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
                ))}
              </Pie>
              <Tooltip />
            </PieChart>
          </ResponsiveContainer>
        </div>

        {/* Tier Breakdown */}
        <div className="chart-card">
          <h3>Incidents by Confidence Tier</h3>
          <ResponsiveContainer width="100%" height={250}>
            <BarChart data={tierData} margin={{ top: 5, right: 30, left: 0, bottom: 5 }}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="tier" tick={{ fontSize: 11 }} />
              <YAxis tick={{ fontSize: 11 }} />
              <Tooltip formatter={(value, _name, props) => [value, props.payload.description]} />
              <Bar dataKey="count" name="Incidents">
                {tierData.map((_, index) => (
                  <Cell key={`cell-${index}`} fill={['#dc2626', '#f97316', '#3b82f6', '#10b981'][index]} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>

        {/* Summary Stats */}
        <div className="chart-card chart-wide">
          <h3>Quick Statistics</h3>
          <div className="quick-stats">
            <div className="quick-stat">
              <span className="quick-stat-value">{((stats.total_deaths / stats.total_incidents) * 100).toFixed(1)}%</span>
              <span className="quick-stat-label">Fatality Rate</span>
            </div>
            <div className="quick-stat">
              <span className="quick-stat-value">{((stats.non_immigrant_incidents / stats.total_incidents) * 100).toFixed(1)}%</span>
              <span className="quick-stat-label">Non-Immigrant Involved</span>
            </div>
            <div className="quick-stat">
              <span className="quick-stat-value">{(stats.total_incidents / stats.states_affected).toFixed(1)}</span>
              <span className="quick-stat-label">Avg Incidents/State</span>
            </div>
            <div className="quick-stat">
              <span className="quick-stat-value">{timelineArray.length > 0 ? (stats.total_incidents / timelineArray.length).toFixed(1) : '0'}</span>
              <span className="quick-stat-label">Avg Incidents/Month</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
