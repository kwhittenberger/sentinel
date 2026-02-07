import { useState } from 'react';
import type { Incident } from '../types';

interface IncidentListSidebarProps {
  incidents: Incident[];
  selectedIncident: Incident | null;
  onSelectIncident: (incident: Incident) => void;
  getTypeDisplayName: (name: string | undefined) => string;
  getStateDisplayName: (incident: Incident) => string;
  onExportCSV: (incidents: Incident[]) => void;
  onCopyShareLink: () => void;
}

function formatDate(dateStr: string): string {
  if (!dateStr) return 'Unknown';
  return dateStr.split('T')[0];
}

export function IncidentListSidebar({
  incidents,
  selectedIncident,
  onSelectIncident,
  getTypeDisplayName,
  getStateDisplayName,
  onExportCSV,
  onCopyShareLink,
}: IncidentListSidebarProps) {
  const [searchText, setSearchText] = useState('');
  const [incidentTypeFilter, setIncidentTypeFilter] = useState('');
  const [sortBy, setSortBy] = useState<'date-desc' | 'date-asc' | 'state' | 'type' | 'deaths-first'>('date-desc');

  // Get unique incident type names from data
  const uniqueTypeNames = [...new Set(incidents.map(i => i.incident_type).filter(Boolean))].sort();

  // Filter incidents by search and type
  let filteredIncidents = incidents.filter(incident => {
    const matchesSearch = !searchText ||
      (incident.city?.toLowerCase().includes(searchText.toLowerCase())) ||
      (incident.victim_name?.toLowerCase().includes(searchText.toLowerCase())) ||
      (incident.state?.toLowerCase().includes(searchText.toLowerCase())) ||
      (incident.incident_type?.toLowerCase().includes(searchText.toLowerCase()));
    const matchesType = !incidentTypeFilter || incident.incident_type === incidentTypeFilter;
    return matchesSearch && matchesType;
  });

  // Sort incidents
  filteredIncidents = [...filteredIncidents].sort((a, b) => {
    switch (sortBy) {
      case 'date-desc':
        return (b.date || '').localeCompare(a.date || '');
      case 'date-asc':
        return (a.date || '').localeCompare(b.date || '');
      case 'state':
        return (a.state || '').localeCompare(b.state || '') || (a.city || '').localeCompare(b.city || '');
      case 'type':
        return (a.incident_type || '').localeCompare(b.incident_type || '');
      case 'deaths-first':
        if (a.is_death && !b.is_death) return -1;
        if (!a.is_death && b.is_death) return 1;
        return (b.date || '').localeCompare(a.date || '');
      default:
        return 0;
    }
  });

  return (
    <>
      <div className="incident-header">
        <h2>Incidents ({filteredIncidents.length})</h2>
        <button
          className="export-btn"
          onClick={() => onExportCSV(filteredIncidents)}
          title="Export filtered incidents to CSV"
        >
          Export CSV
        </button>
        <button
          className="share-btn"
          onClick={onCopyShareLink}
          title="Copy link with current filters"
        >
          Share
        </button>
      </div>

      {/* Search and Filter */}
      <div className="incident-filters">
        <input
          type="text"
          placeholder="Search by name, city, state..."
          value={searchText}
          onChange={(e) => setSearchText(e.target.value)}
          className="search-input"
        />
        <div className="filter-row">
          <select
            value={incidentTypeFilter}
            onChange={(e) => setIncidentTypeFilter(e.target.value)}
            className="type-filter"
          >
            <option value="">All Types</option>
            {uniqueTypeNames.map(type => (
              <option key={type} value={type}>{getTypeDisplayName(type)}</option>
            ))}
          </select>
          <select
            value={sortBy}
            onChange={(e) => setSortBy(e.target.value as typeof sortBy)}
            className="sort-select"
          >
            <option value="date-desc">Newest First</option>
            <option value="date-asc">Oldest First</option>
            <option value="deaths-first">Deaths First</option>
            <option value="state">By State</option>
            <option value="type">By Type</option>
          </select>
        </div>
      </div>

      <div className="incident-list">
        {filteredIncidents.map((incident) => (
          <div
            key={incident.id}
            id={`incident-${incident.id}`}
            className={`incident-list-item ${selectedIncident?.id === incident.id ? 'selected' : ''} ${incident.is_death ? 'death' : ''}`}
            onClick={() => onSelectIncident(incident)}
          >
            <div className="incident-list-location">
              {incident.city}, {getStateDisplayName(incident)}
            </div>
            {incident.victim_name && (
              <div className="incident-list-name">{incident.victim_name}</div>
            )}
            <div className="incident-list-meta">
              {formatDate(incident.date)} · {getTypeDisplayName(incident.incident_type)}
              {incident.linked_ids && incident.linked_ids.length > 0 && (
                <span className="linked-badge" title={`${incident.linked_ids.length} related report(s)`}>
                  +{incident.linked_ids.length}
                </span>
              )}
            </div>
          </div>
        ))}
      </div>
    </>
  );
}
