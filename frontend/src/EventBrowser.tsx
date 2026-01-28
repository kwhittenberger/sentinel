import { useState, useEffect, useCallback } from 'react';
import type { Event, EventSuggestion } from './types';

interface EventBrowserProps {
  onRefresh?: () => void;
}

const API_BASE = '';

export function EventBrowser({ onRefresh }: EventBrowserProps) {
  const [events, setEvents] = useState<Event[]>([]);
  const [suggestions, setSuggestions] = useState<EventSuggestion[]>([]);
  const [selectedEvent, setSelectedEvent] = useState<Event | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showCreateForm, setShowCreateForm] = useState(false);
  const [showSuggestions, setShowSuggestions] = useState(false);
  const [filterState, setFilterState] = useState('');
  const [filterOngoing, setFilterOngoing] = useState(false);

  const [formData, setFormData] = useState({
    name: '',
    event_type: '',
    start_date: '',
    end_date: '',
    ongoing: false,
    primary_state: '',
    primary_city: '',
    geographic_scope: 'local',
    description: '',
    tags: '',
  });

  const loadEvents = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (filterState) params.append('state', filterState);
      if (filterOngoing) params.append('ongoing_only', 'true');

      const res = await fetch(`${API_BASE}/api/events?${params}`);
      if (!res.ok) throw new Error('Failed to load events');
      const data = await res.json();
      setEvents(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load events');
    } finally {
      setLoading(false);
    }
  }, [filterState, filterOngoing]);

  const loadSuggestions = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/events/suggestions`);
      if (!res.ok) throw new Error('Failed to load suggestions');
      const data = await res.json();
      setSuggestions(data);
    } catch (err) {
      console.error('Failed to load suggestions:', err);
    }
  }, []);

  const loadEventDetails = useCallback(async (eventId: string) => {
    try {
      const res = await fetch(`${API_BASE}/api/events/${eventId}`);
      if (!res.ok) throw new Error('Failed to load event details');
      const data = await res.json();
      setSelectedEvent(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load event details');
    }
  }, []);

  useEffect(() => {
    loadEvents();
    loadSuggestions();
  }, [loadEvents, loadSuggestions]);

  const handleCreateEvent = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    setError(null);

    try {
      const eventData = {
        ...formData,
        tags: formData.tags ? formData.tags.split(',').map(t => t.trim()) : [],
        end_date: formData.end_date || undefined,
      };

      const res = await fetch(`${API_BASE}/api/events`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(eventData),
      });

      if (!res.ok) throw new Error('Failed to create event');

      const data = await res.json();
      setShowCreateForm(false);
      setFormData({
        name: '',
        event_type: '',
        start_date: '',
        end_date: '',
        ongoing: false,
        primary_state: '',
        primary_city: '',
        geographic_scope: 'local',
        description: '',
        tags: '',
      });
      await loadEvents();
      await loadEventDetails(data.id);
      onRefresh?.();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create event');
    } finally {
      setSaving(false);
    }
  };

  const handleApplySuggestion = async (suggestion: EventSuggestion) => {
    setSaving(true);
    setError(null);

    try {
      const res = await fetch(`${API_BASE}/api/events`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: suggestion.suggested_name,
          start_date: suggestion.date,
          event_type: suggestion.type,
          primary_state: suggestion.state,
        }),
      });

      if (!res.ok) throw new Error('Failed to create event from suggestion');

      const eventData = await res.json();

      // Link incidents
      for (const incidentId of suggestion.incident_ids) {
        await fetch(`${API_BASE}/api/events/${eventData.id}/incidents`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ incident_id: incidentId, assigned_by: 'ai' }),
        });
      }

      await loadEvents();
      await loadEventDetails(eventData.id);
      await loadSuggestions();
      setShowSuggestions(false);
      onRefresh?.();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to apply suggestion');
    } finally {
      setSaving(false);
    }
  };

  const handleUnlinkIncident = async (eventId: string, incidentId: string) => {
    try {
      await fetch(`${API_BASE}/api/events/${eventId}/incidents/${incidentId}`, {
        method: 'DELETE',
      });
      await loadEventDetails(eventId);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to unlink incident');
    }
  };

  if (loading && events.length === 0) {
    return <div className="admin-loading">Loading events...</div>;
  }

  return (
    <div className="admin-page">
      <div className="page-header">
        <h2>Events</h2>
        <div className="page-actions">
          {suggestions.length > 0 && (
            <button
              className="action-btn"
              onClick={() => setShowSuggestions(true)}
            >
              AI Suggestions ({suggestions.length})
            </button>
          )}
          <button
            className="action-btn primary"
            onClick={() => setShowCreateForm(true)}
          >
            + Create Event
          </button>
        </div>
      </div>

      {error && <div className="error-banner">{error}</div>}

      {/* Filters */}
      <div className="filter-bar">
        <input
          type="text"
          placeholder="Filter by state..."
          value={filterState}
          onChange={(e) => setFilterState(e.target.value)}
        />
        <label className="checkbox-label">
          <input
            type="checkbox"
            checked={filterOngoing}
            onChange={(e) => setFilterOngoing(e.target.checked)}
          />
          Ongoing only
        </label>
      </div>

      <div className="split-view">
        {/* Events List */}
        <div className="list-panel">
          <div className="list-header">
            <h3>Events ({events.length})</h3>
          </div>
          <div className="list-items">
            {events.map((event) => (
              <div
                key={event.id}
                className={`list-item ${selectedEvent?.id === event.id ? 'selected' : ''}`}
                onClick={() => loadEventDetails(event.id)}
              >
                <div className="item-content">
                  <div className="item-title">{event.name}</div>
                  <div className="item-meta">
                    {event.event_type && <span className="badge type">{event.event_type}</span>}
                    {event.ongoing && <span className="badge ongoing">Ongoing</span>}
                    <span>{event.primary_state}</span>
                    <span className="incident-count">{event.incident_count} incidents</span>
                  </div>
                  <div className="item-date">
                    {event.start_date}
                    {event.end_date && ` - ${event.end_date}`}
                  </div>
                </div>
              </div>
            ))}
            {events.length === 0 && (
              <div className="empty-list">No events found</div>
            )}
          </div>
        </div>

        {/* Event Details */}
        <div className="detail-panel">
          {selectedEvent ? (
            <>
              <div className="detail-header">
                <div>
                  <h3>{selectedEvent.name}</h3>
                  <div className="event-meta">
                    {selectedEvent.event_type && (
                      <span className="badge type">{selectedEvent.event_type}</span>
                    )}
                    {selectedEvent.ongoing && <span className="badge ongoing">Ongoing</span>}
                    <span className="location">
                      {selectedEvent.primary_city && `${selectedEvent.primary_city}, `}
                      {selectedEvent.primary_state}
                    </span>
                  </div>
                </div>
              </div>

              <div className="event-info">
                <div className="info-row">
                  <span className="label">Date Range:</span>
                  <span>
                    {selectedEvent.start_date}
                    {selectedEvent.end_date && ` to ${selectedEvent.end_date}`}
                  </span>
                </div>
                {selectedEvent.geographic_scope && (
                  <div className="info-row">
                    <span className="label">Scope:</span>
                    <span>{selectedEvent.geographic_scope}</span>
                  </div>
                )}
                {selectedEvent.description && (
                  <div className="info-row full">
                    <span className="label">Description:</span>
                    <p>{selectedEvent.description}</p>
                  </div>
                )}
                {selectedEvent.ai_summary && (
                  <div className="info-row full">
                    <span className="label">AI Summary:</span>
                    <p className="ai-summary">{selectedEvent.ai_summary}</p>
                  </div>
                )}
                {selectedEvent.tags && selectedEvent.tags.length > 0 && (
                  <div className="info-row">
                    <span className="label">Tags:</span>
                    <div className="tags">
                      {selectedEvent.tags.map((tag) => (
                        <span key={tag} className="tag">{tag}</span>
                      ))}
                    </div>
                  </div>
                )}
              </div>

              <div className="incidents-section">
                <h4>Linked Incidents ({selectedEvent.incident_count})</h4>
                <div className="incidents-list">
                  {selectedEvent.incidents?.map((incident) => (
                    <div key={incident.incident_id} className="incident-card">
                      <div className="incident-header">
                        <span className="incident-date">{incident.date}</span>
                        <span className="incident-location">
                          {incident.city && `${incident.city}, `}{incident.state}
                        </span>
                        {incident.is_primary_event && (
                          <span className="badge primary">Primary</span>
                        )}
                      </div>
                      {incident.incident_type && (
                        <div className="incident-type">{incident.incident_type}</div>
                      )}
                      {incident.description && (
                        <p className="incident-desc">{incident.description.slice(0, 150)}...</p>
                      )}
                      <button
                        className="unlink-btn"
                        onClick={() => handleUnlinkIncident(selectedEvent.id, incident.incident_id)}
                      >
                        Unlink
                      </button>
                    </div>
                  ))}
                  {(!selectedEvent.incidents || selectedEvent.incidents.length === 0) && (
                    <p className="no-data">No incidents linked to this event</p>
                  )}
                </div>
              </div>
            </>
          ) : (
            <div className="empty-state">
              <p>Select an event to view details</p>
            </div>
          )}
        </div>
      </div>

      {/* Create Event Modal */}
      {showCreateForm && (
        <div className="modal-overlay" onClick={() => setShowCreateForm(false)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h3>Create Event</h3>
              <button className="close-btn" onClick={() => setShowCreateForm(false)}>&times;</button>
            </div>
            <form onSubmit={handleCreateEvent}>
              <div className="modal-body">
                <div className="form-group">
                  <label>Name *</label>
                  <input
                    type="text"
                    value={formData.name}
                    onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                    required
                    placeholder="e.g. Denver ICE Protests May 2025"
                  />
                </div>

                <div className="form-row">
                  <div className="form-group">
                    <label>Event Type</label>
                    <select
                      value={formData.event_type}
                      onChange={(e) => setFormData({ ...formData, event_type: e.target.value })}
                    >
                      <option value="">Select type</option>
                      <option value="protest_series">Protest Series</option>
                      <option value="enforcement_operation">Enforcement Operation</option>
                      <option value="crime_spree">Crime Spree</option>
                      <option value="raid_series">Raid Series</option>
                      <option value="legal_proceedings">Legal Proceedings</option>
                      <option value="cluster">Incident Cluster</option>
                    </select>
                  </div>
                  <div className="form-group">
                    <label>Geographic Scope</label>
                    <select
                      value={formData.geographic_scope}
                      onChange={(e) => setFormData({ ...formData, geographic_scope: e.target.value })}
                    >
                      <option value="local">Local</option>
                      <option value="regional">Regional</option>
                      <option value="statewide">Statewide</option>
                      <option value="national">National</option>
                    </select>
                  </div>
                </div>

                <div className="form-row">
                  <div className="form-group">
                    <label>Start Date *</label>
                    <input
                      type="date"
                      value={formData.start_date}
                      onChange={(e) => setFormData({ ...formData, start_date: e.target.value })}
                      required
                    />
                  </div>
                  <div className="form-group">
                    <label>End Date</label>
                    <input
                      type="date"
                      value={formData.end_date}
                      onChange={(e) => setFormData({ ...formData, end_date: e.target.value })}
                    />
                  </div>
                </div>

                <div className="form-group">
                  <label className="checkbox-label">
                    <input
                      type="checkbox"
                      checked={formData.ongoing}
                      onChange={(e) => setFormData({ ...formData, ongoing: e.target.checked })}
                    />
                    Ongoing event
                  </label>
                </div>

                <div className="form-row">
                  <div className="form-group">
                    <label>Primary State</label>
                    <input
                      type="text"
                      value={formData.primary_state}
                      onChange={(e) => setFormData({ ...formData, primary_state: e.target.value })}
                      placeholder="e.g. CO"
                    />
                  </div>
                  <div className="form-group">
                    <label>Primary City</label>
                    <input
                      type="text"
                      value={formData.primary_city}
                      onChange={(e) => setFormData({ ...formData, primary_city: e.target.value })}
                      placeholder="e.g. Denver"
                    />
                  </div>
                </div>

                <div className="form-group">
                  <label>Description</label>
                  <textarea
                    value={formData.description}
                    onChange={(e) => setFormData({ ...formData, description: e.target.value })}
                    rows={3}
                  />
                </div>

                <div className="form-group">
                  <label>Tags (comma-separated)</label>
                  <input
                    type="text"
                    value={formData.tags}
                    onChange={(e) => setFormData({ ...formData, tags: e.target.value })}
                    placeholder="e.g. protest, sanctuary, ice"
                  />
                </div>
              </div>
              <div className="modal-footer">
                <button type="button" className="action-btn" onClick={() => setShowCreateForm(false)}>
                  Cancel
                </button>
                <button type="submit" className="action-btn primary" disabled={saving}>
                  {saving ? 'Creating...' : 'Create Event'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* AI Suggestions Modal */}
      {showSuggestions && (
        <div className="modal-overlay" onClick={() => setShowSuggestions(false)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h3>AI-Suggested Event Groupings</h3>
              <button className="close-btn" onClick={() => setShowSuggestions(false)}>&times;</button>
            </div>
            <div className="modal-body">
              {suggestions.map((suggestion, idx) => (
                <div key={idx} className="suggestion-card">
                  <div className="suggestion-header">
                    <span className="suggestion-name">{suggestion.suggested_name}</span>
                    <span className="suggestion-confidence">
                      {(suggestion.confidence * 100).toFixed(0)}% confidence
                    </span>
                  </div>
                  <div className="suggestion-meta">
                    <span>{suggestion.incident_count} incidents</span>
                    {suggestion.state && <span>{suggestion.state}</span>}
                    {suggestion.date && <span>{suggestion.date}</span>}
                  </div>
                  <button
                    className="action-btn primary small"
                    onClick={() => handleApplySuggestion(suggestion)}
                    disabled={saving}
                  >
                    Create Event
                  </button>
                </div>
              ))}
              {suggestions.length === 0 && (
                <p className="no-data">No suggestions available</p>
              )}
            </div>
          </div>
        </div>
      )}

      <style>{`
        .filter-bar {
          display: flex;
          gap: 1rem;
          margin-bottom: 1rem;
          align-items: center;
        }

        .filter-bar input[type="text"] {
          padding: 0.5rem 1rem;
          border-radius: 4px;
          border: 1px solid var(--border-color);
          background: var(--bg-secondary);
          width: 200px;
        }

        .checkbox-label {
          display: flex;
          align-items: center;
          gap: 0.5rem;
          cursor: pointer;
        }

        .split-view {
          display: grid;
          grid-template-columns: 320px 1fr;
          gap: 1rem;
        }

        .list-panel {
          background: var(--bg-secondary);
          border-radius: 8px;
          overflow: hidden;
        }

        .list-header {
          padding: 0.75rem 1rem;
          border-bottom: 1px solid var(--border-color);
        }

        .list-items {
          max-height: calc(100vh - 350px);
          overflow-y: auto;
        }

        .list-item {
          padding: 0.75rem 1rem;
          cursor: pointer;
          border-bottom: 1px solid var(--border-color);
        }

        .list-item:hover {
          background: var(--bg-hover);
        }

        .list-item.selected {
          background: var(--bg-active);
          border-left: 3px solid var(--primary-color);
        }

        .item-title {
          font-weight: 500;
          margin-bottom: 0.25rem;
        }

        .item-meta {
          display: flex;
          gap: 0.5rem;
          font-size: 0.75rem;
          align-items: center;
          flex-wrap: wrap;
        }

        .item-date {
          font-size: 0.75rem;
          color: var(--text-secondary);
          margin-top: 0.25rem;
        }

        .incident-count {
          color: var(--text-secondary);
        }

        .detail-panel {
          background: var(--bg-secondary);
          border-radius: 8px;
          padding: 1rem;
        }

        .detail-header {
          margin-bottom: 1rem;
          padding-bottom: 1rem;
          border-bottom: 1px solid var(--border-color);
        }

        .event-meta {
          display: flex;
          gap: 0.5rem;
          align-items: center;
          margin-top: 0.5rem;
        }

        .location {
          color: var(--text-secondary);
        }

        .event-info {
          margin-bottom: 1.5rem;
        }

        .info-row {
          display: flex;
          gap: 1rem;
          margin-bottom: 0.5rem;
        }

        .info-row.full {
          flex-direction: column;
          gap: 0.25rem;
        }

        .info-row .label {
          font-weight: 500;
          min-width: 100px;
        }

        .ai-summary {
          font-style: italic;
          background: var(--bg-primary);
          padding: 0.75rem;
          border-radius: 6px;
        }

        .tags {
          display: flex;
          gap: 0.5rem;
          flex-wrap: wrap;
        }

        .tag {
          background: var(--bg-primary);
          padding: 0.25rem 0.5rem;
          border-radius: 4px;
          font-size: 0.75rem;
        }

        .incidents-section h4 {
          margin-bottom: 1rem;
        }

        .incidents-list {
          display: flex;
          flex-direction: column;
          gap: 0.75rem;
          max-height: 400px;
          overflow-y: auto;
        }

        .incident-card {
          background: var(--bg-primary);
          padding: 0.75rem;
          border-radius: 6px;
          position: relative;
        }

        .incident-header {
          display: flex;
          gap: 0.75rem;
          margin-bottom: 0.25rem;
          align-items: center;
        }

        .incident-date {
          font-weight: 500;
        }

        .incident-location {
          color: var(--text-secondary);
          font-size: 0.85rem;
        }

        .incident-type {
          font-size: 0.85rem;
          color: var(--text-secondary);
        }

        .incident-desc {
          font-size: 0.8rem;
          margin-top: 0.5rem;
          color: var(--text-secondary);
        }

        .unlink-btn {
          position: absolute;
          top: 0.5rem;
          right: 0.5rem;
          font-size: 0.7rem;
          padding: 0.25rem 0.5rem;
          background: none;
          border: 1px solid var(--border-color);
          border-radius: 4px;
          cursor: pointer;
          color: var(--text-secondary);
        }

        .unlink-btn:hover {
          background: var(--bg-hover);
          color: #ef4444;
          border-color: #ef4444;
        }

        .badge {
          display: inline-block;
          padding: 0.125rem 0.5rem;
          border-radius: 4px;
          font-size: 0.7rem;
          text-transform: uppercase;
        }

        .badge.type {
          background: #3b82f6;
          color: white;
        }

        .badge.ongoing {
          background: #22c55e;
          color: white;
        }

        .badge.primary {
          background: #f59e0b;
          color: white;
        }

        .form-row {
          display: grid;
          grid-template-columns: 1fr 1fr;
          gap: 1rem;
        }

        .suggestion-card {
          background: var(--bg-primary);
          padding: 1rem;
          border-radius: 8px;
          margin-bottom: 0.75rem;
        }

        .suggestion-header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          margin-bottom: 0.5rem;
        }

        .suggestion-name {
          font-weight: 500;
        }

        .suggestion-confidence {
          font-size: 0.8rem;
          color: var(--text-secondary);
        }

        .suggestion-meta {
          display: flex;
          gap: 1rem;
          font-size: 0.85rem;
          color: var(--text-secondary);
          margin-bottom: 0.75rem;
        }

        .empty-state, .empty-list, .no-data {
          display: flex;
          align-items: center;
          justify-content: center;
          height: 100px;
          color: var(--text-secondary);
        }

        .error-banner {
          background: #fee2e2;
          color: #dc2626;
          padding: 0.75rem 1rem;
          border-radius: 6px;
          margin-bottom: 1rem;
        }
      `}</style>
    </div>
  );
}

export default EventBrowser;
