import React, { useState, useEffect, useCallback } from 'react';
import type { Actor, ActorType, ActorRole, ActorMergeSuggestion } from './types';

const API_BASE = '';

const ACTOR_TYPE_LABELS: Record<ActorType, string> = {
  person: 'Person',
  organization: 'Organization',
  agency: 'Agency',
  group: 'Group',
};

const ACTOR_ROLE_LABELS: Record<ActorRole, string> = {
  victim: 'Victim',
  offender: 'Offender',
  witness: 'Witness',
  officer: 'Officer',
  arresting_agency: 'Arresting Agency',
  reporting_agency: 'Reporting Agency',
  bystander: 'Bystander',
  organizer: 'Organizer',
  participant: 'Participant',
};

export const ActorBrowser: React.FC = () => {
  const [actors, setActors] = useState<Actor[]>([]);
  const [selectedActor, setSelectedActor] = useState<Actor | null>(null);
  const [mergeSuggestions, setMergeSuggestions] = useState<ActorMergeSuggestion[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Filters
  const [searchQuery, setSearchQuery] = useState('');
  const [typeFilter, setTypeFilter] = useState<ActorType | ''>('');
  const [roleFilter, setRoleFilter] = useState<ActorRole | ''>('');

  // Modal states
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [showMergeSuggestionsModal, setShowMergeSuggestionsModal] = useState(false);
  const [showRelationModal, setShowRelationModal] = useState(false);

  // Form states
  const [newActor, setNewActor] = useState<Partial<Actor>>({
    canonical_name: '',
    actor_type: 'person',
    aliases: [],
    prior_deportations: 0,
    is_government_entity: false,
    is_law_enforcement: false,
  });
  const [newAlias, setNewAlias] = useState('');

  const fetchActors = useCallback(async () => {
    try {
      setLoading(true);
      const params = new URLSearchParams();
      if (searchQuery) params.append('search', searchQuery);
      if (typeFilter) params.append('actor_type', typeFilter);
      if (roleFilter) params.append('role', roleFilter);

      const response = await fetch(`${API_BASE}/api/actors?${params}`);
      if (!response.ok) throw new Error('Failed to fetch actors');
      const data = await response.json();
      setActors(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
    } finally {
      setLoading(false);
    }
  }, [searchQuery, typeFilter, roleFilter]);

  const fetchActorDetails = useCallback(async (actorId: string) => {
    try {
      const response = await fetch(`${API_BASE}/api/actors/${actorId}`);
      if (!response.ok) throw new Error('Failed to fetch actor details');
      const data = await response.json();
      setSelectedActor(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
    }
  }, []);

  const fetchMergeSuggestions = useCallback(async () => {
    try {
      const response = await fetch(`${API_BASE}/api/actors/merge-suggestions`);
      if (!response.ok) throw new Error('Failed to fetch merge suggestions');
      const data = await response.json();
      setMergeSuggestions(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
    }
  }, []);

  useEffect(() => {
    fetchActors();
  }, [fetchActors]);

  const handleCreateActor = async () => {
    try {
      const response = await fetch(`${API_BASE}/api/actors`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(newActor),
      });
      if (!response.ok) throw new Error('Failed to create actor');
      setShowCreateModal(false);
      setNewActor({
        canonical_name: '',
        actor_type: 'person',
        aliases: [],
        prior_deportations: 0,
        is_government_entity: false,
        is_law_enforcement: false,
      });
      fetchActors();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
    }
  };

  const handleMergeActors = async (actor1Id: string, actor2Id: string) => {
    try {
      const response = await fetch(`${API_BASE}/api/actors/merge`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          primary_actor_id: actor1Id,
          secondary_actor_id: actor2Id,
        }),
      });
      if (!response.ok) throw new Error('Failed to merge actors');
      setShowMergeSuggestionsModal(false);
      fetchActors();
      fetchMergeSuggestions();
      if (selectedActor && (selectedActor.id === actor1Id || selectedActor.id === actor2Id)) {
        fetchActorDetails(actor1Id);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
    }
  };

  const handleDeleteActor = async (actorId: string) => {
    if (!confirm('Are you sure you want to delete this actor?')) return;
    try {
      const response = await fetch(`${API_BASE}/api/actors/${actorId}`, {
        method: 'DELETE',
      });
      if (!response.ok) throw new Error('Failed to delete actor');
      if (selectedActor?.id === actorId) {
        setSelectedActor(null);
      }
      fetchActors();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
    }
  };

  const addAlias = () => {
    if (newAlias.trim()) {
      setNewActor({
        ...newActor,
        aliases: [...(newActor.aliases || []), newAlias.trim()],
      });
      setNewAlias('');
    }
  };

  const removeAlias = (alias: string) => {
    setNewActor({
      ...newActor,
      aliases: (newActor.aliases || []).filter((a) => a !== alias),
    });
  };

  const renderActorTypeIcon = (type: ActorType) => {
    const icons: Record<ActorType, string> = {
      person: '👤',
      organization: '🏢',
      agency: '🏛️',
      group: '👥',
    };
    return icons[type] || '❓';
  };

  const renderActorList = () => (
    <div className="actor-list">
      <div className="list-header">
        <h3>Actors ({actors.length})</h3>
        <div className="header-actions">
          <button className="btn btn-secondary" onClick={() => {
            fetchMergeSuggestions();
            setShowMergeSuggestionsModal(true);
          }}>
            Merge Suggestions
          </button>
          <button className="btn btn-primary" onClick={() => setShowCreateModal(true)}>
            + New Actor
          </button>
        </div>
      </div>

      <div className="filters">
        <input
          type="text"
          placeholder="Search actors..."
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          className="search-input"
        />
        <select
          value={typeFilter}
          onChange={(e) => setTypeFilter(e.target.value as ActorType | '')}
          className="filter-select"
        >
          <option value="">All Types</option>
          {Object.entries(ACTOR_TYPE_LABELS).map(([value, label]) => (
            <option key={value} value={value}>{label}</option>
          ))}
        </select>
        <select
          value={roleFilter}
          onChange={(e) => setRoleFilter(e.target.value as ActorRole | '')}
          className="filter-select"
        >
          <option value="">All Roles</option>
          {Object.entries(ACTOR_ROLE_LABELS).map(([value, label]) => (
            <option key={value} value={value}>{label}</option>
          ))}
        </select>
      </div>

      <div className="actor-items">
        {actors.map((actor) => (
          <div
            key={actor.id}
            className={`actor-item ${selectedActor?.id === actor.id ? 'selected' : ''}`}
            onClick={() => fetchActorDetails(actor.id)}
          >
            <div className="actor-icon">{renderActorTypeIcon(actor.actor_type)}</div>
            <div className="actor-info">
              <div className="actor-name">{actor.canonical_name}</div>
              <div className="actor-meta">
                <span className="type-badge">{ACTOR_TYPE_LABELS[actor.actor_type]}</span>
                {actor.is_law_enforcement && <span className="badge badge-blue">Law Enforcement</span>}
                {actor.is_government_entity && <span className="badge badge-purple">Government</span>}
                <span className="incident-count">{actor.incident_count} incidents</span>
              </div>
              {actor.aliases && actor.aliases.length > 0 && (
                <div className="aliases">
                  AKA: {actor.aliases.slice(0, 3).join(', ')}
                  {actor.aliases.length > 3 && ` +${actor.aliases.length - 3} more`}
                </div>
              )}
            </div>
          </div>
        ))}
        {actors.length === 0 && !loading && (
          <div className="empty-state">No actors found</div>
        )}
      </div>
    </div>
  );

  const renderActorDetail = () => {
    if (!selectedActor) {
      return (
        <div className="actor-detail empty">
          <p>Select an actor to view details</p>
        </div>
      );
    }

    return (
      <div className="actor-detail">
        <div className="detail-header">
          <div className="header-title">
            <span className="detail-icon">{renderActorTypeIcon(selectedActor.actor_type)}</span>
            <h2>{selectedActor.canonical_name}</h2>
          </div>
          <div className="header-actions">
            <button className="btn btn-danger" onClick={() => handleDeleteActor(selectedActor.id)}>
              Delete
            </button>
          </div>
        </div>

        <div className="detail-content">
          {/* Basic Info */}
          <section className="detail-section">
            <h3>Basic Information</h3>
            <div className="info-grid">
              <div className="info-item">
                <label>Type</label>
                <span>{ACTOR_TYPE_LABELS[selectedActor.actor_type]}</span>
              </div>
              {selectedActor.gender && (
                <div className="info-item">
                  <label>Gender</label>
                  <span>{selectedActor.gender}</span>
                </div>
              )}
              {selectedActor.nationality && (
                <div className="info-item">
                  <label>Nationality</label>
                  <span>{selectedActor.nationality}</span>
                </div>
              )}
              {selectedActor.immigration_status && (
                <div className="info-item">
                  <label>Immigration Status</label>
                  <span>{selectedActor.immigration_status}</span>
                </div>
              )}
              {selectedActor.prior_deportations > 0 && (
                <div className="info-item">
                  <label>Prior Deportations</label>
                  <span>{selectedActor.prior_deportations}</span>
                </div>
              )}
              {selectedActor.date_of_birth && (
                <div className="info-item">
                  <label>Date of Birth</label>
                  <span>{selectedActor.date_of_birth}</span>
                </div>
              )}
              {selectedActor.date_of_death && (
                <div className="info-item">
                  <label>Date of Death</label>
                  <span>{selectedActor.date_of_death}</span>
                </div>
              )}
              {selectedActor.organization_type && (
                <div className="info-item">
                  <label>Organization Type</label>
                  <span>{selectedActor.organization_type}</span>
                </div>
              )}
              {selectedActor.jurisdiction && (
                <div className="info-item">
                  <label>Jurisdiction</label>
                  <span>{selectedActor.jurisdiction}</span>
                </div>
              )}
              <div className="info-item">
                <label>Government Entity</label>
                <span>{selectedActor.is_government_entity ? 'Yes' : 'No'}</span>
              </div>
              <div className="info-item">
                <label>Law Enforcement</label>
                <span>{selectedActor.is_law_enforcement ? 'Yes' : 'No'}</span>
              </div>
              {selectedActor.confidence_score && (
                <div className="info-item">
                  <label>Confidence</label>
                  <span>{Math.round(selectedActor.confidence_score * 100)}%</span>
                </div>
              )}
            </div>
          </section>

          {/* Aliases */}
          {selectedActor.aliases && selectedActor.aliases.length > 0 && (
            <section className="detail-section">
              <h3>Aliases</h3>
              <div className="alias-list">
                {selectedActor.aliases.map((alias, idx) => (
                  <span key={idx} className="alias-tag">{alias}</span>
                ))}
              </div>
            </section>
          )}

          {/* Description */}
          {selectedActor.description && (
            <section className="detail-section">
              <h3>Description</h3>
              <p>{selectedActor.description}</p>
            </section>
          )}

          {/* Roles Played */}
          {selectedActor.roles_played && selectedActor.roles_played.length > 0 && (
            <section className="detail-section">
              <h3>Roles</h3>
              <div className="role-list">
                {selectedActor.roles_played.map((role, idx) => (
                  <span key={idx} className="role-tag">
                    {ACTOR_ROLE_LABELS[role as ActorRole] || role}
                  </span>
                ))}
              </div>
            </section>
          )}

          {/* Relations */}
          {selectedActor.relations && selectedActor.relations.length > 0 && (
            <section className="detail-section">
              <h3>Relationships</h3>
              <div className="relations-list">
                {selectedActor.relations.map((relation) => (
                  <div key={relation.id} className="relation-item">
                    <span className="relation-type">{relation.relation_type.replace('_', ' ')}</span>
                    <span className="related-actor">{relation.related_actor_id}</span>
                    {relation.confidence && (
                      <span className="confidence">{Math.round(relation.confidence * 100)}%</span>
                    )}
                  </div>
                ))}
              </div>
              <button className="btn btn-secondary btn-sm" onClick={() => setShowRelationModal(true)}>
                + Add Relationship
              </button>
            </section>
          )}

          {/* Incidents */}
          {selectedActor.incidents && selectedActor.incidents.length > 0 && (
            <section className="detail-section">
              <h3>Linked Incidents ({selectedActor.incident_count})</h3>
              <div className="incident-list">
                {selectedActor.incidents.map((incident) => (
                  <div key={incident.incident_id} className="incident-item">
                    <div className="incident-header">
                      <span className="incident-date">{incident.date || 'Unknown date'}</span>
                      <span className="incident-role">{ACTOR_ROLE_LABELS[incident.role]}</span>
                    </div>
                    <div className="incident-location">
                      {incident.city && `${incident.city}, `}{incident.state}
                    </div>
                    {incident.incident_type && (
                      <div className="incident-type">{incident.incident_type}</div>
                    )}
                    {incident.description && (
                      <div className="incident-description">{incident.description}</div>
                    )}
                  </div>
                ))}
              </div>
            </section>
          )}
        </div>
      </div>
    );
  };

  const renderCreateModal = () => (
    <div className="modal-overlay" onClick={() => setShowCreateModal(false)}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h3>Create New Actor</h3>
          <button className="close-btn" onClick={() => setShowCreateModal(false)}>×</button>
        </div>
        <div className="modal-body">
          <div className="form-group">
            <label>Name *</label>
            <input
              type="text"
              value={newActor.canonical_name || ''}
              onChange={(e) => setNewActor({ ...newActor, canonical_name: e.target.value })}
              placeholder="Enter actor name"
            />
          </div>

          <div className="form-group">
            <label>Type *</label>
            <select
              value={newActor.actor_type || 'person'}
              onChange={(e) => setNewActor({ ...newActor, actor_type: e.target.value as ActorType })}
            >
              {Object.entries(ACTOR_TYPE_LABELS).map(([value, label]) => (
                <option key={value} value={value}>{label}</option>
              ))}
            </select>
          </div>

          <div className="form-group">
            <label>Aliases</label>
            <div className="alias-input">
              <input
                type="text"
                value={newAlias}
                onChange={(e) => setNewAlias(e.target.value)}
                placeholder="Add alias"
                onKeyPress={(e) => e.key === 'Enter' && (e.preventDefault(), addAlias())}
              />
              <button type="button" onClick={addAlias}>Add</button>
            </div>
            <div className="alias-list">
              {(newActor.aliases || []).map((alias, idx) => (
                <span key={idx} className="alias-tag">
                  {alias}
                  <button type="button" onClick={() => removeAlias(alias)}>×</button>
                </span>
              ))}
            </div>
          </div>

          {newActor.actor_type === 'person' && (
            <>
              <div className="form-row">
                <div className="form-group">
                  <label>Gender</label>
                  <select
                    value={newActor.gender || ''}
                    onChange={(e) => setNewActor({ ...newActor, gender: e.target.value })}
                  >
                    <option value="">Select...</option>
                    <option value="male">Male</option>
                    <option value="female">Female</option>
                    <option value="other">Other</option>
                  </select>
                </div>
                <div className="form-group">
                  <label>Nationality</label>
                  <input
                    type="text"
                    value={newActor.nationality || ''}
                    onChange={(e) => setNewActor({ ...newActor, nationality: e.target.value })}
                    placeholder="Country"
                  />
                </div>
              </div>

              <div className="form-row">
                <div className="form-group">
                  <label>Immigration Status</label>
                  <input
                    type="text"
                    value={newActor.immigration_status || ''}
                    onChange={(e) => setNewActor({ ...newActor, immigration_status: e.target.value })}
                    placeholder="Status"
                  />
                </div>
                <div className="form-group">
                  <label>Prior Deportations</label>
                  <input
                    type="number"
                    min="0"
                    value={newActor.prior_deportations || 0}
                    onChange={(e) => setNewActor({ ...newActor, prior_deportations: parseInt(e.target.value) || 0 })}
                  />
                </div>
              </div>
            </>
          )}

          {(newActor.actor_type === 'organization' || newActor.actor_type === 'agency') && (
            <>
              <div className="form-group">
                <label>Organization Type</label>
                <input
                  type="text"
                  value={newActor.organization_type || ''}
                  onChange={(e) => setNewActor({ ...newActor, organization_type: e.target.value })}
                  placeholder="e.g., Law Enforcement, NGO, etc."
                />
              </div>

              <div className="form-group">
                <label>Jurisdiction</label>
                <input
                  type="text"
                  value={newActor.jurisdiction || ''}
                  onChange={(e) => setNewActor({ ...newActor, jurisdiction: e.target.value })}
                  placeholder="Geographic area of authority"
                />
              </div>

              <div className="form-row checkbox-row">
                <label className="checkbox-label">
                  <input
                    type="checkbox"
                    checked={newActor.is_government_entity || false}
                    onChange={(e) => setNewActor({ ...newActor, is_government_entity: e.target.checked })}
                  />
                  Government Entity
                </label>
                <label className="checkbox-label">
                  <input
                    type="checkbox"
                    checked={newActor.is_law_enforcement || false}
                    onChange={(e) => setNewActor({ ...newActor, is_law_enforcement: e.target.checked })}
                  />
                  Law Enforcement
                </label>
              </div>
            </>
          )}

          <div className="form-group">
            <label>Description</label>
            <textarea
              value={newActor.description || ''}
              onChange={(e) => setNewActor({ ...newActor, description: e.target.value })}
              placeholder="Additional notes about this actor"
              rows={3}
            />
          </div>
        </div>
        <div className="modal-footer">
          <button className="btn btn-secondary" onClick={() => setShowCreateModal(false)}>
            Cancel
          </button>
          <button
            className="btn btn-primary"
            onClick={handleCreateActor}
            disabled={!newActor.canonical_name}
          >
            Create Actor
          </button>
        </div>
      </div>
    </div>
  );

  const renderMergeSuggestionsModal = () => (
    <div className="modal-overlay" onClick={() => setShowMergeSuggestionsModal(false)}>
      <div className="modal modal-lg" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h3>Merge Suggestions</h3>
          <button className="close-btn" onClick={() => setShowMergeSuggestionsModal(false)}>×</button>
        </div>
        <div className="modal-body">
          {mergeSuggestions.length === 0 ? (
            <div className="empty-state">No merge suggestions available</div>
          ) : (
            <div className="merge-suggestions">
              {mergeSuggestions.map((suggestion, idx) => (
                <div key={idx} className="merge-suggestion">
                  <div className="suggestion-actors">
                    <div className="actor-card">
                      <strong>{suggestion.actor1_name}</strong>
                    </div>
                    <div className="merge-arrow">↔</div>
                    <div className="actor-card">
                      <strong>{suggestion.actor2_name}</strong>
                    </div>
                  </div>
                  <div className="suggestion-meta">
                    <span className="similarity">
                      {Math.round(suggestion.similarity * 100)}% similar
                    </span>
                    <span className="reason">{suggestion.reason}</span>
                  </div>
                  <div className="suggestion-actions">
                    <button
                      className="btn btn-sm btn-primary"
                      onClick={() => handleMergeActors(suggestion.actor1_id, suggestion.actor2_id)}
                    >
                      Merge (Keep First)
                    </button>
                    <button
                      className="btn btn-sm btn-secondary"
                      onClick={() => handleMergeActors(suggestion.actor2_id, suggestion.actor1_id)}
                    >
                      Merge (Keep Second)
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
        <div className="modal-footer">
          <button className="btn btn-secondary" onClick={() => setShowMergeSuggestionsModal(false)}>
            Close
          </button>
        </div>
      </div>
    </div>
  );

  return (
    <div className="actor-browser">
      <style>{`
        .actor-browser {
          display: flex;
          height: 100%;
          gap: 1rem;
        }

        .actor-list {
          width: 400px;
          min-width: 350px;
          display: flex;
          flex-direction: column;
          border-right: 1px solid #e2e8f0;
          padding-right: 1rem;
        }

        .list-header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          margin-bottom: 1rem;
        }

        .list-header h3 {
          margin: 0;
          font-size: 1.1rem;
        }

        .header-actions {
          display: flex;
          gap: 0.5rem;
        }

        .filters {
          display: flex;
          flex-direction: column;
          gap: 0.5rem;
          margin-bottom: 1rem;
        }

        .search-input, .filter-select {
          padding: 0.5rem;
          border: 1px solid #e2e8f0;
          border-radius: 4px;
          font-size: 0.875rem;
        }

        .actor-items {
          flex: 1;
          overflow-y: auto;
        }

        .actor-item {
          display: flex;
          gap: 0.75rem;
          padding: 0.75rem;
          border: 1px solid #e2e8f0;
          border-radius: 6px;
          margin-bottom: 0.5rem;
          cursor: pointer;
          transition: all 0.15s;
        }

        .actor-item:hover {
          border-color: #3b82f6;
          background: #f8fafc;
        }

        .actor-item.selected {
          border-color: #3b82f6;
          background: #eff6ff;
        }

        .actor-icon {
          font-size: 1.5rem;
        }

        .actor-info {
          flex: 1;
          min-width: 0;
        }

        .actor-name {
          font-weight: 600;
          margin-bottom: 0.25rem;
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
        }

        .actor-meta {
          display: flex;
          gap: 0.5rem;
          flex-wrap: wrap;
          font-size: 0.75rem;
        }

        .type-badge {
          background: #e2e8f0;
          padding: 0.125rem 0.5rem;
          border-radius: 4px;
        }

        .badge {
          padding: 0.125rem 0.5rem;
          border-radius: 4px;
          font-size: 0.7rem;
        }

        .badge-blue {
          background: #dbeafe;
          color: #1e40af;
        }

        .badge-purple {
          background: #ede9fe;
          color: #6b21a8;
        }

        .incident-count {
          color: #64748b;
        }

        .aliases {
          font-size: 0.75rem;
          color: #64748b;
          margin-top: 0.25rem;
          font-style: italic;
        }

        .actor-detail {
          flex: 1;
          overflow-y: auto;
          padding: 0 1rem;
        }

        .actor-detail.empty {
          display: flex;
          align-items: center;
          justify-content: center;
          color: #64748b;
        }

        .detail-header {
          display: flex;
          justify-content: space-between;
          align-items: flex-start;
          margin-bottom: 1.5rem;
          padding-bottom: 1rem;
          border-bottom: 1px solid #e2e8f0;
        }

        .header-title {
          display: flex;
          align-items: center;
          gap: 0.75rem;
        }

        .detail-icon {
          font-size: 2rem;
        }

        .detail-header h2 {
          margin: 0;
          font-size: 1.5rem;
        }

        .detail-section {
          margin-bottom: 1.5rem;
        }

        .detail-section h3 {
          font-size: 0.9rem;
          text-transform: uppercase;
          letter-spacing: 0.05em;
          color: #64748b;
          margin-bottom: 0.75rem;
          padding-bottom: 0.5rem;
          border-bottom: 1px solid #e2e8f0;
        }

        .info-grid {
          display: grid;
          grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
          gap: 1rem;
        }

        .info-item {
          display: flex;
          flex-direction: column;
          gap: 0.25rem;
        }

        .info-item label {
          font-size: 0.75rem;
          color: #64748b;
          text-transform: uppercase;
        }

        .info-item span {
          font-weight: 500;
        }

        .alias-list, .role-list {
          display: flex;
          flex-wrap: wrap;
          gap: 0.5rem;
        }

        .alias-tag, .role-tag {
          background: #e2e8f0;
          padding: 0.25rem 0.75rem;
          border-radius: 999px;
          font-size: 0.875rem;
        }

        .relations-list {
          display: flex;
          flex-direction: column;
          gap: 0.5rem;
          margin-bottom: 0.75rem;
        }

        .relation-item {
          display: flex;
          align-items: center;
          gap: 0.75rem;
          padding: 0.5rem;
          background: #f8fafc;
          border-radius: 4px;
        }

        .relation-type {
          text-transform: capitalize;
          font-weight: 500;
        }

        .related-actor {
          color: #3b82f6;
        }

        .confidence {
          margin-left: auto;
          color: #64748b;
          font-size: 0.875rem;
        }

        .incident-list {
          display: flex;
          flex-direction: column;
          gap: 0.75rem;
        }

        .incident-item {
          padding: 0.75rem;
          background: #f8fafc;
          border-radius: 6px;
          border-left: 3px solid #3b82f6;
        }

        .incident-header {
          display: flex;
          justify-content: space-between;
          margin-bottom: 0.25rem;
        }

        .incident-date {
          font-weight: 500;
        }

        .incident-role {
          background: #dbeafe;
          color: #1e40af;
          padding: 0.125rem 0.5rem;
          border-radius: 4px;
          font-size: 0.75rem;
        }

        .incident-location {
          color: #64748b;
          font-size: 0.875rem;
        }

        .incident-type {
          margin-top: 0.25rem;
          font-size: 0.875rem;
        }

        .incident-description {
          margin-top: 0.5rem;
          font-size: 0.875rem;
          color: #475569;
        }

        /* Modals */
        .modal-overlay {
          position: fixed;
          top: 0;
          left: 0;
          right: 0;
          bottom: 0;
          background: rgba(0, 0, 0, 0.5);
          display: flex;
          align-items: center;
          justify-content: center;
          z-index: 1000;
        }

        .modal {
          background: white;
          border-radius: 8px;
          width: 90%;
          max-width: 500px;
          max-height: 90vh;
          overflow: hidden;
          display: flex;
          flex-direction: column;
        }

        .modal-lg {
          max-width: 700px;
        }

        .modal-header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          padding: 1rem;
          border-bottom: 1px solid #e2e8f0;
        }

        .modal-header h3 {
          margin: 0;
        }

        .close-btn {
          background: none;
          border: none;
          font-size: 1.5rem;
          cursor: pointer;
          color: #64748b;
        }

        .modal-body {
          padding: 1rem;
          overflow-y: auto;
          flex: 1;
        }

        .modal-footer {
          display: flex;
          justify-content: flex-end;
          gap: 0.5rem;
          padding: 1rem;
          border-top: 1px solid #e2e8f0;
        }

        .form-group {
          margin-bottom: 1rem;
        }

        .form-group label {
          display: block;
          margin-bottom: 0.25rem;
          font-weight: 500;
          font-size: 0.875rem;
        }

        .form-group input,
        .form-group select,
        .form-group textarea {
          width: 100%;
          padding: 0.5rem;
          border: 1px solid #e2e8f0;
          border-radius: 4px;
          font-size: 0.875rem;
        }

        .form-row {
          display: flex;
          gap: 1rem;
        }

        .form-row .form-group {
          flex: 1;
        }

        .checkbox-row {
          margin-bottom: 1rem;
        }

        .checkbox-label {
          display: flex;
          align-items: center;
          gap: 0.5rem;
          cursor: pointer;
        }

        .checkbox-label input[type="checkbox"] {
          width: auto;
        }

        .alias-input {
          display: flex;
          gap: 0.5rem;
        }

        .alias-input input {
          flex: 1;
        }

        .alias-tag button {
          background: none;
          border: none;
          margin-left: 0.25rem;
          cursor: pointer;
          color: #64748b;
        }

        /* Merge suggestions */
        .merge-suggestions {
          display: flex;
          flex-direction: column;
          gap: 1rem;
        }

        .merge-suggestion {
          padding: 1rem;
          border: 1px solid #e2e8f0;
          border-radius: 8px;
        }

        .suggestion-actors {
          display: flex;
          align-items: center;
          justify-content: center;
          gap: 1rem;
          margin-bottom: 0.75rem;
        }

        .actor-card {
          padding: 0.5rem 1rem;
          background: #f8fafc;
          border-radius: 6px;
        }

        .merge-arrow {
          font-size: 1.25rem;
          color: #64748b;
        }

        .suggestion-meta {
          display: flex;
          justify-content: center;
          gap: 1rem;
          margin-bottom: 0.75rem;
          font-size: 0.875rem;
        }

        .similarity {
          font-weight: 500;
          color: #059669;
        }

        .reason {
          color: #64748b;
        }

        .suggestion-actions {
          display: flex;
          justify-content: center;
          gap: 0.5rem;
        }

        /* Buttons */
        .btn {
          padding: 0.5rem 1rem;
          border: none;
          border-radius: 4px;
          cursor: pointer;
          font-size: 0.875rem;
          font-weight: 500;
          transition: all 0.15s;
        }

        .btn-sm {
          padding: 0.25rem 0.75rem;
          font-size: 0.8rem;
        }

        .btn-primary {
          background: #3b82f6;
          color: white;
        }

        .btn-primary:hover {
          background: #2563eb;
        }

        .btn-primary:disabled {
          background: #93c5fd;
          cursor: not-allowed;
        }

        .btn-secondary {
          background: #e2e8f0;
          color: #475569;
        }

        .btn-secondary:hover {
          background: #cbd5e1;
        }

        .btn-danger {
          background: #ef4444;
          color: white;
        }

        .btn-danger:hover {
          background: #dc2626;
        }

        .empty-state {
          text-align: center;
          padding: 2rem;
          color: #64748b;
        }
      `}</style>

      {loading && <div className="loading">Loading...</div>}
      {error && <div className="error">{error}</div>}

      {renderActorList()}
      {renderActorDetail()}

      {showCreateModal && renderCreateModal()}
      {showMergeSuggestionsModal && renderMergeSuggestionsModal()}
      {showRelationModal && (
        <div className="modal-overlay" onClick={() => setShowRelationModal(false)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h3>Add Relationship</h3>
              <button className="close-btn" onClick={() => setShowRelationModal(false)}>×</button>
            </div>
            <div className="modal-body">
              <p>Relationship management coming soon.</p>
            </div>
            <div className="modal-footer">
              <button className="btn btn-secondary" onClick={() => setShowRelationModal(false)}>
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default ActorBrowser;
