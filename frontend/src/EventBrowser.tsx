import { useState, useEffect, useCallback } from 'react';
import type { Event, EventSuggestion, EventActor, Incident } from './types';
import { IncidentDetailView } from './IncidentDetailView';
import './ExtensibleSystem.css';

interface EventBrowserProps {
  onRefresh?: () => void;
}

const API_BASE = '';

export function EventBrowser({ onRefresh }: EventBrowserProps) {
  const [events, setEvents] = useState<Event[]>([]);
  const [suggestions, setSuggestions] = useState<EventSuggestion[]>([]);
  const [selectedEvent, setSelectedEvent] = useState<Event | null>(null);
  const [selectedIncident, setSelectedIncident] = useState<Incident | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showCreateForm, setShowCreateForm] = useState(false);
  const [showSuggestions, setShowSuggestions] = useState(false);
  const [showIncidentDetail, setShowIncidentDetail] = useState(false);
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
          start_date: suggestion.start_date,
          end_date: suggestion.end_date !== suggestion.start_date ? suggestion.end_date : undefined,
          event_type: suggestion.event_type,
          primary_state: suggestion.primary_state,
          primary_city: suggestion.primary_city,
        }),
      });

      if (!res.ok) throw new Error('Failed to create event from suggestion');

      const eventData = await res.json();

      // Link incidents
      for (let i = 0; i < suggestion.incident_ids.length; i++) {
        await fetch(`${API_BASE}/api/events/${eventData.id}/incidents`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            incident_id: suggestion.incident_ids[i],
            assigned_by: 'ai',
            is_primary: i === 0,
            sequence_number: i + 1,
          }),
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

  const handleViewIncident = async (incidentId: string) => {
    try {
      const res = await fetch(`${API_BASE}/api/incidents/${incidentId}`);
      if (!res.ok) throw new Error('Failed to load incident');
      const data = await res.json();
      setSelectedIncident(data);
      setShowIncidentDetail(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load incident details');
    }
  };

  if (loading && events.length === 0) {
    return <div className="ext-loading">Loading events...</div>;
  }

  return (
    <div className="ext-browser" style={{ flexDirection: 'column' }}>
      <div className="ext-page-header">
        <h2>Events</h2>
        <div className="ext-page-actions">
          {suggestions.length > 0 && (
            <button
              className="ext-btn ext-btn-warning"
              onClick={() => setShowSuggestions(true)}
            >
              AI Suggestions ({suggestions.length})
            </button>
          )}
          <button
            className="ext-btn ext-btn-primary"
            onClick={() => setShowCreateForm(true)}
          >
            + Create Event
          </button>
        </div>
      </div>

      {error && <div className="ext-error">{error}</div>}

      {/* Filters */}
      <div className="ext-filter-bar">
        <input
          type="text"
          placeholder="Filter by state..."
          value={filterState}
          onChange={(e) => setFilterState(e.target.value)}
        />
        <label className="ext-checkbox-label">
          <input
            type="checkbox"
            checked={filterOngoing}
            onChange={(e) => setFilterOngoing(e.target.checked)}
          />
          Ongoing only
        </label>
      </div>

      <div className="ext-split-view">
        {/* Events List */}
        <div className="ext-list-panel">
          <div className="ext-list-panel-header">
            <h3>Events ({events.length})</h3>
          </div>
          <div className="ext-list-panel-items">
            {events.map((event) => (
              <div
                key={event.id}
                className={`ext-list-panel-item ${selectedEvent?.id === event.id ? 'selected' : ''}`}
                onClick={() => loadEventDetails(event.id)}
              >
                <div className="ext-item-title">{event.name}</div>
                <div className="ext-item-meta">
                  {event.event_type && <span className="ext-badge ext-badge-type">{event.event_type}</span>}
                  {event.ongoing && <span className="ext-badge ext-badge-ongoing">Ongoing</span>}
                  <span>{event.primary_state}</span>
                  <span className="ext-incident-count">{event.incident_count} incidents</span>
                </div>
                <div className="ext-item-date">
                  {event.start_date}
                  {event.end_date && ` - ${event.end_date}`}
                </div>
              </div>
            ))}
            {events.length === 0 && (
              <div className="ext-empty-state">No events found</div>
            )}
          </div>
        </div>

        {/* Event Details */}
        <div className="ext-detail-panel">
          {selectedEvent ? (
            <>
              <div className="ext-detail-header">
                <div>
                  <h3>{selectedEvent.name}</h3>
                  <div className="ext-item-meta" style={{ marginTop: '0.5rem' }}>
                    {selectedEvent.event_type && (
                      <span className="ext-badge ext-badge-type">{selectedEvent.event_type}</span>
                    )}
                    {selectedEvent.ongoing && <span className="ext-badge ext-badge-ongoing">Ongoing</span>}
                    <span style={{ color: 'var(--text-muted)' }}>
                      {selectedEvent.primary_city && `${selectedEvent.primary_city}, `}
                      {selectedEvent.primary_state}
                    </span>
                  </div>
                </div>
              </div>

              <div className="ext-event-info">
                <div className="ext-info-row">
                  <span className="label">Date Range:</span>
                  <span>
                    {selectedEvent.start_date}
                    {selectedEvent.end_date && ` to ${selectedEvent.end_date}`}
                  </span>
                </div>
                {selectedEvent.geographic_scope && (
                  <div className="ext-info-row">
                    <span className="label">Scope:</span>
                    <span>{selectedEvent.geographic_scope}</span>
                  </div>
                )}
                {selectedEvent.description && (
                  <div className="ext-info-row full">
                    <span className="label">Description:</span>
                    <p>{selectedEvent.description}</p>
                  </div>
                )}
                {selectedEvent.ai_summary && (
                  <div className="ext-info-row full">
                    <span className="label">AI Summary:</span>
                    <p className="ext-ai-summary">{selectedEvent.ai_summary}</p>
                  </div>
                )}
                {selectedEvent.tags && selectedEvent.tags.length > 0 && (
                  <div className="ext-info-row">
                    <span className="label">Tags:</span>
                    <div className="ext-tag-list">
                      {selectedEvent.tags.map((tag) => (
                        <span key={tag} className="ext-tag">{tag}</span>
                      ))}
                    </div>
                  </div>
                )}
              </div>

              <div className="ext-incidents-section">
                <h4>Linked Incidents ({selectedEvent.incident_count})</h4>
                <div className="ext-incidents-list">
                  {selectedEvent.incidents?.map((incident) => (
                    <div
                      key={incident.incident_id}
                      className="ext-event-incident-card"
                      onClick={() => handleViewIncident(incident.incident_id)}
                    >
                      <div className="ext-event-incident-header">
                        <div className="ext-event-incident-main">
                          <span className="ext-incident-date">{incident.date}</span>
                          <span className="ext-incident-location">
                            {incident.city && `${incident.city}, `}{incident.state}
                          </span>
                          {incident.category && (
                            <span className={`ext-badge ext-badge-category-${incident.category}`}>
                              {incident.category}
                            </span>
                          )}
                          {incident.is_primary_event && (
                            <span className="ext-badge ext-badge-primary">Primary</span>
                          )}
                        </div>
                        <button
                          className="ext-unlink-btn"
                          onClick={(e) => {
                            e.stopPropagation();
                            handleUnlinkIncident(selectedEvent.id, incident.incident_id);
                          }}
                        >
                          Unlink
                        </button>
                      </div>
                      <div className="ext-incident-details">
                        {incident.incident_type && (
                          <div className="ext-incident-type">
                            {incident.incident_type_display ||
                             incident.incident_type.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())}
                          </div>
                        )}
                        {incident.victim_name && (
                          <div className="ext-incident-victim">
                            <strong>Victim:</strong> {incident.victim_name}
                          </div>
                        )}
                        {incident.outcome_category && (
                          <div className="ext-incident-outcome">
                            <strong>Outcome:</strong> {incident.outcome_category.replace(/_/g, ' ')}
                          </div>
                        )}
                      </div>
                      {(incident.description || incident.notes) && (
                        <p className="ext-incident-desc">
                          {(incident.description || incident.notes || '').slice(0, 200)}
                          {(incident.description || incident.notes || '').length > 200 ? '...' : ''}
                        </p>
                      )}
                    </div>
                  ))}
                  {(!selectedEvent.incidents || selectedEvent.incidents.length === 0) && (
                    <p className="ext-empty-state">No incidents linked to this event</p>
                  )}
                </div>
              </div>

              {/* Actors Section */}
              {selectedEvent.actors && selectedEvent.actors.length > 0 && (
                <div className="ext-actors-section">
                  <h4>Associated Actors ({selectedEvent.actors.length})</h4>
                  <div className="ext-actors-list">
                    {selectedEvent.actors.map((actor: EventActor) => (
                      <div key={`${actor.id}-${actor.role}`} className="ext-actor-item">
                        <div>
                          <span className="ext-actor-item-name">{actor.canonical_name}</span>
                          <div className="ext-actor-item-meta">
                            <span className={`ext-badge ext-badge-actor-${actor.actor_type}`}>
                              {actor.actor_type}
                            </span>
                            <span className={`ext-badge ext-badge-role-${actor.role}`}>
                              {actor.role.replace(/_/g, ' ')}
                            </span>
                            {actor.is_law_enforcement && (
                              <span className="ext-badge ext-badge-law-enforcement">Law Enforcement</span>
                            )}
                          </div>
                        </div>
                        <span className="ext-actor-item-count">
                          {actor.incident_count} incident{actor.incident_count !== 1 ? 's' : ''}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </>
          ) : (
            <div className="ext-empty-state">
              <p>Select an event to view details</p>
            </div>
          )}
        </div>
      </div>

      {/* Create Event Modal */}
      {showCreateForm && (
        <div className="ext-modal-overlay" onClick={() => setShowCreateForm(false)}>
          <div className="ext-modal ext-modal-lg" onClick={(e) => e.stopPropagation()}>
            <div className="ext-modal-header">
              <h3>Create Event</h3>
              <button className="ext-close-btn" onClick={() => setShowCreateForm(false)} aria-label="Close create event dialog">&times;</button>
            </div>
            <form onSubmit={handleCreateEvent}>
              <div className="ext-modal-body">
                <div className="ext-form-group">
                  <label>Name *</label>
                  <input
                    type="text"
                    value={formData.name}
                    onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                    required
                    placeholder="e.g. Denver ICE Protests May 2025"
                  />
                </div>

                <div className="ext-form-row">
                  <div className="ext-form-group">
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
                  <div className="ext-form-group">
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

                <div className="ext-form-row">
                  <div className="ext-form-group">
                    <label>Start Date *</label>
                    <input
                      type="date"
                      value={formData.start_date}
                      onChange={(e) => setFormData({ ...formData, start_date: e.target.value })}
                      required
                    />
                  </div>
                  <div className="ext-form-group">
                    <label>End Date</label>
                    <input
                      type="date"
                      value={formData.end_date}
                      onChange={(e) => setFormData({ ...formData, end_date: e.target.value })}
                    />
                  </div>
                </div>

                <div className="ext-form-group">
                  <label className="ext-checkbox-label">
                    <input
                      type="checkbox"
                      checked={formData.ongoing}
                      onChange={(e) => setFormData({ ...formData, ongoing: e.target.checked })}
                    />
                    Ongoing event
                  </label>
                </div>

                <div className="ext-form-row">
                  <div className="ext-form-group">
                    <label>Primary State</label>
                    <input
                      type="text"
                      value={formData.primary_state}
                      onChange={(e) => setFormData({ ...formData, primary_state: e.target.value })}
                      placeholder="e.g. CO"
                    />
                  </div>
                  <div className="ext-form-group">
                    <label>Primary City</label>
                    <input
                      type="text"
                      value={formData.primary_city}
                      onChange={(e) => setFormData({ ...formData, primary_city: e.target.value })}
                      placeholder="e.g. Denver"
                    />
                  </div>
                </div>

                <div className="ext-form-group">
                  <label>Description</label>
                  <textarea
                    value={formData.description}
                    onChange={(e) => setFormData({ ...formData, description: e.target.value })}
                    rows={3}
                  />
                </div>

                <div className="ext-form-group">
                  <label>Tags (comma-separated)</label>
                  <input
                    type="text"
                    value={formData.tags}
                    onChange={(e) => setFormData({ ...formData, tags: e.target.value })}
                    placeholder="e.g. protest, sanctuary, ice"
                  />
                </div>
              </div>
              <div className="ext-modal-footer">
                <button type="button" className="ext-btn ext-btn-secondary" onClick={() => setShowCreateForm(false)}>
                  Cancel
                </button>
                <button type="submit" className="ext-btn ext-btn-primary" disabled={saving}>
                  {saving ? 'Creating...' : 'Create Event'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* AI Suggestions Modal */}
      {showSuggestions && (
        <div className="ext-modal-overlay" onClick={() => setShowSuggestions(false)}>
          <div className="ext-modal ext-modal-wide" onClick={(e) => e.stopPropagation()}>
            <div className="ext-modal-header">
              <h3>Event Cluster Suggestions</h3>
              <button className="ext-close-btn" onClick={() => setShowSuggestions(false)} aria-label="Close event suggestions">&times;</button>
            </div>
            <div className="ext-modal-body ext-suggestions-modal-list">
              {suggestions.map((suggestion, idx) => (
                <div key={idx} className="ext-suggestion-card-enhanced">
                  <div className="ext-suggestion-header-enhanced">
                    <div className="ext-suggestion-title-group">
                      <span className="ext-suggestion-title-text">{suggestion.suggested_name}</span>
                      <div className="ext-suggestion-badges-group">
                        <span className={`ext-badge ext-badge-category-${suggestion.category}`}>
                          {suggestion.category}
                        </span>
                        <span className="ext-badge ext-badge-type">
                          {suggestion.incident_type.replace(/_/g, ' ')}
                        </span>
                      </div>
                    </div>
                    <span className={`ext-suggestion-confidence-enhanced ${suggestion.confidence >= 0.8 ? 'high' : suggestion.confidence >= 0.6 ? 'medium' : 'low'}`}>
                      {(suggestion.confidence * 100).toFixed(0)}%
                    </span>
                  </div>
                  <div className="ext-suggestion-meta-row">
                    <span>
                      <strong>{suggestion.incident_count}</strong> incidents
                    </span>
                    <span>
                      {suggestion.primary_city ? `${suggestion.primary_city}, ` : ''}{suggestion.primary_state}
                    </span>
                    <span>
                      {suggestion.start_date === suggestion.end_date
                        ? suggestion.start_date
                        : `${suggestion.start_date} → ${suggestion.end_date}`}
                    </span>
                  </div>
                  {suggestion.reasoning && suggestion.reasoning.length > 0 && (
                    <div className="ext-suggestion-reasoning-list">
                      {suggestion.reasoning.map((reason, i) => (
                        <span key={i} className="ext-reason-chip">{reason}</span>
                      ))}
                    </div>
                  )}
                  <div className="ext-suggestion-action-row">
                    <button
                      className="ext-btn ext-btn-primary"
                      onClick={() => handleApplySuggestion(suggestion)}
                      disabled={saving}
                    >
                      Create Event
                    </button>
                  </div>
                </div>
              ))}
              {suggestions.length === 0 && (
                <p className="ext-empty-state">No cluster suggestions found. Try adjusting the clustering settings or check that there are unlinked incidents.</p>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Incident Detail Modal */}
      {showIncidentDetail && selectedIncident && (
        <div className="ext-modal-overlay" onClick={() => setShowIncidentDetail(false)}>
          <div className="ext-modal ext-modal-wide" onClick={(e) => e.stopPropagation()}>
            <div className="ext-modal-header">
              <h3>Incident Details</h3>
              <button className="ext-close-btn" onClick={() => setShowIncidentDetail(false)} aria-label="Close incident details">&times;</button>
            </div>
            <div className="ext-modal-body">
              <IncidentDetailView
                incident={selectedIncident}
                showSource={true}
                onClose={() => setShowIncidentDetail(false)}
              />
            </div>
          </div>
        </div>
      )}

    </div>
  );
}

export default EventBrowser;
