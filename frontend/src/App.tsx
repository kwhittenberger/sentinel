import { useState, useEffect } from 'react';
import { MapContainer, TileLayer, CircleMarker, Tooltip, useMap } from 'react-leaflet';
import 'leaflet/dist/leaflet.css';
import type { Incident, Stats, Filters } from './types';
import { fetchIncidents, fetchStats } from './api';
import './App.css';

// Map center changer component - only updates when center/zoom actually change
function ChangeView({ center, zoom }: { center: [number, number]; zoom: number }) {
  const map = useMap();
  useEffect(() => {
    map.setView(center, zoom);
  }, [map, center[0], center[1], zoom]);
  return null;
}

// Add small offset to prevent markers at same coords from overlapping
// Uses incident ID to generate consistent offset
function getJitteredCoords(lat: number, lon: number, id: string): [number, number] {
  // Simple hash from ID to get consistent pseudo-random offset
  let hash = 0;
  for (let i = 0; i < id.length; i++) {
    hash = ((hash << 5) - hash) + id.charCodeAt(i);
    hash = hash & hash;
  }
  // Small offset: roughly 20-50 meters (0.0002 degrees ≈ 22 meters)
  const latOffset = ((hash % 100) - 50) * 0.00004;
  const lonOffset = (((hash >> 8) % 100) - 50) * 0.00004;
  return [lat + latOffset, lon + lonOffset];
}

const STATE_CENTERS: Record<string, { center: [number, number]; zoom: number }> = {
  'All States': { center: [39.8283, -98.5795], zoom: 4 },
  'California': { center: [36.7783, -119.4179], zoom: 6 },
  'Texas': { center: [31.9686, -99.9018], zoom: 6 },
  'Florida': { center: [27.6648, -81.5158], zoom: 6 },
  'Illinois': { center: [40.6331, -89.3985], zoom: 6 },
  'Minnesota': { center: [46.7296, -94.6859], zoom: 6 },
  'New York': { center: [43.2994, -74.2179], zoom: 6 },
  'Georgia': { center: [32.1656, -82.9001], zoom: 6 },
  'Arizona': { center: [34.0489, -111.0937], zoom: 6 },
};

function App() {
  const [incidents, setIncidents] = useState<Incident[]>([]);
  const [stats, setStats] = useState<Stats | null>(null);
  const [selectedIncident, setSelectedIncident] = useState<Incident | null>(null);
  const [customView, setCustomView] = useState<{ center: [number, number]; zoom: number } | null>(null);
  const [loading, setLoading] = useState(true);
  const [mapStyle, setMapStyle] = useState<'street' | 'satellite'>('street');
  const [viewTab, setViewTab] = useState<'map' | 'streetview'>('map');
  const [searchText, setSearchText] = useState('');
  const [incidentTypeFilter, setIncidentTypeFilter] = useState('');

  const [filters, setFilters] = useState<Filters>({
    tiers: [1, 2, 3, 4],
    states: [],
    categories: [],
    non_immigrant_only: false,
  });

  // Load data when filters change
  useEffect(() => {
    setLoading(true);
    Promise.all([fetchIncidents(filters), fetchStats(filters)]).then(([incData, statsData]) => {
      setIncidents(incData.incidents);
      setStats(statsData);
      setLoading(false);
    });
  }, [filters]);

  // Use custom view if set, otherwise default to US view
  const defaultView = STATE_CENTERS['All States'];
  const mapCenter = customView?.center || defaultView.center;
  const mapZoom = customView?.zoom || defaultView.zoom;

  const getMarkerColor = (incident: Incident) => {
    if (incident.is_death) return '#dc2626'; // red
    if (incident.is_non_immigrant) return '#f97316'; // orange
    return '#3b82f6'; // blue
  };

  const handleMarkerClick = (incident: Incident) => {
    setSelectedIncident(incident);
  };

  const zoomToIncident = (incident: Incident) => {
    if (incident.lat && incident.lon) {
      // Use jittered coords so we zoom to where the marker actually is
      const jitteredCoords = getJitteredCoords(incident.lat, incident.lon, incident.id);
      setCustomView({
        center: jitteredCoords,
        zoom: 16, // Close street-level zoom
      });
    }
  };

  const formatDate = (dateStr: string) => {
    if (!dateStr) return 'Unknown';
    return dateStr.split('T')[0];
  };

  return (
    <div className="app">
      {/* Sidebar */}
      <aside className="sidebar">
        <h2>Filters</h2>

        {/* Tier filter */}
        <div className="filter-group">
          <label>Confidence Tier</label>
          <div className="checkbox-group">
            {[1, 2, 3, 4].map((tier) => (
              <label key={tier} className="checkbox-label">
                <input
                  type="checkbox"
                  checked={filters.tiers.includes(tier)}
                  onChange={(e) => {
                    if (e.target.checked) {
                      setFilters({ ...filters, tiers: [...filters.tiers, tier] });
                    } else {
                      setFilters({ ...filters, tiers: filters.tiers.filter((t) => t !== tier) });
                    }
                  }}
                />
                Tier {tier}
              </label>
            ))}
          </div>
        </div>

        {/* Non-immigrant filter */}
        <div className="filter-group">
          <label className="checkbox-label">
            <input
              type="checkbox"
              checked={filters.non_immigrant_only}
              onChange={(e) => setFilters({ ...filters, non_immigrant_only: e.target.checked })}
            />
            Non-immigrant only
          </label>
        </div>

        {/* State filter */}
        {(() => {
          // Get states from current incidents (respects tier/other filters)
          const availableStates = [...new Set(incidents.map(i => i.state).filter(Boolean))].sort();
          return (
            <div className="filter-group">
              <label>State ({availableStates.length})</label>
              <select
                value={filters.states[0] || ''}
                onChange={(e) => {
                  const state = e.target.value;
                  setFilters({ ...filters, states: state ? [state] : [] });
                  // Zoom to state if we have coordinates for it
                  if (state && STATE_CENTERS[state]) {
                    setCustomView(STATE_CENTERS[state]);
                  } else if (state) {
                    // Zoom to state center based on incidents
                    const stateIncidents = incidents.filter(i => i.state === state && i.lat && i.lon);
                    if (stateIncidents.length > 0) {
                      const avgLat = stateIncidents.reduce((sum, i) => sum + i.lat!, 0) / stateIncidents.length;
                      const avgLon = stateIncidents.reduce((sum, i) => sum + i.lon!, 0) / stateIncidents.length;
                      setCustomView({ center: [avgLat, avgLon], zoom: 7 });
                    }
                  } else {
                    setCustomView(null); // Reset to default view
                  }
                }}
                className="state-select"
              >
                <option value="">All States</option>
                {availableStates.map((state) => (
                  <option key={state} value={state}>
                    {state}
                  </option>
                ))}
              </select>
            </div>
          );
        })()}

        {/* City breakdown for selected state */}
        {filters.states.length === 1 && (
          <div className="filter-group">
            <label>Cities in {filters.states[0]}</label>
            <div className="city-list">
              {(() => {
                const cities = incidents
                  .filter(i => i.state === filters.states[0] && i.city)
                  .reduce((acc, i) => {
                    const city = i.city!;
                    if (!acc[city]) acc[city] = { count: 0, deaths: 0, lat: i.lat, lon: i.lon };
                    acc[city].count++;
                    if (i.is_death) acc[city].deaths++;
                    if (!acc[city].lat && i.lat) { acc[city].lat = i.lat; acc[city].lon = i.lon; }
                    return acc;
                  }, {} as Record<string, { count: number; deaths: number; lat?: number; lon?: number }>);

                return Object.entries(cities)
                  .sort((a, b) => b[1].count - a[1].count)
                  .map(([city, data]) => (
                    <div
                      key={city}
                      className={`city-item ${data.deaths > 0 ? 'has-deaths' : ''}`}
                      onClick={() => {
                        if (data.lat && data.lon) {
                          setCustomView({ center: [data.lat, data.lon], zoom: 12 });
                        }
                      }}
                    >
                      <span className="city-name">{city}</span>
                      <span className="city-count">
                        {data.count}{data.deaths > 0 && <span className="death-count"> ({data.deaths} deaths)</span>}
                      </span>
                    </div>
                  ));
              })()}
            </div>
          </div>
        )}

        <hr />

        {/* Incident List */}
        {(() => {
          // Get unique incident types
          const incidentTypes = [...new Set(incidents.map(i => i.incident_type).filter(Boolean))].sort();

          // Filter incidents by search and type
          const filteredIncidents = incidents.filter(incident => {
            const matchesSearch = !searchText ||
              (incident.city?.toLowerCase().includes(searchText.toLowerCase())) ||
              (incident.victim_name?.toLowerCase().includes(searchText.toLowerCase())) ||
              (incident.state?.toLowerCase().includes(searchText.toLowerCase())) ||
              (incident.incident_type?.toLowerCase().includes(searchText.toLowerCase()));
            const matchesType = !incidentTypeFilter || incident.incident_type === incidentTypeFilter;
            return matchesSearch && matchesType;
          });

          return (
            <>
              <h2>Incidents ({filteredIncidents.length})</h2>

              {/* Search and Filter */}
              <div className="incident-filters">
                <input
                  type="text"
                  placeholder="Search by name, city, state..."
                  value={searchText}
                  onChange={(e) => setSearchText(e.target.value)}
                  className="search-input"
                />
                <select
                  value={incidentTypeFilter}
                  onChange={(e) => setIncidentTypeFilter(e.target.value)}
                  className="type-filter"
                >
                  <option value="">All Types</option>
                  {incidentTypes.map(type => (
                    <option key={type} value={type}>{type}</option>
                  ))}
                </select>
              </div>

              <div className="incident-list">
                {filteredIncidents.map((incident) => (
                  <div
                    key={incident.id}
                    className={`incident-list-item ${selectedIncident?.id === incident.id ? 'selected' : ''} ${incident.is_death ? 'death' : ''}`}
                    onClick={() => {
                      setSelectedIncident(incident);
                      if (incident.lat && incident.lon) {
                        zoomToIncident(incident);
                      }
                    }}
                  >
                    <div className="incident-list-location">
                      {incident.city}, {incident.state}
                    </div>
                    {incident.victim_name && (
                      <div className="incident-list-name">{incident.victim_name}</div>
                    )}
                    <div className="incident-list-meta">
                      {formatDate(incident.date)} · {incident.incident_type}
                    </div>
                  </div>
                ))}
              </div>
            </>
          );
        })()}

        <hr />

        {/* Incident Detail Panel */}
        <h2>Incident Details</h2>
        {selectedIncident ? (
          <div className="incident-detail">
            <h3>
              {selectedIncident.city}, {selectedIncident.state}
            </h3>
            {selectedIncident.victim_name && <p className="victim-name">{selectedIncident.victim_name}</p>}

            <div className="detail-row">
              <span className="label">Date:</span>
              <span>{formatDate(selectedIncident.date)}</span>
            </div>
            <div className="detail-row">
              <span className="label">Type:</span>
              <span>{selectedIncident.incident_type}</span>
            </div>
            <div className="detail-row">
              <span className="label">Category:</span>
              <span>{selectedIncident.victim_category || 'Unknown'}</span>
            </div>
            <div className="detail-row">
              <span className="label">Outcome:</span>
              <span>{selectedIncident.outcome_category || 'Unknown'}</span>
            </div>
            <div className="detail-row">
              <span className="label">Tier:</span>
              <span>{selectedIncident.tier}</span>
            </div>
            <div className="detail-row">
              <span className="label">ID:</span>
              <span>{selectedIncident.id}</span>
            </div>

            {selectedIncident.notes && (
              <div className="detail-section">
                <strong>Notes:</strong>
                <p>{selectedIncident.notes}</p>
              </div>
            )}

            {selectedIncident.source_url && (
              <div className="detail-section">
                <strong>Source:</strong>
                <a href={selectedIncident.source_url} target="_blank" rel="noopener noreferrer">
                  {selectedIncident.source_name || 'View Source'}
                </a>
              </div>
            )}

            {selectedIncident.linked_ids && selectedIncident.linked_ids.length > 0 && (
              <div className="detail-section deduped">
                <small>Deduplicated from: {selectedIncident.linked_ids.join(', ')}</small>
              </div>
            )}

            <div className="button-group">
              {selectedIncident.lat && selectedIncident.lon && (
                <>
                  <button className="zoom-btn" onClick={() => zoomToIncident(selectedIncident)}>
                    Zoom to Location
                  </button>
                  <button className="street-view-btn" onClick={() => setViewTab('streetview')}>
                    View Street View
                  </button>
                </>
              )}
              <button className="clear-btn" onClick={() => setSelectedIncident(null)}>
                Clear Selection
              </button>
            </div>
          </div>
        ) : (
          <p className="hint">Click a marker on the map to view details</p>
        )}
      </aside>

      {/* Main Content */}
      <main className="main-content">
        <h1>ICE Enforcement Incidents Dashboard</h1>
        <p className="subtitle">Interactive analysis of violent confrontations during immigration enforcement (Jan 2025 - Jan 2026)</p>

        {/* Stats */}
        {stats && (
          <div className="stats-grid">
            <div className="stat-card">
              <div className="stat-value">{stats.total_incidents}</div>
              <div className="stat-label">Total Incidents</div>
            </div>
            <div className="stat-card">
              <div className="stat-value">{stats.total_deaths}</div>
              <div className="stat-label">Deaths</div>
            </div>
            <div className="stat-card">
              <div className="stat-value">{stats.states_affected}</div>
              <div className="stat-label">States Affected</div>
            </div>
            <div className="stat-card">
              <div className="stat-value">{stats.non_immigrant_incidents}</div>
              <div className="stat-label">Non-Immigrant</div>
            </div>
          </div>
        )}

        {/* View Tabs */}
        <div className="view-tabs">
          <button
            className={`view-tab ${viewTab === 'map' ? 'active' : ''}`}
            onClick={() => setViewTab('map')}
          >
            Map
          </button>
          <button
            className={`view-tab ${viewTab === 'streetview' ? 'active' : ''}`}
            onClick={() => setViewTab('streetview')}
            disabled={!selectedIncident?.lat || !selectedIncident?.lon}
          >
            Street View {!selectedIncident?.lat && '(select incident)'}
          </button>

          {/* Map style toggle - only show on map tab */}
          {viewTab === 'map' && (
            <div className="map-controls-inline">
              {customView && (
                <button className="reset-view-btn" onClick={() => setCustomView(null)}>
                  Reset View
                </button>
              )}
              <button
                className={`map-style-btn ${mapStyle === 'satellite' ? 'active' : ''}`}
                onClick={() => setMapStyle(mapStyle === 'street' ? 'satellite' : 'street')}
              >
                {mapStyle === 'street' ? 'Satellite' : 'Street Map'}
              </button>
            </div>
          )}
        </div>

        {/* Map View */}
        {viewTab === 'map' && (
          <div className="map-container">
            {loading && <div className="loading-overlay">Loading...</div>}
            <MapContainer center={mapCenter} zoom={mapZoom} maxZoom={20} style={{ height: '100%', width: '100%' }}>
              <ChangeView center={mapCenter} zoom={mapZoom} />
              {mapStyle === 'street' ? (
                <TileLayer
                  attribution='&copy; <a href="https://carto.com/">CARTO</a>'
                  url="https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png"
                  maxZoom={20}
                />
              ) : (
                <TileLayer
                  attribution='&copy; Google'
                  url="https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}"
                  maxZoom={20}
                />
              )}
              {incidents
                .filter((inc) => inc.lat && inc.lon)
                .map((incident) => (
                  <CircleMarker
                    key={incident.id}
                    center={getJitteredCoords(incident.lat!, incident.lon!, incident.id)}
                    radius={8}
                    pathOptions={{
                      color: getMarkerColor(incident),
                      fillColor: getMarkerColor(incident),
                      fillOpacity: 0.7,
                    }}
                    eventHandlers={{
                      click: () => handleMarkerClick(incident),
                    }}
                  >
                    <Tooltip>
                      <strong>{incident.city}, {incident.state}</strong>
                      {incident.victim_name && (
                        <>
                          <br />
                          <em>{incident.victim_name}</em>
                        </>
                      )}
                      <br />
                      {incident.incident_type}
                      <br />
                      {formatDate(incident.date)}
                    </Tooltip>
                  </CircleMarker>
                ))}
            </MapContainer>
          </div>
        )}

        {/* Street View */}
        {viewTab === 'streetview' && selectedIncident?.lat && selectedIncident?.lon && (
          <div className="street-view-container">
            <div className="street-view-info">
              <span>{selectedIncident.city}, {selectedIncident.state}</span>
              <a
                href={`https://www.google.com/maps/@?api=1&map_action=pano&viewpoint=${selectedIncident.lat},${selectedIncident.lon}`}
                target="_blank"
                rel="noopener noreferrer"
              >
                Open in Google Maps
              </a>
            </div>
            <iframe
              className="street-view-iframe"
              src={`https://maps.google.com/maps?q=&layer=c&cbll=${selectedIncident.lat},${selectedIncident.lon}&cbp=11,0,0,0,0&output=svembed`}
              allowFullScreen
              loading="lazy"
            />
          </div>
        )}

        {/* Legend */}
        <div className="legend">
          <span className="legend-item">
            <span className="legend-dot death"></span> Death
          </span>
          <span className="legend-item">
            <span className="legend-dot non-immigrant"></span> Non-immigrant
          </span>
          <span className="legend-item">
            <span className="legend-dot other"></span> Other
          </span>
        </div>
      </main>
    </div>
  );
}

export default App;
