import { useState } from 'react';
import { HighlightedArticle, collectHighlightsFromRecord } from './articleHighlight';
import type { Incident, IncidentActor, IncidentEvent, ExtractedIncidentData } from './types';
import './ExtensibleSystem.css';

interface IncidentDetailViewProps {
  incident?: Incident | null;
  extractedData?: ExtractedIncidentData | null;
  articleContent?: string;
  showSource?: boolean;
  onClose?: () => void;
}

interface TaggedFieldProps {
  label: string;
  value: string | number | boolean | null | undefined;
  confidence?: number;
  type?: 'person' | 'location' | 'date' | 'status' | 'number' | 'text';
}

function TaggedField({ label, value, confidence, type = 'text' }: TaggedFieldProps) {
  if (value === null || value === undefined || value === '') {
    return null;
  }

  const displayValue = typeof value === 'boolean' ? (value ? 'Yes' : 'No') : String(value);

  const getTypeClass = () => {
    switch (type) {
      case 'person': return 'ext-field-person';
      case 'location': return 'ext-field-location';
      case 'date': return 'ext-field-date';
      case 'status': return 'ext-field-status';
      case 'number': return 'ext-field-number';
      default: return 'ext-field-text';
    }
  };

  const getConfidenceClass = () => {
    if (!confidence) return '';
    if (confidence >= 0.8) return 'ext-confidence-high';
    if (confidence >= 0.5) return 'ext-confidence-medium';
    return 'ext-confidence-low';
  };

  return (
    <div className="ext-tagged-field">
      <span className="ext-field-label">{label}</span>
      <span className={`ext-field-value ${getTypeClass()}`}>
        {displayValue}
        {confidence !== undefined && (
          <span className={`ext-field-confidence ${getConfidenceClass()}`}>
            {(confidence * 100).toFixed(0)}%
          </span>
        )}
      </span>
    </div>
  );
}

const roleColors: Record<string, string> = {
  victim: '#ef4444',
  offender: '#f97316',
  officer: '#3b82f6',
  witness: '#8b5cf6',
  arresting_agency: '#0ea5e9',
  reporting_agency: '#0ea5e9',
  bystander: '#6b7280',
  organizer: '#10b981',
  participant: '#6b7280',
};

const eventTypeIcons: Record<string, string> = {
  murder: '\u2620',
  shooting: '\uD83D\uDD2B',
  arrest: '\u2696',
  protest: '\u270A',
  prior_arrest: '\uD83D\uDCCB',
  conviction: '\u2696',
  deportation_attempt: '\u2708',
  indictment: '\uD83D\uDCC4',
  release: '\uD83D\uDD13',
  immigration_detainer: '\uD83D\uDD12',
};

function IncidentActorCard({ actor }: { actor: IncidentActor }) {
  const [expanded, setExpanded] = useState(false);
  const borderColor = actor.actor_type === 'agency' ? '#0ea5e9'
    : actor.actor_type === 'group' ? '#8b5cf6'
    : '#3b82f6';

  return (
    <div className="edv-actor-card" style={{ borderLeft: `3px solid ${borderColor}` }}>
      <div className="edv-actor-header" onClick={() => setExpanded(!expanded)}>
        <div className="edv-actor-name-row">
          <span className="edv-actor-name">{actor.canonical_name}</span>
          <span className={`edv-actor-type-badge edv-actor-type-${actor.actor_type}`}>
            {actor.actor_type}
          </span>
        </div>
        <div className="edv-actor-roles">
          <span
            className="edv-role-tag"
            style={{
              borderColor: roleColors[actor.role] || '#6b7280',
              color: roleColors[actor.role] || '#6b7280',
            }}
          >
            {(actor.role_type_name || actor.role).replace(/_/g, ' ')}
          </span>
        </div>
        <span className="edv-expand-icon">{expanded ? '\u25B2' : '\u25BC'}</span>
      </div>
      {expanded && (
        <div className="edv-actor-details">
          {actor.gender && (
            <div className="edv-field-row">
              <span className="edv-field-label">Gender</span>
              <span className="edv-field-value">{actor.gender}</span>
            </div>
          )}
          {actor.nationality && (
            <div className="edv-field-row">
              <span className="edv-field-label">Nationality</span>
              <span className="edv-field-value">{actor.nationality}</span>
            </div>
          )}
          {actor.immigration_status && (
            <div className="edv-field-row">
              <span className="edv-field-label">Immigration Status</span>
              <span className="edv-field-value">{actor.immigration_status}</span>
            </div>
          )}
          {actor.prior_deportations !== undefined && actor.prior_deportations > 0 && (
            <div className="edv-field-row">
              <span className="edv-field-label">Prior Deportations</span>
              <span className="edv-field-value">{actor.prior_deportations}</span>
            </div>
          )}
          {actor.is_law_enforcement && (
            <div className="edv-field-row">
              <span className="edv-field-label">Law Enforcement</span>
              <span className="edv-field-value">Yes</span>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function IncidentEventRow({ event }: { event: IncidentEvent }) {
  const icon = event.event_type ? (eventTypeIcons[event.event_type] || '\u2022') : '\u2022';
  return (
    <div className="edv-event-row">
      <div className="edv-event-date">
        {event.start_date || '??'}
      </div>
      <div className="edv-event-content">
        <span className="edv-event-type">
          {icon}{' '}
          {event.event_type ? event.event_type.replace(/_/g, ' ') : event.name}
        </span>
        {event.description && (
          <span className="edv-event-desc">{event.description}</span>
        )}
      </div>
    </div>
  );
}

export function IncidentDetailView({
  incident,
  extractedData,
  articleContent,
  showSource = true,
  onClose
}: IncidentDetailViewProps) {
  // Use extracted data if available, fall back to incident data
  const data = extractedData || incident;

  if (!data) {
    return (
      <div className="ext-empty-state">
        <p>No incident data available</p>
      </div>
    );
  }

  const isEnforcement = incident?.category === 'enforcement';
  const isCrime = incident?.category === 'crime';

  // Build highlights from incident + extracted data for article content
  const highlights = collectHighlightsFromRecord({
    ...(incident ? incident : {}),
    ...(extractedData ? extractedData : {}),
  } as Record<string, unknown>);

  return (
    <div className="ext-incident-detail-view">
      {onClose && (
        <button className="ext-close-btn" onClick={onClose}>&times;</button>
      )}

      {/* Header with category badge */}
      <div className="ext-detail-view-header">
        {incident?.category && (
          <span className={`ext-badge ext-badge-category-${incident.category}`}>
            {incident.category}
          </span>
        )}
        {incident?.incident_type && (
          <span className="ext-badge ext-badge-type">
            {incident.incident_type.replace(/_/g, ' ')}
          </span>
        )}
        {incident?.domain_name && (
          <span className="ext-badge ext-badge-domain">
            {incident.domain_name}
          </span>
        )}
        {incident?.category_name && incident.category_name !== incident?.incident_type && (
          <span className="ext-badge ext-badge-event-category">
            {incident.category_name}
          </span>
        )}
      </div>

      {/* Core Details Section */}
      <div className="ext-detail-section-group">
        <h4>Incident Details</h4>
        <div className="ext-tagged-fields-grid">
          <TaggedField
            label="Date"
            value={extractedData?.date || incident?.date}
            confidence={extractedData?.date_confidence}
            type="date"
          />
          <TaggedField
            label="State"
            value={extractedData?.state || incident?.state}
            confidence={extractedData?.state_confidence}
            type="location"
          />
          <TaggedField
            label="City"
            value={extractedData?.city || incident?.city}
            confidence={extractedData?.city_confidence}
            type="location"
          />
          <TaggedField
            label="Incident Type"
            value={extractedData?.incident_type || incident?.incident_type}
            confidence={extractedData?.incident_type_confidence}
          />
          <TaggedField
            label="Outcome"
            value={extractedData?.outcome_category || incident?.outcome_category}
            confidence={extractedData?.outcome_category_confidence}
            type="status"
          />
        </div>
      </div>

      {/* Enforcement: Victim Details */}
      {(isEnforcement || extractedData?.victim_name) && (
        <div className="ext-detail-section-group">
          <h4>Victim Information</h4>
          <div className="ext-tagged-fields-grid">
            <TaggedField
              label="Victim Name"
              value={extractedData?.victim_name || incident?.victim_name}
              confidence={extractedData?.victim_name_confidence}
              type="person"
            />
            <TaggedField
              label="Victim Age"
              value={extractedData?.victim_age || incident?.victim_age}
              type="number"
            />
            <TaggedField
              label="Victim Category"
              value={extractedData?.victim_category || incident?.victim_category}
              confidence={extractedData?.victim_category_confidence}
              type="status"
            />
          </div>
        </div>
      )}

      {/* Crime: Offender Details */}
      {(isCrime || extractedData?.offender_name) && (
        <div className="ext-detail-section-group ext-offender-section">
          <h4>Offender Information</h4>
          <div className="ext-tagged-fields-grid">
            <TaggedField
              label="Offender Name"
              value={extractedData?.offender_name}
              type="person"
            />
            <TaggedField
              label="Age"
              value={(extractedData as any)?.offender_age}
              type="number"
            />
            <TaggedField
              label="Nationality"
              value={(extractedData as any)?.offender_nationality || (extractedData as any)?.offender_country_of_origin}
              type="location"
            />
            <TaggedField
              label="Immigration Status"
              value={extractedData?.immigration_status || incident?.offender_immigration_status}
              type="status"
            />
            <TaggedField
              label="Prior Deportations"
              value={extractedData?.prior_deportations ?? incident?.prior_deportations}
              type="number"
            />
            <TaggedField
              label="Prior Arrests"
              value={(extractedData as any)?.prior_arrests}
              type="number"
            />
            <TaggedField
              label="Prior Convictions"
              value={(extractedData as any)?.prior_convictions}
              type="number"
            />
            <TaggedField
              label="Gang Affiliated"
              value={extractedData?.gang_affiliated ?? incident?.gang_affiliated}
              type="status"
            />
            {(extractedData as any)?.gang_name && (
              <TaggedField
                label="Gang Name"
                value={(extractedData as any)?.gang_name}
              />
            )}
            {(extractedData as any)?.cartel_connection && (
              <TaggedField
                label="Cartel Connection"
                value={(extractedData as any)?.cartel_connection}
              />
            )}
          </div>

          {/* Policy failures */}
          {((extractedData as any)?.ice_detainer_ignored ||
            (extractedData as any)?.was_released_sanctuary ||
            (extractedData as any)?.was_released_bail) && (
            <div className="ext-policy-failures">
              <h5>Policy Failures</h5>
              <div className="ext-tagged-fields-grid">
                <TaggedField
                  label="ICE Detainer Ignored"
                  value={(extractedData as any)?.ice_detainer_ignored}
                  type="status"
                />
                <TaggedField
                  label="Released (Sanctuary)"
                  value={(extractedData as any)?.was_released_sanctuary}
                  type="status"
                />
                <TaggedField
                  label="Released on Bail"
                  value={(extractedData as any)?.was_released_bail}
                  type="status"
                />
              </div>
            </div>
          )}
        </div>
      )}

      {/* Charges and Sentence */}
      {((extractedData as any)?.charges || (extractedData as any)?.sentence) && (
        <div className="ext-detail-section-group">
          <h4>Legal Details</h4>
          {(extractedData as any)?.charges && (
            <div className="ext-charges-list">
              <span className="ext-field-label">Charges:</span>
              <div className="ext-tag-list">
                {(extractedData as any).charges.map((charge: string, i: number) => (
                  <span key={i} className="ext-tag ext-tag-charge">{charge}</span>
                ))}
              </div>
            </div>
          )}
          <TaggedField
            label="Sentence"
            value={(extractedData as any)?.sentence}
          />
        </div>
      )}

      {/* Description with Markdown */}
      {(extractedData?.description || incident?.description || incident?.notes) && (
        <div className="ext-detail-section-group">
          <h4>Description</h4>
          <div className="ext-description-content">
            <HighlightedArticle
              content={extractedData?.description || incident?.description || incident?.notes || ''}
              highlights={highlights}
            />
          </div>
        </div>
      )}

      {/* Article Content with Markdown */}
      {articleContent && (
        <div className="ext-detail-section-group">
          <h4>Article Content</h4>
          <div className="ext-article-content">
            <HighlightedArticle content={articleContent} highlights={highlights} />
          </div>
        </div>
      )}

      {/* Sources */}
      {showSource && (incident?.sources?.length || incident?.source_url) && (
        <div className="ext-detail-section-group">
          <h4>Sources ({incident?.sources?.length || 1})</h4>
          <div className="ext-sources-list">
            {incident?.sources && incident.sources.length > 0 ? (
              incident.sources.map((source, idx) => (
                <div key={source.id || idx} className="ext-source-item">
                  <a
                    href={source.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="ext-source-link"
                  >
                    {source.title || source.url}
                  </a>
                  <div className="ext-source-meta">
                    {source.is_primary && (
                      <span className="ext-badge ext-badge-primary">Primary</span>
                    )}
                    {source.published_date && (
                      <span className="ext-source-date">{source.published_date}</span>
                    )}
                  </div>
                </div>
              ))
            ) : (
              <div className="ext-source-item">
                <a
                  href={incident?.source_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="ext-source-link"
                >
                  {incident?.source_name || incident?.source_url}
                </a>
              </div>
            )}
          </div>
          {incident?.tier && (
            <span className="ext-badge ext-badge-tier">Tier {incident.tier}</span>
          )}
        </div>
      )}

      {/* Actors */}
      {incident?.actors && incident.actors.length > 0 && (
        <div className="ext-detail-section-group">
          <h4>
            Actors & Entities
            <span className="edv-count-badge" style={{ marginLeft: 6 }}>{incident.actors.length}</span>
          </h4>
          <div className="edv-actors-list">
            {incident.actors.map((actor) => (
              <IncidentActorCard key={actor.id + actor.role} actor={actor} />
            ))}
          </div>
        </div>
      )}

      {/* Events Timeline */}
      {incident?.linked_events && incident.linked_events.length > 0 && (
        <div className="ext-detail-section-group">
          <h4>
            Related Events
            <span className="edv-count-badge" style={{ marginLeft: 6 }}>{incident.linked_events.length}</span>
          </h4>
          <div className="edv-events-timeline">
            {incident.linked_events.map((event) => (
              <IncidentEventRow key={event.id} event={event} />
            ))}
          </div>
        </div>
      )}

      {/* Extraction Notes */}
      {(extractedData as any)?.extraction_notes && (
        <div className="ext-detail-section-group ext-extraction-notes">
          <h4>Extraction Notes</h4>
          <p>{(extractedData as any).extraction_notes}</p>
        </div>
      )}

      {/* Overall Confidence */}
      {(extractedData as any)?.overall_confidence !== undefined && (
        <div className="ext-overall-confidence">
          <span className="ext-field-label">Overall Confidence:</span>
          <span className={`ext-confidence-badge ${
            (extractedData as any).overall_confidence >= 0.8 ? 'high' :
            (extractedData as any).overall_confidence >= 0.5 ? 'medium' : 'low'
          }`}>
            {((extractedData as any).overall_confidence * 100).toFixed(0)}%
          </span>
        </div>
      )}
    </div>
  );
}

export default IncidentDetailView;
