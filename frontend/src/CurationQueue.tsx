import { useState, useEffect } from 'react';
import type { CurationQueueItem } from './types';
import { SplitPane } from './SplitPane';
import { IncidentDetailView } from './IncidentDetailView';

const API_BASE = '/api';

interface CurationQueueProps {
  onRefresh?: () => void;
}

interface EditableData {
  date?: string;
  state?: string;
  city?: string;
  incident_type?: string;
  victim_name?: string;
  victim_age?: number;
  victim_category?: string;
  outcome_category?: string;
  description?: string;
  offender_name?: string;
  immigration_status?: string;
  prior_deportations?: number;
  gang_affiliated?: boolean;
}

export function CurationQueue({ onRefresh }: CurationQueueProps) {
  const [items, setItems] = useState<CurationQueueItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedItem, setSelectedItem] = useState<CurationQueueItem | null>(null);
  const [processing, setProcessing] = useState(false);
  const [editMode, setEditMode] = useState(false);
  const [editData, setEditData] = useState<EditableData>({});

  const fetchQueue = async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await fetch(`${API_BASE}/admin/queue?status=pending`);
      if (!response.ok) throw new Error('Failed to fetch queue');
      const data = await response.json();
      setItems(data.items || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchQueue();
  }, []);

  const handleSelectItem = (item: CurationQueueItem) => {
    setSelectedItem(item);
    setEditMode(false);
    // Initialize edit data from extracted data
    if (item.extracted_data) {
      setEditData({
        date: item.extracted_data.date,
        state: item.extracted_data.state,
        city: item.extracted_data.city,
        incident_type: item.extracted_data.incident_type,
        victim_name: item.extracted_data.victim_name,
        victim_age: item.extracted_data.victim_age,
        victim_category: item.extracted_data.victim_category,
        outcome_category: item.extracted_data.outcome_category,
        description: item.extracted_data.description,
        offender_name: item.extracted_data.offender_name,
        immigration_status: item.extracted_data.immigration_status,
        prior_deportations: item.extracted_data.prior_deportations,
        gang_affiliated: item.extracted_data.gang_affiliated,
      });
    } else {
      setEditData({});
    }
  };

  const handleApprove = async (
    item: CurationQueueItem,
    forceCreate: boolean = false,
    linkToExistingId?: string
  ) => {
    setProcessing(true);
    setError(null);
    try {
      const overrides = editMode ? editData : undefined;
      const response = await fetch(`${API_BASE}/admin/queue/${item.id}/approve`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          overrides,
          force_create: forceCreate,
          link_to_existing_id: linkToExistingId
        }),
      });
      const data = await response.json();

      // Handle duplicate detection
      if (data.error === 'duplicate_detected') {
        const existingInfo = data.existing_location
          ? `${data.existing_date || 'Unknown date'} in ${data.existing_location}`
          : data.existing_date || 'Unknown';

        const personInfo = data.existing_name
          ? `\nMatched person: ${data.existing_name}`
          : '';

        const sourceInfo = data.existing_source
          ? `\nOriginal source: ${data.existing_source.substring(0, 60)}...`
          : '';

        const confidenceInfo = data.confidence
          ? `\nMatch confidence: ${(data.confidence * 100).toFixed(0)}%`
          : '';

        // Ask user what to do with duplicate
        const choice = window.prompt(
          `${data.message}${confidenceInfo}\n\n` +
          `Existing incident: ${existingInfo}${personInfo}${sourceInfo}\n\n` +
          `Choose action:\n` +
          `1 = Link this article as additional source to existing incident (recommended)\n` +
          `2 = Create new incident anyway\n` +
          `(Cancel to do nothing)\n\n` +
          `Enter 1 or 2:`
        );

        if (choice === '1' && data.existing_incident_id) {
          // Link to existing incident
          await handleApprove(item, false, data.existing_incident_id);
        } else if (choice === '2') {
          // Create new incident
          await handleApprove(item, true);
        }
        return;
      }

      if (!data.success) {
        throw new Error(data.error || 'Failed to approve');
      }

      setItems(items.filter(i => i.id !== item.id));
      setSelectedItem(null);
      setEditMode(false);
      setEditData({});
      onRefresh?.();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Approval failed');
    } finally {
      setProcessing(false);
    }
  };

  const handleReject = async (item: CurationQueueItem, reason: string) => {
    setProcessing(true);
    try {
      const response = await fetch(`${API_BASE}/admin/queue/${item.id}/reject`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ reason }),
      });
      if (!response.ok) throw new Error('Failed to reject');
      setItems(items.filter(i => i.id !== item.id));
      setSelectedItem(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Rejection failed');
    } finally {
      setProcessing(false);
    }
  };

  const getConfidenceColor = (confidence?: number): string => {
    if (!confidence) return 'var(--text-muted, #888)';
    if (confidence >= 0.8) return '#22c55e';
    if (confidence >= 0.5) return '#eab308';
    return '#ef4444';
  };

  const formatConfidence = (confidence?: number): string => {
    if (!confidence) return 'N/A';
    return `${(confidence * 100).toFixed(0)}%`;
  };

  if (loading) {
    return <div className="admin-page"><div className="loading">Loading queue...</div></div>;
  }

  if (error) {
    return (
      <div className="admin-page">
        <div className="settings-message error">Error: {error}</div>
        <button className="action-btn" onClick={fetchQueue}>Retry</button>
      </div>
    );
  }

  return (
    <div className="admin-page curation-queue-page">
      <div className="page-header">
        <h2>Curation Queue</h2>
        <div className="page-actions">
          <span className="stats-badge">{items.length} pending</span>
          <button className="action-btn" onClick={fetchQueue} disabled={loading}>
            Refresh
          </button>
        </div>
      </div>

      <div className="page-content">
        {items.length === 0 ? (
          <div className="empty-state">
            <p>No articles pending review</p>
            <p className="hint">
              Articles are added to the queue when the data pipeline fetches new content
              and runs LLM extraction.
            </p>
          </div>
        ) : (
          <SplitPane
            storageKey="curation-queue"
            defaultLeftWidth={350}
            minLeftWidth={250}
            maxLeftWidth={500}
            left={
              <div className="batch-list">
                {items.map(item => (
                  <div
                    key={item.id}
                    className={`batch-item ${selectedItem?.id === item.id ? 'selected' : ''}`}
                    onClick={() => handleSelectItem(item)}
                  >
                    <div className="item-header">
                      <span className="item-title">{item.title || 'Untitled'}</span>
                      <span
                        className="item-confidence"
                        style={{ color: getConfidenceColor(item.extraction_confidence) }}
                      >
                        {formatConfidence(item.extraction_confidence)}
                      </span>
                    </div>
                    <div className="item-meta">
                      <span>{item.source_name || 'Unknown source'}</span>
                      {item.published_date && <span>{item.published_date}</span>}
                    </div>
                  </div>
                ))}
              </div>
            }
            right={selectedItem ? (
              <div className="batch-detail queue-detail">
                <div className="detail-header">
                  <h3>{selectedItem.title || 'Untitled Article'}</h3>
                  <div className="header-actions">
                    {editMode ? (
                      <button className="action-btn small" onClick={() => setEditMode(false)}>
                        Cancel
                      </button>
                    ) : (
                      <button className="action-btn small primary" onClick={() => setEditMode(true)}>
                        Edit
                      </button>
                    )}
                    <span
                      className="confidence-badge"
                      style={{ background: getConfidenceColor(selectedItem.extraction_confidence) }}
                    >
                      {formatConfidence(selectedItem.extraction_confidence)}
                    </span>
                  </div>
                </div>

                <div className="detail-section">
                  <h4>Source</h4>
                  <a href={selectedItem.source_url} target="_blank" rel="noopener noreferrer">
                    {selectedItem.source_url}
                  </a>
                  <p>Published: {selectedItem.published_date || 'Unknown'}</p>
                </div>

                {editMode ? (
                  <div className="detail-section">
                    <h4>Edit Extracted Data</h4>
                    <div className="edit-form">
                      <div className="form-row">
                        <div className="form-group">
                          <label>Date</label>
                          <input
                            type="date"
                            value={editData.date || ''}
                            onChange={e => setEditData({ ...editData, date: e.target.value })}
                          />
                        </div>
                        <div className="form-group">
                          <label>State</label>
                          <input
                            type="text"
                            value={editData.state || ''}
                            onChange={e => setEditData({ ...editData, state: e.target.value })}
                          />
                        </div>
                      </div>
                      <div className="form-row">
                        <div className="form-group">
                          <label>City</label>
                          <input
                            type="text"
                            value={editData.city || ''}
                            onChange={e => setEditData({ ...editData, city: e.target.value })}
                          />
                        </div>
                        <div className="form-group">
                          <label>Incident Type</label>
                          <input
                            type="text"
                            value={editData.incident_type || ''}
                            onChange={e => setEditData({ ...editData, incident_type: e.target.value })}
                          />
                        </div>
                      </div>
                      <div className="form-row">
                        <div className="form-group">
                          <label>Victim Name</label>
                          <input
                            type="text"
                            value={editData.victim_name || ''}
                            onChange={e => setEditData({ ...editData, victim_name: e.target.value })}
                          />
                        </div>
                        <div className="form-group">
                          <label>Victim Age</label>
                          <input
                            type="number"
                            value={editData.victim_age || ''}
                            onChange={e => setEditData({ ...editData, victim_age: parseInt(e.target.value) || undefined })}
                          />
                        </div>
                      </div>
                      <div className="form-row">
                        <div className="form-group">
                          <label>Victim Category</label>
                          <select
                            value={editData.victim_category || ''}
                            onChange={e => setEditData({ ...editData, victim_category: e.target.value })}
                          >
                            <option value="">Select...</option>
                            <option value="detainee">Detainee</option>
                            <option value="enforcement_target">Enforcement Target</option>
                            <option value="protester">Protester</option>
                            <option value="journalist">Journalist</option>
                            <option value="bystander">Bystander</option>
                            <option value="us_citizen_collateral">US Citizen (Collateral)</option>
                            <option value="officer">Officer</option>
                            <option value="multiple">Multiple</option>
                          </select>
                        </div>
                        <div className="form-group">
                          <label>Outcome Category</label>
                          <select
                            value={editData.outcome_category || ''}
                            onChange={e => setEditData({ ...editData, outcome_category: e.target.value })}
                          >
                            <option value="">Select...</option>
                            <option value="fatal">Fatal</option>
                            <option value="serious_injury">Serious Injury</option>
                            <option value="minor_injury">Minor Injury</option>
                            <option value="no_injury">No Injury</option>
                            <option value="property_damage">Property Damage</option>
                            <option value="unknown">Unknown</option>
                          </select>
                        </div>
                      </div>
                      <div className="form-group">
                        <label>Description</label>
                        <textarea
                          value={editData.description || ''}
                          onChange={e => setEditData({ ...editData, description: e.target.value })}
                          rows={3}
                        />
                      </div>
                      <div className="form-row">
                        <div className="form-group">
                          <label>Offender Name</label>
                          <input
                            type="text"
                            value={editData.offender_name || ''}
                            onChange={e => setEditData({ ...editData, offender_name: e.target.value })}
                          />
                        </div>
                        <div className="form-group">
                          <label>Immigration Status</label>
                          <input
                            type="text"
                            value={editData.immigration_status || ''}
                            onChange={e => setEditData({ ...editData, immigration_status: e.target.value })}
                          />
                        </div>
                      </div>
                      <div className="form-row">
                        <div className="form-group">
                          <label>Prior Deportations</label>
                          <input
                            type="number"
                            value={editData.prior_deportations || ''}
                            onChange={e => setEditData({ ...editData, prior_deportations: parseInt(e.target.value) || undefined })}
                          />
                        </div>
                        <div className="form-group">
                          <label>Gang Affiliated</label>
                          <select
                            value={editData.gang_affiliated === undefined ? '' : editData.gang_affiliated ? 'yes' : 'no'}
                            onChange={e => setEditData({ ...editData, gang_affiliated: e.target.value === '' ? undefined : e.target.value === 'yes' })}
                          >
                            <option value="">Unknown</option>
                            <option value="yes">Yes</option>
                            <option value="no">No</option>
                          </select>
                        </div>
                      </div>
                    </div>
                  </div>
                ) : (
                  <IncidentDetailView
                    incident={{
                      id: selectedItem.id,
                      category: selectedItem.extracted_data?.category || 'crime',
                      incident_type: selectedItem.extracted_data?.incident_type || 'unknown',
                      date: selectedItem.extracted_data?.date || '',
                      state: selectedItem.extracted_data?.state || '',
                      source_url: selectedItem.source_url,
                      source_name: selectedItem.source_name,
                      tier: 3,
                      is_non_immigrant: false,
                      is_death: selectedItem.extracted_data?.involves_fatality || false,
                    }}
                    extractedData={selectedItem.extracted_data}
                    articleContent={selectedItem.content}
                    showSource={true}
                  />
                )}

                <div className="detail-actions">
                  <button
                    className="action-btn approve"
                    onClick={() => handleApprove(selectedItem)}
                    disabled={processing}
                  >
                    Approve & Create Incident
                  </button>
                  <button
                    className="action-btn reject"
                    onClick={() => {
                      const reason = prompt('Rejection reason:');
                      if (reason) handleReject(selectedItem, reason);
                    }}
                    disabled={processing}
                  >
                    Reject
                  </button>
                </div>
              </div>
            ) : (
              <div className="batch-detail empty">
                <p>Select an article to view details</p>
              </div>
            )}
          />
        )}
      </div>
    </div>
  );
}

export default CurationQueue;
