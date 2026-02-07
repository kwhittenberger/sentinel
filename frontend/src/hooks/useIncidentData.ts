import { useState, useEffect, useCallback } from 'react';
import type { Incident, Stats, Filters, IncidentType, DomainSummary, EventListItem, Event } from '../types';
import { fetchIncidents, fetchStats, fetchQueueStats, fetchDomainsSummary, fetchEventList } from '../api';

interface QueueStats {
  pending: number;
  in_review: number;
  approved: number;
  rejected: number;
}

export interface IncidentDataReturn {
  // Core data
  incidents: Incident[];
  setIncidents: React.Dispatch<React.SetStateAction<Incident[]>>;
  stats: Stats | null;
  setStats: React.Dispatch<React.SetStateAction<Stats | null>>;
  loading: boolean;

  // Filters
  filters: Filters;
  setFilters: React.Dispatch<React.SetStateAction<Filters>>;

  // Queue & domain data
  queueStats: QueueStats | null;
  setQueueStats: React.Dispatch<React.SetStateAction<QueueStats | null>>;
  domainsSummary: DomainSummary[];
  eventList: EventListItem[];
  incidentTypes: IncidentType[];

  // Active event
  activeEvent: Event | null;

  // Dark mode
  darkMode: boolean;
  setDarkMode: React.Dispatch<React.SetStateAction<boolean>>;

  // Helpers
  getTypeDisplayName: (typeName: string | undefined) => string;
  getStateDisplayName: (incident: Incident) => string;
}

export function useIncidentData(): IncidentDataReturn {
  const [incidents, setIncidents] = useState<Incident[]>([]);
  const [stats, setStats] = useState<Stats | null>(null);
  const [loading, setLoading] = useState(true);

  // Initialize filters from URL params
  const [filters, setFilters] = useState<Filters>(() => {
    const params = new URLSearchParams(window.location.search);
    // Default to one year ago if no date_start specified
    const oneYearAgo = new Date();
    oneYearAgo.setFullYear(oneYearAgo.getFullYear() - 1);
    const defaultDateStart = oneYearAgo.toISOString().split('T')[0];
    // Default end date to today
    const today = new Date().toISOString().split('T')[0];

    // Validate date params: must parse to a valid Date in YYYY-MM-DD format
    const parseValidDate = (value: string | null, fallback: string): string => {
      if (!value) return fallback;
      const parsed = new Date(value);
      if (isNaN(parsed.getTime())) return fallback;
      // Ensure it's a reasonable YYYY-MM-DD string (not random text that Date() accepts)
      if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return fallback;
      return value;
    };

    return {
      tiers: params.get('tiers') ? params.get('tiers')!.split(',').map(Number) : [1, 2, 3, 4],
      states: params.get('states') ? params.get('states')!.split(',') : [],
      categories: params.get('categories') ? params.get('categories')!.split(',') : [],
      date_start: parseValidDate(params.get('date_start'), defaultDateStart),
      date_end: parseValidDate(params.get('date_end'), today),
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
    }).catch((err) => {
      console.error('Failed to load incidents/stats:', err);
      setLoading(false);
    });
  }, [filters]);

  // Queue stats, domains, events
  const [queueStats, setQueueStats] = useState<QueueStats | null>(null);
  const [domainsSummary, setDomainsSummary] = useState<DomainSummary[]>([]);
  const [eventList, setEventList] = useState<EventListItem[]>([]);
  const [incidentTypes, setIncidentTypes] = useState<IncidentType[]>([]);

  // Load queue stats for sidebar badge, domains, and events for filters
  useEffect(() => {
    fetchQueueStats().then(setQueueStats).catch(() => {});
    fetchDomainsSummary().then(data => setDomainsSummary(data.domains)).catch(() => {});
    fetchEventList().then(setEventList).catch(() => {});
  }, []);

  // Load event details when event filter is active
  const [activeEvent, setActiveEvent] = useState<Event | null>(null);

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

  // Dark mode
  const [darkMode, setDarkMode] = useState(() => {
    const stored = localStorage.getItem('darkMode');
    return stored ? stored === 'true' : window.matchMedia('(prefers-color-scheme: dark)').matches;
  });

  // Apply dark mode class to document
  useEffect(() => {
    document.documentElement.classList.toggle('dark', darkMode);
    localStorage.setItem('darkMode', String(darkMode));
  }, [darkMode]);

  return {
    incidents,
    setIncidents,
    stats,
    setStats,
    loading,
    filters,
    setFilters,
    queueStats,
    setQueueStats,
    domainsSummary,
    eventList,
    incidentTypes,
    activeEvent,
    darkMode,
    setDarkMode,
    getTypeDisplayName,
    getStateDisplayName,
  };
}
