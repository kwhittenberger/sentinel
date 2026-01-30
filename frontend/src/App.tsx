import { useState, useEffect, useRef, useCallback } from 'react';
import { MapContainer, TileLayer, CircleMarker, Tooltip, useMap } from 'react-leaflet';
import MarkerClusterGroup from 'react-leaflet-cluster';
import 'leaflet/dist/leaflet.css';
import type { Incident, Stats, Filters, IncidentType, DomainSummary, EventListItem, IncidentConnections, UniversalExtractionData, Event } from './types';
import { fetchIncidents, fetchStats, fetchQueueStats, fetchDomainsSummary, fetchEventList, fetchIncidentConnections } from './api';
import { Charts } from './Charts';
import { HeatmapLayer } from './HeatmapLayer';
import { AdminPanel } from './AdminPanel';
import { IncidentDetailView } from './IncidentDetailView';
import { ExtractionDetailView } from './ExtractionDetailView';
import './App.css';

interface QueueStats {
  pending: number;
  in_review: number;
  approved: number;
  rejected: number;
}

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
  const [viewTab, setViewTab] = useState<'map' | 'streetview' | 'charts'>('map');
  const [adminPanel, setAdminPanel] = useState<'none' | 'admin'>('none');
  const [queueStats, setQueueStats] = useState<QueueStats | null>(null);
  const [searchText, setSearchText] = useState('');
  const [incidentTypeFilter, setIncidentTypeFilter] = useState('');
  const [incidentTypes, setIncidentTypes] = useState<IncidentType[]>([]);
  const [domainsSummary, setDomainsSummary] = useState<DomainSummary[]>([]);
  const [eventList, setEventList] = useState<EventListItem[]>([]);
  const [sortBy, setSortBy] = useState<'date-desc' | 'date-asc' | 'state' | 'type' | 'deaths-first'>('date-desc');
  const [statsCollapsed, setStatsCollapsed] = useState(
    () => localStorage.getItem('sentinel-stats-collapsed') !== 'false'
  );
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [fullIncident, setFullIncident] = useState<Incident | null>(null);
  const [articleContent, setArticleContent] = useState<string | null>(null);
  const [extractionData, setExtractionData] = useState<UniversalExtractionData | null>(null);
  const [sourceUrl, setSourceUrl] = useState<string | null>(null);
  const [connections, setConnections] = useState<IncidentConnections | null>(null);
  const [connectionsLoading, setConnectionsLoading] = useState(false);
  const [activeEvent, setActiveEvent] = useState<Event | null>(null);
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
      date_start: params.get('date_start') || defaultDateStart,
      date_end: params.get('date_end') || today,
      domain: params.get('domain') || undefined,
      category: params.get('category') || undefined,
      severity: params.get('severity') || undefined,
      event_id: params.get('event_id') || undefined,
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
    if (filters.domain) {
      params.set('domain', filters.domain);
    }
    if (filters.category) {
      params.set('category', filters.category);
    }
    if (filters.severity) {
      params.set('severity', filters.severity);
    }
    if (filters.event_id) {
      params.set('event_id', filters.event_id);
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

  // Load queue stats for sidebar badge, domains, and events for filters
  useEffect(() => {
    fetchQueueStats().then(setQueueStats).catch(() => {});
    fetchDomainsSummary().then(data => setDomainsSummary(data.domains)).catch(() => {});
    fetchEventList().then(setEventList).catch(() => {});
  }, []);

  // Load event details when event filter is active
  useEffect(() => {
    if (filters.event_id) {
      fetch(`/api/events/${filters.event_id}`)
        .then(res => res.ok ? res.json() : null)
        .then(data => { if (data) setActiveEvent(data as Event); })
        .catch(() => setActiveEvent(null));
    } else {
      setActiveEvent(null);
    }
  }, [filters.event_id]);

  // Load incident types for display names
  useEffect(() => {
    fetch('/api/admin/types')
      .then(res => res.ok ? res.json() : [])
      .then(data => Array.isArray(data) ? data : [])
      .then(setIncidentTypes)
      .catch(() => setIncidentTypes([]));
  }, []);

  // Helper to get display name for incident type
  const getTypeDisplayName = useCallback((typeName: string | undefined): string => {
    if (!typeName) return '';
    const typeInfo = incidentTypes.find(t => t.name === typeName || t.slug === typeName);
    return typeInfo?.display_name || typeName.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
  }, [incidentTypes]);

  // Helper to get display state name (full name if available, otherwise abbreviation)
  const getStateDisplayName = (incident: Incident): string => {
    return incident.state_name || incident.state || 'Unknown';
  };

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

  // Stats collapse toggle
  const toggleStats = () => {
    setStatsCollapsed(prev => {
      localStorage.setItem('sentinel-stats-collapsed', String(!prev));
      return !prev;
    });
  };

  // Open drawer when incident selected, close when cleared
  useEffect(() => {
    if (selectedIncident) {
      setDrawerOpen(true);
      // Fetch full incident detail from admin API
      setFullIncident(null);
      setArticleContent(null);
      setExtractionData(null);
      setSourceUrl(null);
      fetch(`/api/admin/incidents/${selectedIncident.id}`)
        .then(res => res.ok ? res.json() : null)
        .then(data => { if (data) setFullIncident(data as Incident); })
        .catch(() => {});
      // Fetch linked articles for content + extraction data
      fetch(`/api/admin/incidents/${selectedIncident.id}/articles`)
        .then(res => res.ok ? res.json() : null)
        .then(data => {
          if (data?.articles?.length > 0) {
            const article = data.articles.find((a: Record<string, unknown>) => a.is_primary) || data.articles[0];
            if (article?.content) setArticleContent(article.content as string);
            if (article?.source_url) setSourceUrl(article.source_url as string);
            // Use extracted_data for the rich ExtractionDetailView
            if (article?.extracted_data && typeof article.extracted_data === 'object') {
              setExtractionData(article.extracted_data as UniversalExtractionData);
            }
          }
        })
        .catch(() => {});
    } else {
      setDrawerOpen(false);
      setFullIncident(null);
      setArticleContent(null);
      setExtractionData(null);
      setSourceUrl(null);
      setConnections(null);
    }
  }, [selectedIncident]);

  // Fetch connections when drawer is open with an incident
  useEffect(() => {
    if (drawerOpen && selectedIncident?.id) {
      setConnectionsLoading(true);
      fetchIncidentConnections(selectedIncident.id)
        .then(setConnections)
        .catch(() => setConnections(null))
        .finally(() => setConnectionsLoading(false));
    }
  }, [drawerOpen, selectedIncident?.id]);

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
      getStateDisplayName(i),
      i.city || '',
      getTypeDisplayName(i.incident_type),
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
    link.download = `sentinel_incidents_${new Date().toISOString().split('T')[0]}.csv`;
    link.click();
  };

  return (
    <div className="app">
      {/* Full-screen Admin Panel */}
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
        {/* Admin Quick Access */}
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
              category: undefined, // reset category when domain changes
            })}
            className="state-select"
          >
            <option value="">All Domains</option>
            {domainsSummary.map(d => (
              <option key={d.slug} value={d.slug}>{d.name}</option>
            ))}
          </select>
        </div>

        {/* Category filter (filtered by selected domain) */}
        {(() => {
          const selectedDomain = domainsSummary.find(d => d.slug === filters.domain);
          const categories = selectedDomain?.categories || [];
          if (categories.length === 0 && !filters.domain) {
            // Show all categories across domains when no domain selected
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

        {/* Category breakdown widget */}
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
          // Get states from current incidents (respects tier/other filters)
          const availableStates = [...new Set(incidents.map(i => i.state).filter(Boolean))].sort();
          // Build state code -> name lookup from incidents
          const stateNameMap: Record<string, string> = {};
          incidents.forEach(i => {
            if (i.state && i.state_name) {
              stateNameMap[i.state] = i.state_name;
            }
          });
          return (
            <div className="filter-group">
              <label>State ({availableStates.length})</label>
              <select
                value={filters.states[0] || ''}
                onChange={(e) => {
                  const state = e.target.value;
                  setFilters({ ...filters, states: state ? [state] : [] });
                  // Zoom to state if we have coordinates for it
                  if (state && STATE_CENTERS[stateNameMap[state] || state]) {
                    setCustomView(STATE_CENTERS[stateNameMap[state] || state]);
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
                    {stateNameMap[state] || state}
                  </option>
                ))}
              </select>
            </div>
          );
        })()}

        {/* City breakdown for selected state */}
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
                    onClick={() => {
                      setSelectedIncident(incident);
                      if (incident.lat && incident.lon) {
                        zoomToIncident(incident);
                      }
                    }}
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
        })()}

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

      {/* Bottom Detail Drawer — always rendered, animated via CSS */}
      <div className={`detail-drawer-overlay ${drawerOpen && selectedIncident ? 'visible' : ''}`}
        onClick={() => setSelectedIncident(null)} />
      <div className={`detail-drawer ${drawerOpen && selectedIncident ? 'open' : ''}`}>
        {selectedIncident && (
          <>
            <div className="detail-drawer-header">
              <div className="detail-drawer-title">
                <h3>{selectedIncident.city}, {getStateDisplayName(selectedIncident)}</h3>
                {selectedIncident.victim_name && (
                  <span className="detail-drawer-subtitle">{selectedIncident.victim_name}</span>
                )}
              </div>
              <div className="detail-drawer-actions">
                {selectedIncident.lat && selectedIncident.lon && (
                  <button className="detail-drawer-action-btn" onClick={() => {
                    setDrawerOpen(false);
                    zoomToIncident(selectedIncident);
                  }}>
                    Zoom
                  </button>
                )}
                <button className="detail-drawer-close" onClick={() => setSelectedIncident(null)}>&times;</button>
              </div>
            </div>
            <div className="detail-drawer-body">
              <div className="detail-drawer-columns">
                <div className="detail-drawer-main">
                  {extractionData ? (
                    <ExtractionDetailView
                      data={extractionData}
                      articleContent={articleContent || undefined}
                      sourceUrl={sourceUrl || undefined}
                    />
                  ) : (
                    <IncidentDetailView
                      incident={fullIncident || selectedIncident}
                      extractedData={null}
                      articleContent={articleContent || undefined}
                      showSource={true}
                    />
                  )}
                </div>
                <div className="detail-drawer-side">
                  {/* Connected Incidents */}
                  <div className="connected-incidents">
                    <h4>Connected Incidents</h4>

                    {connectionsLoading && <p className="connected-loading">Loading connections...</p>}
                    {!connectionsLoading && connections?.events && connections.events.length > 0 && (
                      <div className="connected-events">
                        {connections.events.map(ev => (
                          <div key={ev.event_id} className="connected-event-group">
                            <div className="connected-event-name">
                              <span>{ev.event_name}</span>
                              <button
                                className="connected-event-map-btn"
                                title="Show all incidents from this event on the map"
                                onClick={() => {
                                  setFilters(f => ({ ...f, event_id: ev.event_id }));
                                  setSelectedIncident(null);
                                }}
                              >
                                View on Map
                              </button>
                            </div>
                            <div className="connected-event-siblings">
                              {ev.incidents.map(sib => (
                                <div
                                  key={sib.id}
                                  className="connected-incident-item"
                                  onClick={() => {
                                    const full = incidents.find(i => i.id === sib.id);
                                    if (full) setSelectedIncident(full);
                                  }}
                                >
                                  <span className="connected-incident-date">{sib.date?.split('T')[0] || '—'}</span>
                                  <span className="connected-incident-location">
                                    {sib.city}{sib.city && sib.state ? ', ' : ''}{sib.state}
                                  </span>
                                  {sib.incident_type && (
                                    <span className="connected-incident-type">{sib.incident_type.replace(/_/g, ' ')}</span>
                                  )}
                                  {sib.outcome_category && (
                                    <span className={`connected-incident-outcome ${sib.outcome_category === 'death' ? 'fatal' : ''}`}>
                                      {sib.outcome_category}
                                    </span>
                                  )}
                                </div>
                              ))}
                            </div>
                          </div>
                        ))}
                      </div>
                    )}

                    {selectedIncident.linked_ids && selectedIncident.linked_ids.length > 0 && (
                      <div className="connected-linked-reports">
                        <div className="connected-section-label">Linked Reports ({selectedIncident.linked_ids.length})</div>
                        {selectedIncident.linked_ids.map(linkedId => {
                          const linkedInc = incidents.find(i => i.id === linkedId);
                          return (
                            <div
                              key={linkedId}
                              className="connected-incident-item"
                              onClick={() => {
                                if (linkedInc) setSelectedIncident(linkedInc);
                              }}
                              style={{ cursor: linkedInc ? 'pointer' : 'default' }}
                            >
                              {linkedInc ? (
                                <>
                                  <span className="connected-incident-date">{formatDate(linkedInc.date)}</span>
                                  <span className="connected-incident-location">
                                    {linkedInc.city}{linkedInc.city && linkedInc.state ? ', ' : ''}{getStateDisplayName(linkedInc)}
                                  </span>
                                  <span className="connected-incident-type">{linkedInc.source_name || `Tier ${linkedInc.tier}`}</span>
                                </>
                              ) : (
                                <span className="connected-incident-id">{linkedId}</span>
                              )}
                            </div>
                          );
                        })}
                      </div>
                    )}

                    {!connectionsLoading && (!connections?.events || connections.events.length === 0) &&
                      (!selectedIncident.linked_ids || selectedIncident.linked_ids.length === 0) && (
                      <p className="connected-empty">No connected incidents found.</p>
                    )}
                  </div>
                </div>
              </div>
            </div>
          </>
        )}
      </div>

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

        {/* Stats */}
        {stats && (
          <div className={`stats-section ${statsCollapsed ? 'stats-collapsed' : ''}`}>
            <button className="stats-toggle-btn" onClick={toggleStats} title={statsCollapsed ? 'Expand stats' : 'Collapse stats'}>
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
                    : '—'}
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
                      : '—'}
                  </div>
                  <div className="stat-label">Avg Confidence</div>
                </div>
              </div>
            )}
          </div>
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

          {/* Map style toggle - only show on map tab */}
          {viewTab === 'map' && adminPanel === 'none' && (
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

        {/* Event Detail Banner */}
        {activeEvent && adminPanel === 'none' && (
          <div className="event-banner">
            <div className="event-banner-header">
              <div className="event-banner-title">
                <h3>{activeEvent.name}</h3>
                <div className="event-banner-meta">
                  {activeEvent.event_type && (
                    <span className="event-banner-type">{activeEvent.event_type.replace(/_/g, ' ')}</span>
                  )}
                  <span className="event-banner-dates">
                    {activeEvent.start_date?.split('T')[0]}
                    {activeEvent.end_date && ` — ${activeEvent.end_date.split('T')[0]}`}
                    {activeEvent.ongoing && ' (ongoing)'}
                  </span>
                  {activeEvent.primary_city && activeEvent.primary_state && (
                    <span className="event-banner-location">{activeEvent.primary_city}, {activeEvent.primary_state}</span>
                  )}
                  <span className="event-banner-count">{activeEvent.incident_count} incident{activeEvent.incident_count !== 1 ? 's' : ''}</span>
                </div>
              </div>
              <button className="event-banner-close" onClick={() => setFilters(f => ({ ...f, event_id: undefined }))}>
                Clear Event
              </button>
            </div>
            {activeEvent.ai_summary && (
              <p className="event-banner-summary">{activeEvent.ai_summary}</p>
            )}
            {!activeEvent.ai_summary && activeEvent.description && (
              <p className="event-banner-summary">{activeEvent.description}</p>
            )}
            {activeEvent.actors && activeEvent.actors.length > 0 && (
              <div className="event-banner-actors">
                {activeEvent.actors.map((actor, idx) => (
                  <span key={`${actor.id}-${actor.role}-${idx}`} className={`event-banner-actor event-banner-actor-${actor.role}`}>
                    {actor.canonical_name}
                    <span className="event-banner-actor-role">{actor.role.replace(/_/g, ' ')}</span>
                  </span>
                ))}
              </div>
            )}
            {activeEvent.tags && activeEvent.tags.length > 0 && (
              <div className="event-banner-tags">
                {activeEvent.tags.map(tag => (
                  <span key={tag} className="event-banner-tag">{tag}</span>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Map View */}
        {/* Timeline Controls */}
        {viewTab === 'map' && adminPanel === 'none' && timelineEnabled && (
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

        {viewTab === 'map' && adminPanel === 'none' && (
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
                          <strong>{incident.city}, {getStateDisplayName(incident)}</strong>
                          {incident.victim_name && (
                            <>
                              <br />
                              <em>{incident.victim_name}</em>
                            </>
                          )}
                          <br />
                          {getTypeDisplayName(incident.incident_type)}
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
        {viewTab === 'charts' && adminPanel === 'none' && (
          <Charts stats={stats} incidents={incidents} />
        )}

        {/* Street View */}
        {viewTab === 'streetview' && adminPanel === 'none' && selectedIncident?.lat && selectedIncident?.lon && (
          <div className="street-view-container">
            <div className="street-view-info">
              <span>{selectedIncident.city}, {getStateDisplayName(selectedIncident)}</span>
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
          <span className="keyboard-hint" title="j/k or arrows: navigate | h: heatmap | d: dark mode | m/c/s: views | Esc: clear">
            Keyboard: j/k h d m c s Esc
          </span>
        </div>
      </main>
      </>
      )}
    </div>
  );
}

export default App;
