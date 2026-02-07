import React, { useState, useEffect, useCallback } from 'react';
import type { Actor, ActorType, ActorRole, ActorMergeSuggestion } from './types';
import './ExtensibleSystem.css';

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

interface SimilarActor {
  id: string;
  canonical_name: string;
  similarity: number;
}

export const ActorBrowser: React.FC = () => {
  const [actors, setActors] = useState<Actor[]>([]);
  const [selectedActor, setSelectedActor] = useState<Actor | null>(null);
  const [mergeSuggestions, setMergeSuggestions] = useState<ActorMergeSuggestion[]>([]);
  const [similarActors, setSimilarActors] = useState<SimilarActor[]>([]);
  const [suggestionCount, setSuggestionCount] = useState(0);
  const [loading, setLoading] = useState(true);
  const [loadingSimilar, setLoadingSimilar] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [mergeSuccess, setMergeSuccess] = useState<string | null>(null);

  // Filters
  const [searchQuery, setSearchQuery] = useState('');
  const [typeFilter, setTypeFilter] = useState<ActorType | ''>('');
  const [roleFilter, setRoleFilter] = useState<ActorRole | ''>('');

  // Modal states
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [showMergeSuggestionsModal, setShowMergeSuggestionsModal] = useState(false);
  const [showRelationModal, setShowRelationModal] = useState(false);
  const [showSimilarModal, setShowSimilarModal] = useState(false);

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
      setSuggestionCount(data.length);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
    }
  }, []);

  const fetchSimilarActors = useCallback(async (actorId: string) => {
    try {
      setLoadingSimilar(true);
      const response = await fetch(`${API_BASE}/api/actors/${actorId}/similar`);
      if (!response.ok) throw new Error('Failed to fetch similar actors');
      const data = await response.json();
      setSimilarActors(data);
      setShowSimilarModal(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
    } finally {
      setLoadingSimilar(false);
    }
  }, []);

  useEffect(() => {
    fetchActors();
    // Load suggestion count on mount
    fetch(`${API_BASE}/api/actors/merge-suggestions?limit=100`)
      .then(res => res.json())
      .then(data => setSuggestionCount(data.length))
      .catch(() => {});
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

  const handleMergeActors = async (actor1Id: string, actor2Id: string, keepFirst: boolean = true) => {
    const primaryId = keepFirst ? actor1Id : actor2Id;
    const secondaryId = keepFirst ? actor2Id : actor1Id;

    try {
      const response = await fetch(`${API_BASE}/api/actors/merge`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          primary_actor_id: primaryId,
          secondary_actor_id: secondaryId,
        }),
      });
      if (!response.ok) throw new Error('Failed to merge actors');

      // Get the name of the merged actor for feedback
      const result = await response.json();
      setMergeSuccess(`Merged successfully into "${result.canonical_name}"`);
      setTimeout(() => setMergeSuccess(null), 3000);

      // Immediately remove suggestions involving the merged-away actor
      setMergeSuggestions(prev => prev.filter(
        s => s.actor1_id !== secondaryId && s.actor2_id !== secondaryId
      ));

      setShowSimilarModal(false);
      fetchActors();
      // Re-fetch suggestions in background for accuracy (modal stays open)
      fetchMergeSuggestions();
      if (selectedActor && (selectedActor.id === actor1Id || selectedActor.id === actor2Id)) {
        fetchActorDetails(primaryId);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
    }
  };

  const handleQuickMerge = async (similarActorId: string) => {
    if (!selectedActor) return;
    await handleMergeActors(selectedActor.id, similarActorId, true);
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
    <div className="ext-list">
      <div className="ext-list-header">
        <h3>Actors ({actors.length})</h3>
        <div className="ext-header-actions">
          <button
            className={`ext-btn ${suggestionCount > 0 ? 'ext-btn-warning' : 'ext-btn-secondary'}`}
            onClick={() => {
              fetchMergeSuggestions();
              setShowMergeSuggestionsModal(true);
            }}
          >
            Merge Suggestions
            {suggestionCount > 0 && <span className="ext-count-badge">{suggestionCount}</span>}
          </button>
          <button className="ext-btn ext-btn-primary" onClick={() => setShowCreateModal(true)}>
            + New Actor
          </button>
        </div>
      </div>

      <div className="ext-filters">
        <input
          type="text"
          placeholder="Search actors..."
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          className="ext-search-input"
        />
        <select
          value={typeFilter}
          onChange={(e) => setTypeFilter(e.target.value as ActorType | '')}
          className="ext-filter-select"
        >
          <option value="">All Types</option>
          {Object.entries(ACTOR_TYPE_LABELS).map(([value, label]) => (
            <option key={value} value={value}>{label}</option>
          ))}
        </select>
        <select
          value={roleFilter}
          onChange={(e) => setRoleFilter(e.target.value as ActorRole | '')}
          className="ext-filter-select"
        >
          <option value="">All Roles</option>
          {Object.entries(ACTOR_ROLE_LABELS).map(([value, label]) => (
            <option key={value} value={value}>{label}</option>
          ))}
        </select>
      </div>

      <div className="ext-items">
        {actors.map((actor) => (
          <div
            key={actor.id}
            className={`ext-item ${selectedActor?.id === actor.id ? 'selected' : ''}`}
            onClick={() => fetchActorDetails(actor.id)}
          >
            <div className="ext-item-icon">{renderActorTypeIcon(actor.actor_type)}</div>
            <div className="ext-item-info">
              <div className="ext-item-name">{actor.canonical_name}</div>
              <div className="ext-item-meta">
                <span className="ext-type-badge">{ACTOR_TYPE_LABELS[actor.actor_type]}</span>
                {actor.is_law_enforcement && <span className="ext-badge ext-badge-blue">Law Enforcement</span>}
                {actor.is_government_entity && <span className="ext-badge ext-badge-purple">Government</span>}
                <span className="ext-incident-count">{actor.incident_count} incidents</span>
              </div>
              {actor.aliases && actor.aliases.length > 0 && (
                <div className="ext-item-secondary">
                  AKA: {actor.aliases.slice(0, 3).join(', ')}
                  {actor.aliases.length > 3 && ` +${actor.aliases.length - 3} more`}
                </div>
              )}
            </div>
          </div>
        ))}
        {actors.length === 0 && !loading && (
          <div className="ext-empty-state">No actors found</div>
        )}
      </div>
    </div>
  );

  const renderActorDetail = () => {
    if (!selectedActor) {
      return (
        <div className="ext-detail empty">
          <p>Select an actor to view details</p>
        </div>
      );
    }

    return (
      <div className="ext-detail">
        <div className="ext-detail-header">
          <div className="ext-header-title">
            <span className="ext-detail-icon">{renderActorTypeIcon(selectedActor.actor_type)}</span>
            <h2>{selectedActor.canonical_name}</h2>
          </div>
          <div className="ext-header-actions">
            <button
              className="ext-btn ext-btn-secondary"
              onClick={() => fetchSimilarActors(selectedActor.id)}
              disabled={loadingSimilar}
            >
              {loadingSimilar ? 'Finding...' : 'Find Similar'}
            </button>
            <button className="ext-btn ext-btn-danger" onClick={() => handleDeleteActor(selectedActor.id)}>
              Delete
            </button>
          </div>
        </div>

        <div className="ext-detail-content">
          {/* Basic Info */}
          <section className="ext-section">
            <h3>Basic Information</h3>
            <div className="ext-info-grid">
              <div className="ext-info-item">
                <label>Type</label>
                <span>{ACTOR_TYPE_LABELS[selectedActor.actor_type]}</span>
              </div>
              {selectedActor.gender && (
                <div className="ext-info-item">
                  <label>Gender</label>
                  <span>{selectedActor.gender}</span>
                </div>
              )}
              {selectedActor.nationality && (
                <div className="ext-info-item">
                  <label>Nationality</label>
                  <span>{selectedActor.nationality}</span>
                </div>
              )}
              {selectedActor.immigration_status && (
                <div className="ext-info-item">
                  <label>Immigration Status</label>
                  <span>{selectedActor.immigration_status}</span>
                </div>
              )}
              {selectedActor.prior_deportations > 0 && (
                <div className="ext-info-item">
                  <label>Prior Deportations</label>
                  <span>{selectedActor.prior_deportations}</span>
                </div>
              )}
              {selectedActor.date_of_birth && (
                <div className="ext-info-item">
                  <label>Date of Birth</label>
                  <span>{selectedActor.date_of_birth}</span>
                </div>
              )}
              {selectedActor.date_of_death && (
                <div className="ext-info-item">
                  <label>Date of Death</label>
                  <span>{selectedActor.date_of_death}</span>
                </div>
              )}
              {selectedActor.organization_type && (
                <div className="ext-info-item">
                  <label>Organization Type</label>
                  <span>{selectedActor.organization_type}</span>
                </div>
              )}
              {selectedActor.jurisdiction && (
                <div className="ext-info-item">
                  <label>Jurisdiction</label>
                  <span>{selectedActor.jurisdiction}</span>
                </div>
              )}
              <div className="ext-info-item">
                <label>Government Entity</label>
                <span>{selectedActor.is_government_entity ? 'Yes' : 'No'}</span>
              </div>
              <div className="ext-info-item">
                <label>Law Enforcement</label>
                <span>{selectedActor.is_law_enforcement ? 'Yes' : 'No'}</span>
              </div>
              {selectedActor.confidence_score && (
                <div className="ext-info-item">
                  <label>Confidence</label>
                  <span>{Math.round(selectedActor.confidence_score * 100)}%</span>
                </div>
              )}
            </div>
          </section>

          {/* Aliases */}
          {selectedActor.aliases && selectedActor.aliases.length > 0 && (
            <section className="ext-section">
              <h3>Aliases</h3>
              <div className="ext-tag-list">
                {selectedActor.aliases.map((alias, idx) => (
                  <span key={idx} className="ext-tag">{alias}</span>
                ))}
              </div>
            </section>
          )}

          {/* Description */}
          {selectedActor.description && (
            <section className="ext-section">
              <h3>Description</h3>
              <p>{selectedActor.description}</p>
            </section>
          )}

          {/* Roles Played */}
          {selectedActor.roles_played && selectedActor.roles_played.length > 0 && (
            <section className="ext-section">
              <h3>Roles</h3>
              <div className="ext-tag-list">
                {selectedActor.roles_played.map((role, idx) => (
                  <span key={idx} className="ext-tag">
                    {ACTOR_ROLE_LABELS[role as ActorRole] || role}
                  </span>
                ))}
              </div>
            </section>
          )}

          {/* Relations */}
          {selectedActor.relations && selectedActor.relations.length > 0 && (
            <section className="ext-section">
              <h3>Relationships</h3>
              <div className="ext-relations-list">
                {selectedActor.relations.map((relation) => (
                  <div key={relation.id} className="ext-relation-item">
                    <span className="ext-relation-type">{relation.relation_type.replace('_', ' ')}</span>
                    <span className="ext-related-actor">{relation.related_actor_id}</span>
                    {relation.confidence && (
                      <span className="ext-confidence">{Math.round(relation.confidence * 100)}%</span>
                    )}
                  </div>
                ))}
              </div>
              <button className="ext-btn ext-btn-secondary ext-btn-sm" onClick={() => setShowRelationModal(true)}>
                + Add Relationship
              </button>
            </section>
          )}

          {/* Incidents */}
          {selectedActor.incidents && selectedActor.incidents.length > 0 && (
            <section className="ext-section">
              <h3>Linked Incidents ({selectedActor.incident_count})</h3>
              <div className="ext-linked-list">
                {selectedActor.incidents.map((incident) => (
                  <div key={incident.incident_id} className="ext-linked-item">
                    <div className="ext-linked-header">
                      <span className="ext-linked-date">{incident.date || 'Unknown date'}</span>
                      <span className="ext-linked-role">{ACTOR_ROLE_LABELS[incident.role]}</span>
                    </div>
                    <div className="ext-linked-location">
                      {incident.city && `${incident.city}, `}{incident.state}
                    </div>
                    {incident.incident_type && (
                      <div className="ext-linked-type">{incident.incident_type}</div>
                    )}
                    {incident.description && (
                      <div className="ext-linked-description">{incident.description}</div>
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
    <div className="ext-modal-overlay" onClick={() => setShowCreateModal(false)}>
      <div className="ext-modal" onClick={(e) => e.stopPropagation()}>
        <div className="ext-modal-header">
          <h3>Create New Actor</h3>
          <button className="ext-close-btn" onClick={() => setShowCreateModal(false)}>×</button>
        </div>
        <div className="ext-modal-body">
          <div className="ext-form-group">
            <label>Name *</label>
            <input
              type="text"
              value={newActor.canonical_name || ''}
              onChange={(e) => setNewActor({ ...newActor, canonical_name: e.target.value })}
              placeholder="Enter actor name"
            />
          </div>

          <div className="ext-form-group">
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

          <div className="ext-form-group">
            <label>Aliases</label>
            <div className="ext-alias-input">
              <input
                type="text"
                value={newAlias}
                onChange={(e) => setNewAlias(e.target.value)}
                placeholder="Add alias"
                onKeyPress={(e) => e.key === 'Enter' && (e.preventDefault(), addAlias())}
              />
              <button type="button" onClick={addAlias}>Add</button>
            </div>
            <div className="ext-tag-list">
              {(newActor.aliases || []).map((alias, idx) => (
                <span key={idx} className="ext-alias-tag">
                  {alias}
                  <button type="button" onClick={() => removeAlias(alias)}>×</button>
                </span>
              ))}
            </div>
          </div>

          {newActor.actor_type === 'person' && (
            <>
              <div className="ext-form-row">
                <div className="ext-form-group">
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
                <div className="ext-form-group">
                  <label>Nationality</label>
                  <input
                    type="text"
                    value={newActor.nationality || ''}
                    onChange={(e) => setNewActor({ ...newActor, nationality: e.target.value })}
                    placeholder="Country"
                  />
                </div>
              </div>

              <div className="ext-form-row">
                <div className="ext-form-group">
                  <label>Immigration Status</label>
                  <input
                    type="text"
                    value={newActor.immigration_status || ''}
                    onChange={(e) => setNewActor({ ...newActor, immigration_status: e.target.value })}
                    placeholder="Status"
                  />
                </div>
                <div className="ext-form-group">
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
              <div className="ext-form-group">
                <label>Organization Type</label>
                <input
                  type="text"
                  value={newActor.organization_type || ''}
                  onChange={(e) => setNewActor({ ...newActor, organization_type: e.target.value })}
                  placeholder="e.g., Law Enforcement, NGO, etc."
                />
              </div>

              <div className="ext-form-group">
                <label>Jurisdiction</label>
                <input
                  type="text"
                  value={newActor.jurisdiction || ''}
                  onChange={(e) => setNewActor({ ...newActor, jurisdiction: e.target.value })}
                  placeholder="Geographic area of authority"
                />
              </div>

              <div className="ext-checkbox-row">
                <label className="ext-checkbox-label">
                  <input
                    type="checkbox"
                    checked={newActor.is_government_entity || false}
                    onChange={(e) => setNewActor({ ...newActor, is_government_entity: e.target.checked })}
                  />
                  Government Entity
                </label>
                <label className="ext-checkbox-label">
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

          <div className="ext-form-group">
            <label>Description</label>
            <textarea
              value={newActor.description || ''}
              onChange={(e) => setNewActor({ ...newActor, description: e.target.value })}
              placeholder="Additional notes about this actor"
              rows={3}
            />
          </div>
        </div>
        <div className="ext-modal-footer">
          <button className="ext-btn ext-btn-secondary" onClick={() => setShowCreateModal(false)}>
            Cancel
          </button>
          <button
            className="ext-btn ext-btn-primary"
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
    <div className="ext-modal-overlay" onClick={() => setShowMergeSuggestionsModal(false)}>
      <div className="ext-modal ext-modal-lg" onClick={(e) => e.stopPropagation()}>
        <div className="ext-modal-header">
          <h3>Merge Suggestions ({mergeSuggestions.length})</h3>
          <button className="ext-close-btn" onClick={() => setShowMergeSuggestionsModal(false)}>×</button>
        </div>
        <div className="ext-modal-body">
          <p className="ext-help-text">
            These actors may be duplicates. Review and merge to normalize your data.
          </p>
          {mergeSuggestions.length === 0 ? (
            <div className="ext-empty-state">No merge suggestions available</div>
          ) : (
            <div className="ext-merge-suggestions">
              {mergeSuggestions.map((suggestion, idx) => (
                <div key={idx} className="ext-merge-suggestion">
                  <div className="ext-suggestion-actors">
                    <div className="ext-actor-card">
                      <strong>{suggestion.actor1_name}</strong>
                    </div>
                    <div className="ext-merge-arrow">↔</div>
                    <div className="ext-actor-card">
                      <strong>{suggestion.actor2_name}</strong>
                    </div>
                  </div>
                  <div className="ext-suggestion-meta">
                    <span className={`ext-match-type ext-match-type-${suggestion.match_type || 'trigram'}`}>
                      {suggestion.match_type === 'first_last' ? 'Name Match' :
                       suggestion.match_type === 'containment' ? 'Contains' : 'Similar'}
                    </span>
                    <span className="ext-similarity">
                      {Math.round(suggestion.similarity * 100)}%
                    </span>
                    <span className="ext-reason">{suggestion.reason}</span>
                  </div>
                  <div className="ext-suggestion-actions">
                    <button
                      className="ext-btn ext-btn-sm ext-btn-primary"
                      onClick={() => handleMergeActors(suggestion.actor1_id, suggestion.actor2_id, true)}
                    >
                      Keep "{suggestion.actor1_name.split(' ')[0]}..."
                    </button>
                    <button
                      className="ext-btn ext-btn-sm ext-btn-secondary"
                      onClick={() => handleMergeActors(suggestion.actor1_id, suggestion.actor2_id, false)}
                    >
                      Keep "{suggestion.actor2_name.split(' ')[0]}..."
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
        <div className="ext-modal-footer">
          <button className="ext-btn ext-btn-secondary" onClick={() => setShowMergeSuggestionsModal(false)}>
            Close
          </button>
        </div>
      </div>
    </div>
  );

  const renderSimilarActorsModal = () => (
    <div className="ext-modal-overlay" onClick={() => setShowSimilarModal(false)}>
      <div className="ext-modal" onClick={(e) => e.stopPropagation()}>
        <div className="ext-modal-header">
          <h3>Similar to: {selectedActor?.canonical_name}</h3>
          <button className="ext-close-btn" onClick={() => setShowSimilarModal(false)}>×</button>
        </div>
        <div className="ext-modal-body">
          {similarActors.length === 0 ? (
            <div className="ext-empty-state">No similar actors found</div>
          ) : (
            <div className="ext-similar-actors">
              {similarActors.map((actor) => (
                <div key={actor.id} className="ext-similar-item">
                  <div className="ext-similar-info">
                    <strong>{actor.canonical_name}</strong>
                    <span className="ext-similarity-score">
                      {Math.round(actor.similarity * 100)}% match
                    </span>
                  </div>
                  <div className="ext-similar-actions">
                    <button
                      className="ext-btn ext-btn-sm ext-btn-primary"
                      onClick={() => handleQuickMerge(actor.id)}
                    >
                      Merge into "{selectedActor?.canonical_name.split(' ')[0]}..."
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
        <div className="ext-modal-footer">
          <button className="ext-btn ext-btn-secondary" onClick={() => setShowSimilarModal(false)}>
            Close
          </button>
        </div>
      </div>
    </div>
  );

  return (
    <div className="ext-browser">
      {loading && <div className="ext-loading">Loading...</div>}
      {error && <div className="ext-error">{error}</div>}

      {renderActorList()}
      {renderActorDetail()}

      {mergeSuccess && (
        <div className="ext-success-toast">{mergeSuccess}</div>
      )}

      {showCreateModal && renderCreateModal()}
      {showMergeSuggestionsModal && renderMergeSuggestionsModal()}
      {showSimilarModal && renderSimilarActorsModal()}
      {showRelationModal && (
        <div className="ext-modal-overlay" onClick={() => setShowRelationModal(false)}>
          <div className="ext-modal" onClick={(e) => e.stopPropagation()}>
            <div className="ext-modal-header">
              <h3>Add Relationship</h3>
              <button className="ext-close-btn" onClick={() => setShowRelationModal(false)}>×</button>
            </div>
            <div className="ext-modal-body">
              <p>Relationship management coming soon.</p>
            </div>
            <div className="ext-modal-footer">
              <button className="ext-btn ext-btn-secondary" onClick={() => setShowRelationModal(false)}>
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
