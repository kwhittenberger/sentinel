import ReactMarkdown from 'react-markdown';
import type { Incident, ExtractedIncidentData } from './types';
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
            <ReactMarkdown>
              {extractedData?.description || incident?.description || incident?.notes || ''}
            </ReactMarkdown>
          </div>
        </div>
      )}

      {/* Article Content with Markdown */}
      {articleContent && (
        <div className="ext-detail-section-group">
          <h4>Article Content</h4>
          <div className="ext-article-content">
            <ReactMarkdown>
              {articleContent}
            </ReactMarkdown>
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
