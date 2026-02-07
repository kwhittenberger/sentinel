import { IncidentDetailView } from '../IncidentDetailView';
import { ExtractionDetailView } from '../ExtractionDetailView';
import type { Incident, IncidentConnections, UniversalExtractionData } from '../types';

interface IncidentDetailDrawerProps {
  incident: Incident | null;
  fullIncident: Incident | null;
  drawerOpen: boolean;
  extractionData: UniversalExtractionData | null;
  articleContent: string | null;
  sourceUrl: string | null;
  connections: IncidentConnections | null;
  connectionsLoading: boolean;
  incidents: Incident[];
  onClose: () => void;
  onZoom: (incident: Incident) => void;
  onSelectIncident: (incident: Incident) => void;
  onSetEventFilter: (eventId: string) => void;
  getStateDisplayName: (incident: Incident) => string;
  formatDate: (dateStr: string) => string;
}

export function IncidentDetailDrawer({
  incident,
  fullIncident,
  drawerOpen,
  extractionData,
  articleContent,
  sourceUrl,
  connections,
  connectionsLoading,
  incidents,
  onClose,
  onZoom,
  onSelectIncident,
  onSetEventFilter,
  getStateDisplayName,
  formatDate,
}: IncidentDetailDrawerProps) {
  return (
    <>
      <div className={`detail-drawer-overlay ${drawerOpen && incident ? 'visible' : ''}`}
        onClick={onClose} />
      <div className={`detail-drawer ${drawerOpen && incident ? 'open' : ''}`}>
        {incident && (
          <>
            <div className="detail-drawer-header">
              <div className="detail-drawer-title">
                <h3>{incident.city}, {getStateDisplayName(incident)}</h3>
                {incident.victim_name && (
                  <span className="detail-drawer-subtitle">{incident.victim_name}</span>
                )}
              </div>
              <div className="detail-drawer-actions">
                {incident.lat && incident.lon && (
                  <button className="detail-drawer-action-btn" onClick={() => onZoom(incident)}>
                    Zoom
                  </button>
                )}
                <button className="detail-drawer-close" onClick={onClose} aria-label="Close detail drawer">&times;</button>
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
                      incident={fullIncident || incident}
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
                                onClick={() => onSetEventFilter(ev.event_id)}
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
                                    if (full) onSelectIncident(full);
                                  }}
                                >
                                  <span className="connected-incident-date">{sib.date?.split('T')[0] || '\u2014'}</span>
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

                    {incident.linked_ids && incident.linked_ids.length > 0 && (
                      <div className="connected-linked-reports">
                        <div className="connected-section-label">Linked Reports ({incident.linked_ids.length})</div>
                        {incident.linked_ids.map(linkedId => {
                          const linkedInc = incidents.find(i => i.id === linkedId);
                          return (
                            <div
                              key={linkedId}
                              className="connected-incident-item"
                              onClick={() => {
                                if (linkedInc) onSelectIncident(linkedInc);
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
                      (!incident.linked_ids || incident.linked_ids.length === 0) && (
                      <p className="connected-empty">No connected incidents found.</p>
                    )}
                  </div>
                </div>
              </div>
            </div>
          </>
        )}
      </div>
    </>
  );
}
