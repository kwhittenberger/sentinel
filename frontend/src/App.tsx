import { useState, useEffect, useRef, useCallback } from 'react';
import { MapContainer, TileLayer, CircleMarker, Tooltip, useMap } from 'react-leaflet';
import MarkerClusterGroup from 'react-leaflet-cluster';
import 'leaflet/dist/leaflet.css';
import type { Incident, Stats, Filters } from './types';
import { fetchIncidents, fetchStats } from './api';
import { Charts } from './Charts';
import { HeatmapLayer } from './HeatmapLayer';
import { AdminPanel } from './AdminPanel';
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
  const [showHeatmap, setShowHeatmap] = useState(false);
  const [darkMode, setDarkMode] = useState(() => {
    const stored = localStorage.getItem('darkMode');
    return stored ? stored === 'true' : window.matchMedia('(prefers-color-scheme: dark)').matches;
  });

  // Apply dark mode class to document
  useEffect(() => {
    document.documentElement.classList.toggle('dark', darkMode);
    localStorage.setItem('darkMode', String(darkMode));
  }, [darkMode]);
  const [viewTab, setViewTab] = useState<'map' | 'streetview' | 'charts' | 'admin'>('map');
  const [searchText, setSearchText] = useState('');
  const [incidentTypeFilter, setIncidentTypeFilter] = useState('');
  const [sortBy, setSortBy] = useState<'date-desc' | 'date-asc' | 'state' | 'type' | 'deaths-first'>('date-desc');
  const [timelineEnabled, setTimelineEnabled] = useState(false);
  const [timelineDate, setTimelineDate] = useState<string | null>(null);
  const [isPlaying, setIsPlaying] = useState(false);
  const playIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Initialize filters from URL params
  const [filters, setFilters] = useState<Filters>(() => {
    const params = new URLSearchParams(window.location.search);
    // Default to one year ago if no date_start specified
    const oneYearAgo = new Date();
    oneYearAgo.setFullYear(oneYearAgo.getFullYear() - 1);
    const defaultDateStart = oneYearAgo.toISOString().split('T')[0];
    // Default end date to today
    const today = new Date().toISOString().split('T')[0];

    return {
      tiers: params.get('tiers') ? params.get('tiers')!.split(',').map(Number) : [1, 2, 3, 4],
      states: params.get('states') ? params.get('states')!.split(',') : [],
      categories: params.get('categories') ? params.get('categories')!.split(',') : [],
      non_immigrant_only: params.get('non_immigrant_only') === 'true',
      death_only: params.get('death_only') === 'true',
      date_start: params.get('date_start') || defaultDateStart,
      date_end: params.get('date_end') || today,
    };
  });

  // Sync filters to URL
  useEffect(() => {
    const params = new URLSearchParams();
    if (filters.tiers.length > 0 && filters.tiers.length < 4) {
      params.set('tiers', filters.tiers.join(','));
    }
    if (filters.states.length > 0) {
      params.set('states', filters.states.join(','));
    }
    if (filters.categories.length > 0) {
      params.set('categories', filters.categories.join(','));
    }
    if (filters.non_immigrant_only) {
      params.set('non_immigrant_only', 'true');
    }
    if (filters.death_only) {
      params.set('death_only', 'true');
    }
    if (filters.date_start) {
      params.set('date_start', filters.date_start);
    }
    if (filters.date_end) {
      params.set('date_end', filters.date_end);
    }
    const newUrl = params.toString() ? `${window.location.pathname}?${params}` : window.location.pathname;
    window.history.replaceState({}, '', newUrl);
  }, [filters]);

  // Load data when filters change
  useEffect(() => {
    setLoading(true);
    Promise.all([fetchIncidents(filters), fetchStats(filters)]).then(([incData, statsData]) => {
      setIncidents(incData.incidents);
      setStats(statsData);
      setLoading(false);
    });
  }, [filters]);

  // Keyboard navigation
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      // Ignore if typing in an input
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLSelectElement) {
        return;
      }

      const incidentsWithCoords = incidents.filter(i => i.lat && i.lon);
      const currentIndex = selectedIncident
        ? incidentsWithCoords.findIndex(i => i.id === selectedIncident.id)
        : -1;

      switch (e.key) {
        case 'ArrowDown':
        case 'j':
          e.preventDefault();
          if (incidentsWithCoords.length > 0) {
            const nextIndex = currentIndex < incidentsWithCoords.length - 1 ? currentIndex + 1 : 0;
            const nextIncident = incidentsWithCoords[nextIndex];
            setSelectedIncident(nextIncident);
            zoomToIncident(nextIncident);
          }
          break;
        case 'ArrowUp':
        case 'k':
          e.preventDefault();
          if (incidentsWithCoords.length > 0) {
            const prevIndex = currentIndex > 0 ? currentIndex - 1 : incidentsWithCoords.length - 1;
            const prevIncident = incidentsWithCoords[prevIndex];
            setSelectedIncident(prevIncident);
            zoomToIncident(prevIncident);
          }
          break;
        case 'Escape':
          setSelectedIncident(null);
          setCustomView(null);
          break;
        case 'h':
          if (!e.ctrlKey && !e.metaKey) {
            setShowHeatmap(prev => !prev);
          }
          break;
        case 'd':
          if (!e.ctrlKey && !e.metaKey) {
            setDarkMode(prev => !prev);
          }
          break;
        case 'm':
          setViewTab('map');
          break;
        case 'c':
          if (!e.ctrlKey && !e.metaKey) {
            setViewTab('charts');
          }
          break;
        case 's':
          if (!e.ctrlKey && !e.metaKey && selectedIncident?.lat && selectedIncident?.lon) {
            setViewTab('streetview');
          }
          break;
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [incidents, selectedIncident]);

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
    // Scroll to incident in list
    setTimeout(() => {
      const element = document.getElementById(`incident-${incident.id}`);
      if (element) {
        element.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
      }
    }, 100);
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

  // Timeline animation
  const sortedDates = [...new Set(incidents.map(i => i.date?.split('T')[0]).filter(Boolean))].sort() as string[];

  const getTimelineIncidents = useCallback(() => {
    if (!timelineEnabled || !timelineDate) return incidents;
    return incidents.filter(i => i.date && i.date.split('T')[0] <= timelineDate);
  }, [incidents, timelineEnabled, timelineDate]);

  const handleTimelineToggle = () => {
    if (!timelineEnabled) {
      setTimelineEnabled(true);
      setTimelineDate(sortedDates[0] || null);
    } else {
      setTimelineEnabled(false);
      setTimelineDate(null);
      setIsPlaying(false);
      if (playIntervalRef.current) {
        clearInterval(playIntervalRef.current);
        playIntervalRef.current = null;
      }
    }
  };

  const handlePlayPause = () => {
    if (isPlaying) {
      setIsPlaying(false);
      if (playIntervalRef.current) {
        clearInterval(playIntervalRef.current);
        playIntervalRef.current = null;
      }
    } else {
      setIsPlaying(true);
      playIntervalRef.current = setInterval(() => {
        setTimelineDate(current => {
          const currentIdx = sortedDates.indexOf(current || '');
          if (currentIdx >= sortedDates.length - 1) {
            setIsPlaying(false);
            if (playIntervalRef.current) clearInterval(playIntervalRef.current);
            return current;
          }
          return sortedDates[currentIdx + 1];
        });
      }, 500);
    }
  };

  // Cleanup interval on unmount
  useEffect(() => {
    return () => {
      if (playIntervalRef.current) {
        clearInterval(playIntervalRef.current);
      }
    };
  }, []);

  const displayedIncidents = timelineEnabled ? getTimelineIncidents() : incidents;

  // Handle heatmap click - find and select nearest incident
  const handleHeatmapClick = useCallback((lat: number, lon: number) => {
    // Find incidents within ~50km radius
    const maxDistanceKm = 50;
    const incidentsWithCoords = displayedIncidents.filter(inc => inc.lat && inc.lon);

    if (incidentsWithCoords.length === 0) return;

    // Calculate distance using Haversine formula
    const getDistanceKm = (lat1: number, lon1: number, lat2: number, lon2: number) => {
      const R = 6371; // Earth's radius in km
      const dLat = (lat2 - lat1) * Math.PI / 180;
      const dLon = (lon2 - lon1) * Math.PI / 180;
      const a = Math.sin(dLat / 2) * Math.sin(dLat / 2) +
                Math.cos(lat1 * Math.PI / 180) * Math.cos(lat2 * Math.PI / 180) *
                Math.sin(dLon / 2) * Math.sin(dLon / 2);
      const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
      return R * c;
    };

    // Find the closest incident
    let nearestIncident: Incident | null = null;
    let nearestDistance = Infinity;

    for (const inc of incidentsWithCoords) {
      const distance = getDistanceKm(lat, lon, inc.lat!, inc.lon!);
      if (distance < nearestDistance && distance <= maxDistanceKm) {
        nearestDistance = distance;
        nearestIncident = inc;
      }
    }

    if (nearestIncident) {
      handleMarkerClick(nearestIncident);
      // Zoom to the incident
      setCustomView({
        center: [nearestIncident.lat!, nearestIncident.lon!],
        zoom: 12,
      });
    }
  }, [displayedIncidents]);

  const copyShareLink = () => {
    navigator.clipboard.writeText(window.location.href).then(() => {
      alert('Link copied to clipboard!');
    });
  };

  const exportToCSV = (incidentsToExport: Incident[]) => {
    const headers = ['ID', 'Date', 'State', 'City', 'Type', 'Victim Name', 'Category', 'Outcome', 'Tier', 'Death', 'Non-Immigrant', 'Notes', 'Source URL'];
    const rows = incidentsToExport.map(i => [
      i.id,
      i.date || '',
      i.state || '',
      i.city || '',
      i.incident_type || '',
      i.victim_name || '',
      i.victim_category || '',
      i.outcome_category || '',
      i.tier,
      i.is_death ? 'Yes' : 'No',
      i.is_non_immigrant ? 'Yes' : 'No',
      (i.notes || '').replace(/"/g, '""'),
      i.source_url || ''
    ]);

    const csvContent = [
      headers.join(','),
      ...rows.map(row => row.map(cell => `"${cell}"`).join(','))
    ].join('\n');

    const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
    const link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    link.download = `ice_incidents_${new Date().toISOString().split('T')[0]}.csv`;
    link.click();
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

        {/* Death only filter */}
        <div className="filter-group">
          <label className="checkbox-label">
            <input
              type="checkbox"
              checked={filters.death_only || false}
              onChange={(e) => setFilters({ ...filters, death_only: e.target.checked })}
            />
            Deaths only
          </label>
        </div>

        {/* Date range filter */}
        <div className="filter-group">
          <label>Date Range</label>
          <div className="date-range">
            <input
              type="date"
              value={filters.date_start || ''}
              onChange={(e) => setFilters({ ...filters, date_start: e.target.value || undefined })}
              className="date-input"
            />
            <span className="date-separator">to</span>
            <input
              type="date"
              value={filters.date_end || ''}
              onChange={(e) => setFilters({ ...filters, date_end: e.target.value || undefined })}
              className="date-input"
            />
          </div>
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
                  onClick={() => exportToCSV(filteredIncidents)}
                  title="Export filtered incidents to CSV"
                >
                  Export CSV
                </button>
                <button
                  className="share-btn"
                  onClick={copyShareLink}
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
                    {incidentTypes.map(type => (
                      <option key={type} value={type}>{type}</option>
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
              <div className="detail-section linked-section">
                <strong>Related Reports ({selectedIncident.linked_ids.length})</strong>
                <p className="linked-info">This incident may appear in multiple sources:</p>
                <div className="linked-ids">
                  {selectedIncident.linked_ids.map(linkedId => {
                    const linkedIncident = incidents.find(i => i.id === linkedId);
                    return (
                      <div key={linkedId} className="linked-item">
                        <span className="linked-id">{linkedId}</span>
                        {linkedIncident && (
                          <span className="linked-source">
                            {linkedIncident.source_name || `Tier ${linkedIncident.tier}`}
                          </span>
                        )}
                      </div>
                    );
                  })}
                </div>
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
        <div className="header-row">
          <h1>ICE Enforcement Incidents Dashboard</h1>
          <button
            className="dark-mode-btn"
            onClick={() => setDarkMode(!darkMode)}
            title={darkMode ? 'Switch to light mode' : 'Switch to dark mode'}
          >
            {darkMode ? 'Light' : 'Dark'}
          </button>
        </div>
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
            className={`view-tab ${viewTab === 'charts' ? 'active' : ''}`}
            onClick={() => setViewTab('charts')}
          >
            Charts
          </button>
          <button
            className={`view-tab ${viewTab === 'streetview' ? 'active' : ''}`}
            onClick={() => setViewTab('streetview')}
            disabled={!selectedIncident?.lat || !selectedIncident?.lon}
          >
            Street View {!selectedIncident?.lat && '(select incident)'}
          </button>
          <button
            className={`view-tab ${viewTab === 'admin' ? 'active' : ''}`}
            onClick={() => setViewTab('admin')}
          >
            Admin
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
                className={`map-style-btn ${timelineEnabled ? 'active' : ''}`}
                onClick={handleTimelineToggle}
              >
                Timeline
              </button>
              <button
                className={`map-style-btn ${showHeatmap ? 'active' : ''}`}
                onClick={() => setShowHeatmap(!showHeatmap)}
              >
                {showHeatmap ? 'Markers' : 'Heatmap'}
              </button>
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
        {/* Timeline Controls */}
        {viewTab === 'map' && timelineEnabled && (
          <div className="timeline-controls">
            <button className="timeline-btn" onClick={handlePlayPause}>
              {isPlaying ? 'Pause' : 'Play'}
            </button>
            <input
              type="range"
              className="timeline-slider"
              min={0}
              max={sortedDates.length - 1}
              value={sortedDates.indexOf(timelineDate || '')}
              onChange={(e) => {
                setIsPlaying(false);
                if (playIntervalRef.current) clearInterval(playIntervalRef.current);
                setTimelineDate(sortedDates[parseInt(e.target.value)]);
              }}
            />
            <span className="timeline-date">{timelineDate || 'N/A'}</span>
            <span className="timeline-count">
              {displayedIncidents.length} / {incidents.length} incidents
            </span>
          </div>
        )}

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
              {showHeatmap ? (
                <HeatmapLayer
                  points={displayedIncidents
                    .filter((inc) => inc.lat && inc.lon)
                    .map((inc) => [inc.lat!, inc.lon!, inc.is_death ? 1.0 : 0.5] as [number, number, number])}
                  onMapClick={handleHeatmapClick}
                />
              ) : (
                <MarkerClusterGroup
                  chunkedLoading
                  maxClusterRadius={40}
                  spiderfyOnMaxZoom={true}
                  showCoverageOnHover={false}
                >
                  {displayedIncidents
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
                </MarkerClusterGroup>
              )}
            </MapContainer>
          </div>
        )}

        {/* Charts View */}
        {viewTab === 'charts' && (
          <Charts stats={stats} incidents={incidents} />
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

        {/* Admin Panel */}
        {viewTab === 'admin' && <AdminPanel />}

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
          <span className="keyboard-hint" title="j/k or arrows: navigate | h: heatmap | d: dark mode | m/c/s: views | Esc: clear">
            Keyboard: j/k h d m c s Esc
          </span>
        </div>
      </main>
    </div>
  );
}

export default App;
