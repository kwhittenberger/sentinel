import { useState } from 'react';
import { HighlightedArticle, collectHighlights } from './articleHighlight';
import type { UniversalExtractionData, ExtractedActor, ExtractedEvent } from './types';
import './ExtractionDetailView.css';

interface ExtractionDetailViewProps {
  data: UniversalExtractionData | null | undefined;
  articleContent?: string;
  sourceUrl?: string;
}

function ConfidenceBadge({ value, label }: { value?: number; label?: string }) {
  if (value === undefined || value === null) return null;
  const pct = Math.round(value * 100);
  const cls = pct >= 80 ? 'edv-conf-high' : pct >= 50 ? 'edv-conf-med' : 'edv-conf-low';
  return (
    <span className={`edv-conf-badge ${cls}`} title={label || 'Confidence'}>
      {pct}%
    </span>
  );
}

function MissingBadge() {
  return <span className="edv-missing-badge">Missing</span>;
}

function FieldRow({ label, value, confidence, missing }: {
  label: string;
  value?: string | number | boolean | null;
  confidence?: number;
  missing?: boolean;
}) {
  const isEmpty = value === null || value === undefined || value === '';
  const displayValue = typeof value === 'boolean' ? (value ? 'Yes' : 'No') : String(value ?? '');

  return (
    <div className={`edv-field-row ${isEmpty && missing ? 'edv-field-missing' : ''}`}>
      <span className="edv-field-label">{label}</span>
      {isEmpty ? (
        missing ? <MissingBadge /> : <span className="edv-field-empty">--</span>
      ) : (
        <span className="edv-field-value">
          {displayValue}
          {confidence !== undefined && <ConfidenceBadge value={confidence} />}
        </span>
      )}
    </div>
  );
}

function ActorCard({ actor }: { actor: ExtractedActor }) {
  const [expanded, setExpanded] = useState(false);
  const roleColors: Record<string, string> = {
    victim: '#ef4444',
    offender: '#f97316',
    defendant: '#f97316',
    officer: '#3b82f6',
    witness: '#8b5cf6',
    arresting_agency: '#0ea5e9',
    investigating_agency: '#0ea5e9',
    prosecuting_agency: '#0ea5e9',
    journalist: '#10b981',
    bystander: '#6b7280',
    family_member: '#a855f7',
    detainee: '#dc2626',
  };

  return (
    <div className={`edv-actor-card edv-actor-${actor.actor_type}`}>
      <div className="edv-actor-header" onClick={() => setExpanded(!expanded)}>
        <div className="edv-actor-name-row">
          <span className="edv-actor-name">{actor.name}</span>
          {actor.name_confidence !== undefined && actor.name_confidence < 1.0 && (
            <ConfidenceBadge value={actor.name_confidence} label="Name confidence" />
          )}
          <span className={`edv-actor-type-badge edv-actor-type-${actor.actor_type}`}>
            {actor.actor_type}
          </span>
        </div>
        <div className="edv-actor-roles">
          {(actor.roles || []).map(role => (
            <span
              key={role}
              className="edv-role-tag"
              style={{ borderColor: roleColors[role] || '#6b7280', color: roleColors[role] || '#6b7280' }}
            >
              {role.replace(/_/g, ' ')}
            </span>
          ))}
        </div>
        <span className="edv-expand-icon">{expanded ? '\u25B2' : '\u25BC'}</span>
      </div>

      {expanded && (
        <div className="edv-actor-details">
          {actor.age !== undefined && <FieldRow label="Age" value={actor.age} />}
          {actor.gender && <FieldRow label="Gender" value={actor.gender} />}
          {actor.nationality && <FieldRow label="Nationality" value={actor.nationality} />}
          {actor.country_of_origin && <FieldRow label="Country of Origin" value={actor.country_of_origin} />}
          {actor.immigration_status && <FieldRow label="Immigration Status" value={actor.immigration_status} />}
          {actor.prior_deportations !== undefined && <FieldRow label="Prior Deportations" value={actor.prior_deportations} />}
          {actor.prior_criminal_history !== undefined && <FieldRow label="Prior Criminal History" value={actor.prior_criminal_history} />}
          {actor.gang_affiliation && <FieldRow label="Gang Affiliation" value={actor.gang_affiliation} />}
          {actor.agency_type && <FieldRow label="Agency Type" value={actor.agency_type.toUpperCase()} />}
          {actor.charges && actor.charges.length > 0 && (
            <div className="edv-field-row">
              <span className="edv-field-label">Charges</span>
              <div className="edv-tag-list">
                {actor.charges.map((c, i) => <span key={i} className="edv-charge-tag">{c}</span>)}
              </div>
            </div>
          )}
          {actor.sentence && <FieldRow label="Sentence" value={actor.sentence} />}
          {actor.injuries && <FieldRow label="Injuries" value={actor.injuries} />}
          {actor.action_taken && <FieldRow label="Action Taken" value={actor.action_taken} />}
          {actor.notes && <FieldRow label="Notes" value={actor.notes} />}
        </div>
      )}
    </div>
  );
}

function EventRow({ event }: { event: ExtractedEvent }) {
  const typeIcons: Record<string, string> = {
    murder: '\u2620',
    shooting: '\uD83D\uDD2B',
    arrest: '\u2696',
    protest: '\u270A',
    vigil: '\uD83D\uDD6F',
    prior_arrest: '\uD83D\uDCCB',
    conviction: '\u2696',
    deportation_attempt: '\u2708',
    indictment: '\uD83D\uDCC4',
    immigration_hearing: '\uD83C\uDFDB',
    removal_order: '\uD83D\uDCC3',
    release: '\uD83D\uDD13',
    immigration_detainer: '\uD83D\uDD12',
    prior_charges: '\uD83D\uDCCB',
    alleged_prior_murder: '\u2620',
  };

  return (
    <div className="edv-event-row">
      <div className="edv-event-date">
        {event.date || '??'}
      </div>
      <div className="edv-event-content">
        <span className="edv-event-type">
          {typeIcons[event.event_type] || '\u2022'}{' '}
          {(event.event_type || 'unknown').replace(/_/g, ' ')}
        </span>
        {event.description && <span className="edv-event-desc">{event.description}</span>}
        {event.relation_to_incident && (
          <span className="edv-event-relation">{event.relation_to_incident.replace(/_/g, ' ')}</span>
        )}
      </div>
    </div>
  );
}

export function ExtractionDetailView({ data, articleContent, sourceUrl }: ExtractionDetailViewProps) {
  const [showArticle, setShowArticle] = useState(false);

  if (!data) {
    return (
      <div className="edv-container">
        <div className="edv-missing-warning">No extraction data available.</div>
      </div>
    );
  }

  const incident = data.incident;
  const actors = data.actors || [];
  const events = data.events || [];
  const policy = data.policy_context;

  // Build highlights from extracted data for article content
  const highlights = collectHighlights([
    ['City', incident?.location?.city],
    ['State', incident?.location?.state],
    ['County', incident?.location?.county],
    ['Address', incident?.location?.address],
    ['Title', incident?.title],
    ['Outcome', incident?.outcome?.severity],
    ['Outcome Detail', incident?.outcome?.description],
    ...actors.map(a => ['Actor: ' + a.actor_type, a.name] as [string, string | undefined]),
  ]);

  const isRelevant = data.is_relevant ?? data.isRelevant;
  const confidence = data.confidence ?? incident?.overall_confidence;

  // Check what's missing
  const missingFields: string[] = [];
  if (!incident?.date) missingFields.push('Date');
  if (!incident?.location?.state) missingFields.push('State');
  if (!incident?.incident_types?.length) missingFields.push('Incident Type');
  if (!incident?.summary) missingFields.push('Summary');

  // Group actors by role
  const actorsByRole: Record<string, ExtractedActor[]> = {};
  actors.forEach(a => {
    (a.roles || []).forEach(role => {
      if (!actorsByRole[role]) actorsByRole[role] = [];
      actorsByRole[role].push(a);
    });
  });

  // Sort events by date
  const sortedEvents = [...events].sort((a, b) => {
    if (!a.date) return 1;
    if (!b.date) return -1;
    return a.date.localeCompare(b.date);
  });

  return (
    <div className="edv-container">
      {/* Relevance & Confidence Header */}
      <div className="edv-header">
        <div className="edv-header-left">
          {isRelevant !== undefined && (
            <span className={`edv-relevance-badge ${isRelevant ? 'edv-relevant' : 'edv-not-relevant'}`}>
              {isRelevant ? 'Relevant' : 'Not Relevant'}
            </span>
          )}
          {data.categories?.map(cat => (
            <span key={cat} className={`edv-category-badge edv-cat-${cat}`}>
              {cat}
            </span>
          ))}
          {data.extraction_type && (
            <span className="edv-extraction-type">{data.extraction_type}</span>
          )}
        </div>
        {confidence !== undefined && (
          <div className="edv-header-confidence">
            <span className="edv-conf-label">Confidence</span>
            <ConfidenceBadge value={confidence} />
          </div>
        )}
      </div>

      {data.relevance_reason && (
        <div className="edv-relevance-reason">{data.relevance_reason}</div>
      )}

      {/* Missing Fields Warning */}
      {missingFields.length > 0 && (
        <div className="edv-missing-warning">
          <strong>Missing required fields:</strong> {missingFields.join(', ')}
        </div>
      )}

      {/* Incident Summary */}
      {incident && (
        <div className="edv-section">
          <h4 className="edv-section-title">Incident Details</h4>

          {incident.title && (
            <div className="edv-incident-title">{incident.title}</div>
          )}

          <div className="edv-fields-grid">
            <FieldRow
              label="Date"
              value={incident.date}
              confidence={incident.date_confidence}
              missing={!incident.date}
            />
            <FieldRow
              label="State"
              value={incident.location?.state}
              confidence={incident.location_confidence}
              missing={!incident.location?.state}
            />
            <FieldRow
              label="City"
              value={incident.location?.city}
              confidence={incident.location_confidence}
            />
            {incident.location?.county && (
              <FieldRow label="County" value={incident.location.county} />
            )}
            {incident.location?.address && (
              <FieldRow label="Address" value={incident.location.address} />
            )}
            {incident.location?.location_type && (
              <FieldRow label="Location Type" value={incident.location.location_type} />
            )}
            {incident.date_approximate !== undefined && (
              <FieldRow label="Date Approximate" value={incident.date_approximate} />
            )}
          </div>

          {incident.incident_types && incident.incident_types.length > 0 && (
            <div className="edv-field-row">
              <span className="edv-field-label">Incident Types</span>
              <div className="edv-tag-list">
                {incident.incident_types.map((t, i) => (
                  <span key={i} className="edv-type-tag">{t.replace(/_/g, ' ')}</span>
                ))}
              </div>
            </div>
          )}

          {incident.outcome && (
            <div className="edv-outcome">
              <FieldRow label="Outcome Severity" value={incident.outcome.severity} />
              {incident.outcome.description && (
                <div className="edv-outcome-desc">{incident.outcome.description}</div>
              )}
            </div>
          )}

          {incident.summary && (
            <div className="edv-summary">
              <span className="edv-field-label">Summary</span>
              <p>{incident.summary}</p>
            </div>
          )}
        </div>
      )}

      {/* Actors */}
      {actors.length > 0 && (
        <div className="edv-section">
          <h4 className="edv-section-title">
            Actors & Entities
            <span className="edv-count-badge">{actors.length}</span>
          </h4>
          <div className="edv-actors-list">
            {actors.map((actor, i) => (
              <ActorCard key={i} actor={actor} />
            ))}
          </div>
        </div>
      )}

      {/* Events Timeline */}
      {sortedEvents.length > 0 && (
        <div className="edv-section">
          <h4 className="edv-section-title">
            Related Events
            <span className="edv-count-badge">{sortedEvents.length}</span>
          </h4>
          <div className="edv-events-timeline">
            {sortedEvents.map((event, i) => (
              <EventRow key={i} event={event} />
            ))}
          </div>
        </div>
      )}

      {/* Policy Context */}
      {policy && (policy.policy_mentioned || policy.ice_detainer_status || policy.sanctuary_jurisdiction !== undefined) && (
        <div className="edv-section">
          <h4 className="edv-section-title">Policy Context</h4>
          <div className="edv-fields-grid">
            {policy.ice_detainer_status && (
              <FieldRow label="ICE Detainer Status" value={policy.ice_detainer_status.replace(/_/g, ' ')} />
            )}
            {policy.sanctuary_jurisdiction !== undefined && (
              <FieldRow label="Sanctuary Jurisdiction" value={policy.sanctuary_jurisdiction} />
            )}
          </div>
          {policy.policy_mentioned && (
            <div className="edv-policy-note">{policy.policy_mentioned}</div>
          )}
        </div>
      )}

      {/* Sources Cited */}
      {data.sources_cited && data.sources_cited.length > 0 && (
        <div className="edv-section">
          <h4 className="edv-section-title">
            Sources Cited
            <span className="edv-count-badge">{data.sources_cited.length}</span>
          </h4>
          <div className="edv-sources-list">
            {data.sources_cited.map((src, i) => (
              <span key={i} className="edv-source-tag">{src}</span>
            ))}
          </div>
        </div>
      )}

      {/* Extraction Notes */}
      {data.extraction_notes && (
        <div className="edv-section edv-notes-section">
          <h4 className="edv-section-title">Extraction Notes</h4>
          <p className="edv-extraction-notes">{data.extraction_notes}</p>
        </div>
      )}

      {/* Source Link */}
      {sourceUrl && (
        <div className="edv-section">
          <h4 className="edv-section-title">Source Article</h4>
          <a href={sourceUrl} target="_blank" rel="noopener noreferrer" className="edv-source-link">
            {sourceUrl}
          </a>
        </div>
      )}

      {/* Article Content (collapsible) */}
      {articleContent && (
        <div className="edv-section">
          <button
            className="edv-toggle-article"
            onClick={() => setShowArticle(!showArticle)}
          >
            {showArticle ? 'Hide' : 'Show'} Article Content
            <span className="edv-expand-icon">{showArticle ? '\u25B2' : '\u25BC'}</span>
          </button>
          {showArticle && (
            <div className="edv-article-content">
              <HighlightedArticle content={articleContent} highlights={highlights} />
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default ExtractionDetailView;
