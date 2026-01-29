import { useState } from 'react';
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, PieChart, Pie, Cell, LineChart, Line, ResponsiveContainer } from 'recharts';
import type { Stats, Incident, IncidentCategory } from './types';

interface ChartsProps {
  stats: Stats | null;
  incidents: Incident[];
}

const COLORS = ['#3b82f6', '#f97316', '#dc2626', '#10b981', '#8b5cf6', '#ec4899', '#06b6d4', '#f59e0b'];
const CATEGORY_COLORS = { enforcement: '#dc2626', crime: '#7c3aed' };

export function Charts({ stats, incidents }: ChartsProps) {
  const [categoryFilter, setCategoryFilter] = useState<IncidentCategory | 'all'>('all');

  if (!stats) return <div className="charts-loading">Loading charts...</div>;

  // Filter incidents by category if selected
  const filteredIncidents = categoryFilter === 'all'
    ? incidents
    : incidents.filter(i => i.category === categoryFilter);

  // Prepare data for state bar chart (with category breakdown)
  const stateDataRaw = filteredIncidents.reduce((acc, inc) => {
    const state = inc.state || 'Unknown';
    if (!acc[state]) acc[state] = { state, enforcement: 0, crime: 0, total: 0 };
    const cat = inc.category || 'enforcement';
    acc[state][cat]++;
    acc[state].total++;
    return acc;
  }, {} as Record<string, { state: string; enforcement: number; crime: number; total: number }>);

  const stateData = Object.values(stateDataRaw)
    .sort((a, b) => b.total - a.total)
    .slice(0, 10);

  // Prepare data for incident type pie chart
  const typeDataRaw = filteredIncidents.reduce((acc, inc) => {
    const type = inc.incident_type || 'unknown';
    if (!acc[type]) acc[type] = 0;
    acc[type]++;
    return acc;
  }, {} as Record<string, number>);

  const typeData = Object.entries(typeDataRaw)
    .map(([type, count]) => ({
      name: type.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase()),
      value: count
    }))
    .sort((a, b) => b.value - a.value)
    .slice(0, 8);

  // Prepare data for timeline with category breakdown
  const timelineData = filteredIncidents.reduce((acc, inc) => {
    if (!inc.date) return acc;
    const month = inc.date.substring(0, 7); // YYYY-MM
    if (!acc[month]) acc[month] = { month, total: 0, deaths: 0, enforcement: 0, crime: 0 };
    acc[month].total++;
    if (inc.is_death) acc[month].deaths++;
    const cat = inc.category || 'enforcement';
    acc[month][cat]++;
    return acc;
  }, {} as Record<string, { month: string; total: number; deaths: number; enforcement: number; crime: number }>);

  const timelineArray = Object.values(timelineData)
    .sort((a, b) => a.month.localeCompare(b.month));

  // Prepare tier breakdown
  const tierDataRaw = filteredIncidents.reduce((acc, inc) => {
    const tier = inc.tier || 4;
    if (!acc[tier]) acc[tier] = 0;
    acc[tier]++;
    return acc;
  }, {} as Record<number, number>);

  const tierData = [1, 2, 3, 4].map(tier => ({
    tier: `Tier ${tier}`,
    count: tierDataRaw[tier] || 0,
    description: tier === 1 ? 'Deaths' : tier === 2 ? 'Force' : tier === 3 ? 'Confrontations' : 'Related'
  }));

  // Category breakdown data
  const categoryData = [
    { name: 'Enforcement', value: stats.by_category?.enforcement || 0, color: CATEGORY_COLORS.enforcement },
    { name: 'Crime', value: stats.by_category?.crime || 0, color: CATEGORY_COLORS.crime },
  ];

  // Calculate filtered stats
  const filteredTotal = filteredIncidents.length;
  const filteredDeaths = filteredIncidents.filter(i => i.is_death).length;
  const filteredNonImmigrant = filteredIncidents.filter(i => i.is_non_immigrant).length;
  const filteredStates = new Set(filteredIncidents.map(i => i.state).filter(Boolean)).size;

  return (
    <div className="charts-container">
      {/* Category Filter */}
      <div className="charts-filter-bar">
        <label>Filter by Category:</label>
        <select
          value={categoryFilter}
          onChange={(e) => setCategoryFilter(e.target.value as IncidentCategory | 'all')}
          className="category-select"
        >
          <option value="all">All Categories</option>
          <option value="enforcement">Enforcement Only</option>
          <option value="crime">Crime Only</option>
        </select>
        <span className="filter-summary">
          Showing {filteredTotal} incidents ({filteredDeaths} deaths) across {filteredStates} states
        </span>
      </div>

      {/* Category Breakdown Summary */}
      {categoryFilter === 'all' && (
        <div className="category-summary">
          <div className="category-stat enforcement">
            <span className="category-value">{stats.by_category?.enforcement || 0}</span>
            <span className="category-label">Enforcement</span>
          </div>
          <div className="category-stat crime">
            <span className="category-value">{stats.by_category?.crime || 0}</span>
            <span className="category-label">Crime</span>
          </div>
          <div className="category-stat non-immigrant">
            <span className="category-value">{filteredNonImmigrant}</span>
            <span className="category-label">Non-Immigrant Involved</span>
          </div>
        </div>
      )}

      <div className="charts-grid">
        {/* Timeline Chart */}
        <div className="chart-card chart-wide">
          <h3>Incidents Over Time {categoryFilter !== 'all' && `(${categoryFilter})`}</h3>
          <ResponsiveContainer width="100%" height={250}>
            <LineChart data={timelineArray} margin={{ top: 5, right: 30, left: 0, bottom: 5 }}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="month" tick={{ fontSize: 11 }} />
              <YAxis tick={{ fontSize: 11 }} />
              <Tooltip />
              <Legend />
              {categoryFilter === 'all' ? (
                <>
                  <Line type="monotone" dataKey="enforcement" stroke={CATEGORY_COLORS.enforcement} strokeWidth={2} name="Enforcement" />
                  <Line type="monotone" dataKey="crime" stroke={CATEGORY_COLORS.crime} strokeWidth={2} name="Crime" />
                </>
              ) : (
                <Line type="monotone" dataKey="total" stroke="#3b82f6" strokeWidth={2} name="Total Incidents" />
              )}
              <Line type="monotone" dataKey="deaths" stroke="#000000" strokeWidth={2} strokeDasharray="5 5" name="Deaths" />
            </LineChart>
          </ResponsiveContainer>
        </div>

        {/* State Bar Chart - Stacked by Category */}
        <div className="chart-card">
          <h3>Top States by Incidents</h3>
          <ResponsiveContainer width="100%" height={250}>
            <BarChart data={stateData} layout="vertical" margin={{ top: 5, right: 30, left: 60, bottom: 5 }}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis type="number" tick={{ fontSize: 11 }} />
              <YAxis type="category" dataKey="state" tick={{ fontSize: 11 }} width={55} />
              <Tooltip />
              <Legend />
              {categoryFilter === 'all' ? (
                <>
                  <Bar dataKey="enforcement" stackId="a" fill={CATEGORY_COLORS.enforcement} name="Enforcement" />
                  <Bar dataKey="crime" stackId="a" fill={CATEGORY_COLORS.crime} name="Crime" />
                </>
              ) : (
                <Bar dataKey="total" fill="#3b82f6" name="Incidents" />
              )}
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

        {/* Category Breakdown Pie Chart - only show when viewing all */}
        {categoryFilter === 'all' && (
          <div className="chart-card">
            <h3>By Category</h3>
            <ResponsiveContainer width="100%" height={250}>
              <PieChart>
                <Pie
                  data={categoryData}
                  cx="50%"
                  cy="50%"
                  innerRadius={50}
                  outerRadius={90}
                  paddingAngle={2}
                  dataKey="value"
                  label={({ name, percent }) => `${name} (${((percent ?? 0) * 100).toFixed(0)}%)`}
                  labelLine={false}
                >
                  {categoryData.map((entry, index) => (
                    <Cell key={`cell-${index}`} fill={entry.color} />
                  ))}
                </Pie>
                <Tooltip />
              </PieChart>
            </ResponsiveContainer>
          </div>
        )}

        {/* Summary Stats */}
        <div className="chart-card chart-wide">
          <h3>Quick Statistics {categoryFilter !== 'all' && `(${categoryFilter})`}</h3>
          <div className="quick-stats">
            <div className="quick-stat">
              <span className="quick-stat-value">{filteredTotal > 0 ? ((filteredDeaths / filteredTotal) * 100).toFixed(1) : '0'}%</span>
              <span className="quick-stat-label">Fatality Rate</span>
            </div>
            <div className="quick-stat">
              <span className="quick-stat-value">{filteredTotal > 0 ? ((filteredNonImmigrant / filteredTotal) * 100).toFixed(1) : '0'}%</span>
              <span className="quick-stat-label">Non-Immigrant Involved</span>
            </div>
            <div className="quick-stat">
              <span className="quick-stat-value">{filteredStates > 0 ? (filteredTotal / filteredStates).toFixed(1) : '0'}</span>
              <span className="quick-stat-label">Avg Incidents/State</span>
            </div>
            <div className="quick-stat">
              <span className="quick-stat-value">{timelineArray.length > 0 ? (filteredTotal / timelineArray.length).toFixed(1) : '0'}</span>
              <span className="quick-stat-label">Avg Incidents/Month</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
