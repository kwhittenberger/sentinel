import { useState, useCallback } from 'react';
import 'leaflet/dist/leaflet.css';
import type { Incident } from './types';
import { fetchIncidents, fetchStats, fetchQueueStats } from './api';
import { Charts } from './Charts';
import { AdminPanel } from './AdminPanel';
import { useIncidentData } from './hooks/useIncidentData';
import { useIncidentSelection } from './hooks/useIncidentSelection';
import { useTimelinePlayback } from './hooks/useTimelinePlayback';
import { useKeyboardNavigation } from './hooks/useKeyboardNavigation';
import { STATE_CENTERS, formatDate, copyShareLink, exportToCSV } from './dashboardUtils';
import { getJitteredCoords } from './components/IncidentMap';
import { MapLegend } from './components/MapLegend';
import { StatsBar } from './components/StatsBar';
import { StreetViewPanel } from './components/StreetViewPanel';
import { EventBanner } from './components/EventBanner';
import { TimelineControls } from './components/TimelineControls';
import { IncidentMap } from './components/IncidentMap';
import { IncidentListSidebar } from './components/IncidentListSidebar';
import { IncidentDetailDrawer } from './components/IncidentDetailDrawer';
import './App.css';

function App() {
  // Data layer
  const {
    incidents, setIncidents, stats, setStats, loading, filters, setFilters,
    queueStats, setQueueStats, domainsSummary, eventList, activeEvent,
    darkMode, setDarkMode, getTypeDisplayName, getStateDisplayName,
  } = useIncidentData();

  // Selection layer
  const {
    selectedIncident, setSelectedIncident, drawerOpen, setDrawerOpen,
    fullIncident, articleContent, extractionData, sourceUrl,
    connections, connectionsLoading,
  } = useIncidentSelection();

  // View state
  const [customView, setCustomView] = useState<{ center: [number, number]; zoom: number } | null>(null);
  const [viewTab, setViewTab] = useState<'map' | 'streetview' | 'charts'>('map');
  const [adminPanel, setAdminPanel] = useState<'none' | 'admin'>('none');
  const [mapStyle, setMapStyle] = useState<'street' | 'satellite'>('street');
  const [showHeatmap, setShowHeatmap] = useState(false);
  const [statsCollapsed, setStatsCollapsed] = useState(
    () => localStorage.getItem('sentinel-stats-collapsed') !== 'false'
  );

  // Timeline layer
  const {
    timelineEnabled, timelineDate, isPlaying, sortedDates,
    getTimelineIncidents, handleTimelineToggle, handlePlayPause,
    setTimelineDate, setIsPlaying, playIntervalRef,
  } = useTimelinePlayback(incidents);

  const displayedIncidents = timelineEnabled ? getTimelineIncidents() : incidents;

  // Map view
  const defaultView = STATE_CENTERS['All States'];
  const mapCenter = customView?.center || defaultView.center;
  const mapZoom = customView?.zoom || defaultView.zoom;

  // Handlers
  const zoomToIncident = useCallback((incident: Incident) => {
    if (incident.lat && incident.lon) {
      const jitteredCoords = getJitteredCoords(incident.lat, incident.lon, incident.id);
      setCustomView({ center: jitteredCoords, zoom: 16 });
    }
  }, []);

  const handleMarkerClick = useCallback((incident: Incident) => {
    setSelectedIncident(incident);
    setTimeout(() => {
      const element = document.getElementById(`incident-${incident.id}`);
      if (element) {
        element.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
      }
    }, 100);
  }, [setSelectedIncident]);

  const handleHeatmapClick = useCallback((lat: number, lon: number) => {
    const maxDistanceKm = 50;
    const incidentsWithCoords = displayedIncidents.filter(inc => inc.lat && inc.lon);
    if (incidentsWithCoords.length === 0) return;

    const getDistanceKm = (lat1: number, lon1: number, lat2: number, lon2: number) => {
      const R = 6371;
      const dLat = (lat2 - lat1) * Math.PI / 180;
      const dLon = (lon2 - lon1) * Math.PI / 180;
      const a = Math.sin(dLat / 2) * Math.sin(dLat / 2) +
                Math.cos(lat1 * Math.PI / 180) * Math.cos(lat2 * Math.PI / 180) *
                Math.sin(dLon / 2) * Math.sin(dLon / 2);
      return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
    };

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
      setCustomView({ center: [nearestIncident.lat!, nearestIncident.lon!], zoom: 12 });
    }
  }, [displayedIncidents, handleMarkerClick]);

  const handleSelectIncident = useCallback((incident: Incident) => {
    setSelectedIncident(incident);
    if (incident.lat && incident.lon) {
      zoomToIncident(incident);
    }
  }, [setSelectedIncident, zoomToIncident]);

  const toggleStats = () => {
    setStatsCollapsed(prev => {
      localStorage.setItem('sentinel-stats-collapsed', String(!prev));
      return !prev;
    });
  };

  const handleExportCSV = useCallback((incidentsToExport: Incident[]) => {
    exportToCSV(incidentsToExport, getStateDisplayName, getTypeDisplayName);
  }, [getStateDisplayName, getTypeDisplayName]);

  // Keyboard navigation
  useKeyboardNavigation({
    incidents, selectedIncident, setSelectedIncident, setCustomView,
    setShowHeatmap, setDarkMode, setViewTab, zoomToIncident,
  });

  return (
    <div className="app">
      {adminPanel === 'admin' ? (
        <AdminPanel
          onClose={() => setAdminPanel('none')}
          onRefresh={() => {
            fetchIncidents(filters).then(data => setIncidents(data.incidents));
            fetchStats(filters).then(setStats);
            fetchQueueStats().then(setQueueStats);
          }}
        />
      ) : (
      <>
      {/* Sidebar */}
      <aside className="sidebar">
        <div className="sidebar-admin-bar">
          <button
            className={`sidebar-admin-btn ${adminPanel !== 'none' ? 'active' : ''}`}
            onClick={() => setAdminPanel(adminPanel === 'none' ? 'admin' : 'none')}
          >
            Admin Panel
            {queueStats && queueStats.pending > 0 && (
              <span className="admin-badge">{queueStats.pending}</span>
            )}
          </button>
        </div>

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

        {/* Domain filter */}
        <div className="filter-group">
          <label>Domain</label>
          <select
            value={filters.domain || ''}
            onChange={(e) => setFilters({
              ...filters,
              domain: e.target.value || undefined,
              category: undefined,
            })}
            className="state-select"
          >
            <option value="">All Domains</option>
            {domainsSummary.map(d => (
              <option key={d.slug} value={d.slug}>{d.name}</option>
            ))}
          </select>
        </div>

        {/* Category filter */}
        {(() => {
          const selectedDomain = domainsSummary.find(d => d.slug === filters.domain);
          const categories = selectedDomain?.categories || [];
          if (categories.length === 0 && !filters.domain) {
            const allCategories = domainsSummary.flatMap(d => d.categories);
            if (allCategories.length > 0) {
              return (
                <div className="filter-group">
                  <label>Category</label>
                  <select
                    value={filters.category || ''}
                    onChange={(e) => setFilters({ ...filters, category: e.target.value || undefined })}
                    className="state-select"
                  >
                    <option value="">All Categories</option>
                    {allCategories.map(c => (
                      <option key={c.slug} value={c.slug}>{c.name}</option>
                    ))}
                  </select>
                </div>
              );
            }
            return null;
          }
          return categories.length > 0 ? (
            <div className="filter-group">
              <label>Category</label>
              <select
                value={filters.category || ''}
                onChange={(e) => setFilters({ ...filters, category: e.target.value || undefined })}
                className="state-select"
              >
                <option value="">All Categories</option>
                {categories.map(c => (
                  <option key={c.slug} value={c.slug}>{c.name}</option>
                ))}
              </select>
            </div>
          ) : null;
        })()}

        {/* Severity filter */}
        <div className="filter-group">
          <label>Severity</label>
          <select
            value={filters.severity || ''}
            onChange={(e) => setFilters({ ...filters, severity: e.target.value || undefined })}
            className="state-select"
          >
            <option value="">All Severities</option>
            <option value="death">Death</option>
            <option value="serious_injury">Serious Injury</option>
            <option value="minor_injury">Minor Injury</option>
            <option value="no_injury">No Injury</option>
          </select>
        </div>

        {/* Event filter */}
        {eventList.length > 0 && (
          <div className="filter-group">
            <label>Event</label>
            <select
              value={filters.event_id || ''}
              onChange={(e) => setFilters({ ...filters, event_id: e.target.value || undefined })}
              className="state-select"
            >
              <option value="">All Events</option>
              {eventList.map(ev => (
                <option key={ev.id} value={ev.id}>
                  {ev.name} ({ev.incident_count})
                </option>
              ))}
            </select>
          </div>
        )}

        {/* Category breakdown */}
        {stats && (
          <div className="filter-group">
            <label>Breakdown</label>
            <div className="category-breakdown">
              {Object.entries(stats.by_category || {}).map(([cat, count]) => {
                const total = stats.total_incidents || 1;
                const pct = Math.round((count / total) * 100);
                const color = cat === 'enforcement' ? '#f97316' : cat === 'crime' ? '#3b82f6' : '#6b7280';
                return (
                  <div key={cat} className="category-breakdown-row">
                    <span className="category-breakdown-label">{cat}</span>
                    <div className="category-breakdown-bar">
                      <div className="category-breakdown-fill" style={{ width: `${pct}%`, background: color }} />
                    </div>
                    <span className="category-breakdown-count">{count}</span>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* Date range filter */}
        <div className="filter-group">
          <label>Date Range</label>
          <div className="date-range">
            <div className="date-range-row">
              <span className="date-range-row-label">From</span>
              <input
                type="date"
                value={filters.date_start || ''}
                onChange={(e) => setFilters({ ...filters, date_start: e.target.value || undefined })}
                className="date-input"
              />
            </div>
            <div className="date-range-row">
              <span className="date-range-row-label">To</span>
              <input
                type="date"
                value={filters.date_end || ''}
                onChange={(e) => setFilters({ ...filters, date_end: e.target.value || undefined })}
                className="date-input"
              />
            </div>
          </div>
        </div>

        {/* State filter */}
        {(() => {
          const availableStates = [...new Set(incidents.map(i => i.state).filter(Boolean))].sort();
          const stateNameMap: Record<string, string> = {};
          incidents.forEach(i => {
            if (i.state && i.state_name) stateNameMap[i.state] = i.state_name;
          });
          return (
            <div className="filter-group">
              <label>State ({availableStates.length})</label>
              <select
                value={filters.states[0] || ''}
                onChange={(e) => {
                  const state = e.target.value;
                  setFilters({ ...filters, states: state ? [state] : [] });
                  if (state && STATE_CENTERS[stateNameMap[state] || state]) {
                    setCustomView(STATE_CENTERS[stateNameMap[state] || state]);
                  } else if (state) {
                    const stateIncidents = incidents.filter(i => i.state === state && i.lat && i.lon);
                    if (stateIncidents.length > 0) {
                      const avgLat = stateIncidents.reduce((sum, i) => sum + i.lat!, 0) / stateIncidents.length;
                      const avgLon = stateIncidents.reduce((sum, i) => sum + i.lon!, 0) / stateIncidents.length;
                      setCustomView({ center: [avgLat, avgLon], zoom: 7 });
                    }
                  } else {
                    setCustomView(null);
                  }
                }}
                className="state-select"
              >
                <option value="">All States</option>
                {availableStates.map((state) => (
                  <option key={state} value={state}>{stateNameMap[state] || state}</option>
                ))}
              </select>
            </div>
          );
        })()}

        {/* City breakdown */}
        {filters.states.length === 1 && (
          <div className="filter-group">
            <label>Cities in {incidents.find(i => i.state === filters.states[0])?.state_name || filters.states[0]}</label>
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
                        if (data.lat && data.lon) setCustomView({ center: [data.lat, data.lon], zoom: 12 });
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

        <IncidentListSidebar
          incidents={incidents}
          selectedIncident={selectedIncident}
          onSelectIncident={handleSelectIncident}
          getTypeDisplayName={getTypeDisplayName}
          getStateDisplayName={getStateDisplayName}
          onExportCSV={handleExportCSV}
          onCopyShareLink={copyShareLink}
        />

        <hr />

        {/* Quick actions for selected incident */}
        {selectedIncident && (
          <>
            <h2>Selected</h2>
            <div className="incident-detail">
              <h3>{selectedIncident.city}, {getStateDisplayName(selectedIncident)}</h3>
              <div className="detail-row">
                <span className="label">Date:</span>
                <span>{formatDate(selectedIncident.date)}</span>
              </div>
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
          </>
        )}
      </aside>

      <IncidentDetailDrawer
        incident={selectedIncident}
        fullIncident={fullIncident}
        drawerOpen={drawerOpen}
        extractionData={extractionData}
        articleContent={articleContent}
        sourceUrl={sourceUrl}
        connections={connections}
        connectionsLoading={connectionsLoading}
        incidents={incidents}
        onClose={() => setSelectedIncident(null)}
        onZoom={(inc) => { setDrawerOpen(false); zoomToIncident(inc); }}
        onSelectIncident={(inc) => setSelectedIncident(inc)}
        onSetEventFilter={(eventId) => {
          setFilters(f => ({ ...f, event_id: eventId }));
          setSelectedIncident(null);
        }}
        getStateDisplayName={getStateDisplayName}
        formatDate={formatDate}
      />

      {/* Main Content */}
      <main className="main-content">
        <div className="header-row">
          <h1>Sentinel</h1>
          <button
            className="dark-mode-btn"
            onClick={() => setDarkMode(!darkMode)}
            title={darkMode ? 'Switch to light mode' : 'Switch to dark mode'}
          >
            {darkMode ? 'Light' : 'Dark'}
          </button>
        </div>
        <p className="subtitle">Incident analysis and pattern detection</p>

        {stats && (
          <StatsBar stats={stats} statsCollapsed={statsCollapsed} toggleStats={toggleStats} />
        )}

        {/* View Tabs */}
        <div className="view-tabs">
          <button
            className={`view-tab ${viewTab === 'map' && adminPanel === 'none' ? 'active' : ''}`}
            onClick={() => { setViewTab('map'); setAdminPanel('none'); }}
          >
            Map
          </button>
          <button
            className={`view-tab ${viewTab === 'charts' && adminPanel === 'none' ? 'active' : ''}`}
            onClick={() => { setViewTab('charts'); setAdminPanel('none'); }}
          >
            Charts
          </button>
          <button
            className={`view-tab ${viewTab === 'streetview' && adminPanel === 'none' ? 'active' : ''}`}
            onClick={() => { setViewTab('streetview'); setAdminPanel('none'); }}
            disabled={!selectedIncident?.lat || !selectedIncident?.lon}
          >
            Street View {!selectedIncident?.lat && '(select incident)'}
          </button>

          {viewTab === 'map' && adminPanel === 'none' && (
            <div className="map-controls-inline">
              {customView && (
                <button className="reset-view-btn" onClick={() => setCustomView(null)}>Reset View</button>
              )}
              <button className={`map-style-btn ${timelineEnabled ? 'active' : ''}`} onClick={handleTimelineToggle}>
                Timeline
              </button>
              <button className={`map-style-btn ${showHeatmap ? 'active' : ''}`} onClick={() => setShowHeatmap(!showHeatmap)}>
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

        {activeEvent && adminPanel === 'none' && (
          <EventBanner event={activeEvent} onClear={() => setFilters(f => ({ ...f, event_id: undefined }))} />
        )}

        {viewTab === 'map' && adminPanel === 'none' && timelineEnabled && (
          <TimelineControls
            isPlaying={isPlaying}
            onPlayPause={handlePlayPause}
            sortedDates={sortedDates}
            timelineDate={timelineDate}
            onDateChange={(date) => {
              setIsPlaying(false);
              if (playIntervalRef.current) clearInterval(playIntervalRef.current);
              setTimelineDate(date);
            }}
            displayedCount={displayedIncidents.length}
            totalCount={incidents.length}
          />
        )}

        {viewTab === 'map' && adminPanel === 'none' && (
          <IncidentMap
            incidents={displayedIncidents}
            selectedIncident={selectedIncident}
            mapCenter={mapCenter}
            mapZoom={mapZoom}
            mapStyle={mapStyle}
            showHeatmap={showHeatmap}
            loading={loading}
            onMarkerClick={handleMarkerClick}
            onHeatmapClick={handleHeatmapClick}
            getTypeDisplayName={getTypeDisplayName}
            getStateDisplayName={getStateDisplayName}
            formatDate={formatDate}
          />
        )}

        {viewTab === 'charts' && adminPanel === 'none' && (
          <Charts stats={stats} incidents={incidents} />
        )}

        {viewTab === 'streetview' && adminPanel === 'none' && selectedIncident?.lat && selectedIncident?.lon && (
          <StreetViewPanel incident={selectedIncident} />
        )}

        <MapLegend />
      </main>
      </>
      )}
    </div>
  );
}

export default App;
