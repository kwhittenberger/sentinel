import { useState, useEffect } from 'react';
import type { CurationQueueItem, UniversalExtractionData } from './types';
import { SplitPane } from './SplitPane';
import { IncidentDetailView } from './IncidentDetailView';
import { ExtractionDetailView } from './ExtractionDetailView';
import { DynamicExtractionFields, buildEditData, parseExtractedData } from './DynamicExtractionFields';

const API_BASE = '/api';

interface CurationQueueProps {
  onRefresh?: () => void;
}

export function CurationQueue({ onRefresh }: CurationQueueProps) {
  const [items, setItems] = useState<CurationQueueItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedItem, setSelectedItem] = useState<CurationQueueItem | null>(null);
  const [processing, setProcessing] = useState(false);
  const [editMode, setEditMode] = useState(false);
  const [editData, setEditData] = useState<Record<string, unknown>>({});
  const [rejectReason, setRejectReason] = useState('');

  const fetchQueue = async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await fetch(`${API_BASE}/admin/queue?status=pending`);
      if (!response.ok) throw new Error('Failed to fetch queue');
      const data = await response.json();
      // Parse extracted_data strings — API may return them as JSON strings
      const items = (data.items || []).map((item: CurationQueueItem) => ({
        ...item,
        extracted_data: parseExtractedData(item.extracted_data),
      }));
      setItems(items);
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
    setEditData(buildEditData(item.extracted_data as Record<string, unknown> | null));
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
                    <DynamicExtractionFields
                      data={editData}
                      onChange={setEditData}
                    />
                  </div>
                ) : (
                  /* Use universal view if extraction has nested incident/actors structure */
                  (selectedItem.extracted_data as Record<string, unknown>)?.incident || (selectedItem.extracted_data as Record<string, unknown>)?.actors ? (
                    <ExtractionDetailView
                      data={selectedItem.extracted_data as UniversalExtractionData}
                      articleContent={selectedItem.content}
                      sourceUrl={selectedItem.source_url}
                    />
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
                  )
                )}

                <div className="detail-actions">
                  <button
                    className="action-btn approve"
                    onClick={() => handleApprove(selectedItem)}
                    disabled={processing}
                  >
                    Approve & Create Incident
                  </button>
                  <div className="bp-inline-reject">
                    <input
                      type="text"
                      className="bp-reject-input"
                      value={rejectReason}
                      onChange={e => setRejectReason(e.target.value)}
                      placeholder="Rejection reason..."
                      onKeyDown={e => { if (e.key === 'Enter' && rejectReason.trim()) { handleReject(selectedItem, rejectReason); setRejectReason(''); } }}
                    />
                    <button
                      className="action-btn reject"
                      onClick={() => { handleReject(selectedItem, rejectReason); setRejectReason(''); }}
                      disabled={processing || !rejectReason.trim()}
                    >
                      Reject
                    </button>
                  </div>
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
