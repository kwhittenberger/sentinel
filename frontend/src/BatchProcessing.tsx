import { useState, useEffect, useCallback } from 'react';
import type { ExtractedIncidentData, UniversalExtractionData } from './types';
import { SplitPane } from './SplitPane';
import { ExtractionDetailView } from './ExtractionDetailView';
import { HighlightedArticle, collectHighlightsFromRecord } from './articleHighlight';

const API_BASE = '/api';

interface TieredItem {
  id: string;
  title?: string;
  source_name?: string;
  extraction_confidence: number | null;
  published_date?: string;
  fetched_at?: string;
}

interface FullArticle {
  id: string;
  title?: string;
  source_name?: string;
  source_url?: string;
  content?: string;
  published_date?: string;
  fetched_at?: string;
  extraction_confidence?: number;
  extracted_data?: ExtractedIncidentData;
  status?: string;
}

interface TieredQueue {
  high: TieredItem[];
  medium: TieredItem[];
  low: TieredItem[];
}

interface Suggestion {
  field: string;
  current_value: unknown;
  confidence: number;
  suggestion: unknown;
  reason: string;
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
  offender_immigration_status?: string;
  prior_deportations?: number;
  gang_affiliated?: boolean;
}

interface BatchProcessingProps {
  onClose?: () => void;
  onRefresh?: () => void;
}

export function BatchProcessing({ onClose, onRefresh }: BatchProcessingProps) {
  const [loading, setLoading] = useState(true);
  const [tieredQueue, setTieredQueue] = useState<TieredQueue>({ high: [], medium: [], low: [] });
  const [selectedTier, setSelectedTier] = useState<'high' | 'medium' | 'low'>('high');
  const [selectedItem, setSelectedItem] = useState<TieredItem | null>(null);
  const [fullArticle, setFullArticle] = useState<FullArticle | null>(null);
  const [loadingArticle, setLoadingArticle] = useState(false);
  const [suggestions, setSuggestions] = useState<Suggestion[]>([]);
  const [loadingSuggestions, setLoadingSuggestions] = useState(false);
  const [processing, setProcessing] = useState(false);
  const [message, setMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null);

  // Edit mode state
  const [editMode, setEditMode] = useState(false);
  const [editData, setEditData] = useState<EditableData>({});

  // Confirmation dialog state
  const [confirmAction, setConfirmAction] = useState<{
    type: 'bulk-approve' | 'bulk-reject';
    tier: string;
    count: number;
  } | null>(null);
  const [rejectReason, setRejectReason] = useState('');

  const loadTieredQueue = useCallback(async () => {
    setLoading(true);
    try {
      const response = await fetch(`${API_BASE}/admin/queue/tiered`);
      if (response.ok) {
        const data = await response.json();
        setTieredQueue(data);
      }
    } catch {
      setMessage({ type: 'error', text: 'Failed to load queue' });
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadTieredQueue();
  }, [loadTieredQueue]);

  const loadFullArticle = async (articleId: string) => {
    setLoadingArticle(true);
    setFullArticle(null);
    setEditMode(false);
    try {
      const response = await fetch(`${API_BASE}/admin/queue/${articleId}`);
      if (response.ok) {
        const data = await response.json();
        setFullArticle(data);
        // Initialize edit data from extracted data
        if (data.extracted_data) {
          setEditData({
            date: data.extracted_data.date,
            state: data.extracted_data.state,
            city: data.extracted_data.city,
            incident_type: data.extracted_data.incident_type,
            victim_name: data.extracted_data.victim_name,
            victim_age: data.extracted_data.victim_age,
            victim_category: data.extracted_data.victim_category,
            outcome_category: data.extracted_data.outcome_category,
            description: data.extracted_data.description,
            offender_name: data.extracted_data.offender_name,
            offender_immigration_status: data.extracted_data.offender_immigration_status,
            prior_deportations: data.extracted_data.prior_deportations,
            gang_affiliated: data.extracted_data.gang_affiliated,
          });
        }
      }
    } catch {
      // Will show limited info from selectedItem
    } finally {
      setLoadingArticle(false);
    }
  };

  const loadSuggestions = async (articleId: string) => {
    setLoadingSuggestions(true);
    setSuggestions([]);
    try {
      const response = await fetch(`${API_BASE}/admin/queue/${articleId}/suggestions`);
      if (response.ok) {
        const data = await response.json();
        setSuggestions(data.suggestions || []);
      }
    } catch {
      // Suggestions are optional, don't show error
    } finally {
      setLoadingSuggestions(false);
    }
  };

  const handleSelectItem = (item: TieredItem) => {
    setSelectedItem(item);
    setFullArticle(null);
    setEditMode(false);
    setEditData({});
    loadFullArticle(item.id);
    loadSuggestions(item.id);
  };

  const handleApprove = async () => {
    if (!selectedItem) return;
    setProcessing(true);
    try {
      // Pass edit data as overrides if in edit mode or if data was modified
      const overrides = editMode ? editData : undefined;
      const response = await fetch(`${API_BASE}/admin/queue/${selectedItem.id}/approve`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(overrides || {}),
      });
      if (response.ok) {
        setMessage({ type: 'success', text: 'Article approved' });
        setSelectedItem(null);
        setFullArticle(null);
        setEditMode(false);
        setEditData({});
        loadTieredQueue();
        onRefresh?.();
      } else {
        setMessage({ type: 'error', text: 'Failed to approve' });
      }
    } catch {
      setMessage({ type: 'error', text: 'Failed to approve' });
    } finally {
      setProcessing(false);
    }
  };

  const handleReject = async (reason?: string) => {
    if (!selectedItem) return;
    const finalReason = reason || rejectReason;
    if (!finalReason) return;

    setProcessing(true);
    try {
      const response = await fetch(`${API_BASE}/admin/queue/${selectedItem.id}/reject`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ reason: finalReason }),
      });
      if (response.ok) {
        setMessage({ type: 'success', text: 'Article rejected' });
        setSelectedItem(null);
        setFullArticle(null);
        setEditMode(false);
        setEditData({});
        setRejectReason('');
        loadTieredQueue();
      } else {
        setMessage({ type: 'error', text: 'Failed to reject' });
      }
    } catch {
      setMessage({ type: 'error', text: 'Failed to reject' });
    } finally {
      setProcessing(false);
    }
  };

  const handleBulkApprove = async () => {
    setProcessing(true);
    setMessage(null);
    setConfirmAction(null);
    try {
      const response = await fetch(`${API_BASE}/admin/queue/bulk-approve`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          tier: selectedTier,
          limit: 100,
        }),
      });
      if (response.ok) {
        const data = await response.json();
        setMessage({ type: 'success', text: `Approved ${data.approved_count} items` });
        loadTieredQueue();
        onRefresh?.();
      } else {
        setMessage({ type: 'error', text: 'Bulk approve failed' });
      }
    } catch {
      setMessage({ type: 'error', text: 'Bulk approve failed' });
    } finally {
      setProcessing(false);
    }
  };

  const handleBulkReject = async () => {
    if (!rejectReason.trim()) return;

    setProcessing(true);
    setMessage(null);
    setConfirmAction(null);
    try {
      const response = await fetch(`${API_BASE}/admin/queue/bulk-reject`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          tier: selectedTier,
          reason: rejectReason,
          limit: 100,
        }),
      });
      if (response.ok) {
        const data = await response.json();
        setMessage({ type: 'success', text: `Rejected ${data.rejected_count} items` });
        setRejectReason('');
        loadTieredQueue();
      } else {
        setMessage({ type: 'error', text: 'Bulk reject failed' });
      }
    } catch {
      setMessage({ type: 'error', text: 'Bulk reject failed' });
    } finally {
      setProcessing(false);
    }
  };

  const getConfidenceColor = (confidence: number | null | undefined): string => {
    if (confidence === null || confidence === undefined) return 'var(--text-muted)';
    if (confidence >= 0.85) return '#22c55e';
    if (confidence >= 0.50) return '#eab308';
    return '#ef4444';
  };

  const getTierDescription = (tier: 'high' | 'medium' | 'low'): string => {
    switch (tier) {
      case 'high':
        return 'High confidence (85%+) - Auto-approve candidates';
      case 'medium':
        return 'Medium confidence (50-85%) - Quick review needed';
      case 'low':
        return 'Low confidence (<50%) - Full review required';
    }
  };

  const currentItems = tieredQueue[selectedTier];
  const article = fullArticle || selectedItem;

  return (
    <div className="batch-processing">
      <div className="batch-header">
        <h2>AI-Assisted Queue Processing</h2>
        {onClose && (
          <button className="admin-close-btn" onClick={onClose}>&times;</button>
        )}
      </div>

      {message && (
        <div className={`settings-message ${message.type}`}>
          {message.text}
        </div>
      )}

      {/* Tier Tabs */}
      <div className="tier-tabs">
        {(['high', 'medium', 'low'] as const).map(tier => (
          <button
            key={tier}
            className={`tier-tab ${selectedTier === tier ? 'active' : ''} tier-${tier}`}
            onClick={() => {
              setSelectedTier(tier);
              setSelectedItem(null);
              setFullArticle(null);
              setEditMode(false);
              setEditData({});
              setSuggestions([]);
            }}
          >
            <span className="tier-name">{tier.charAt(0).toUpperCase() + tier.slice(1)}</span>
            <span className="tier-count">{tieredQueue[tier].length}</span>
          </button>
        ))}
      </div>

      <div className="tier-info">
        <p>{getTierDescription(selectedTier)}</p>
      </div>

      {/* Bulk Actions */}
      <div className="bulk-actions">
        <button
          className="action-btn approve"
          onClick={() => setConfirmAction({ type: 'bulk-approve', tier: selectedTier, count: currentItems.length })}
          disabled={processing || currentItems.length === 0 || !!confirmAction}
        >
          {processing ? 'Processing...' : `Approve All ${currentItems.length} Items`}
        </button>
        <button
          className="action-btn reject"
          onClick={() => {
            setRejectReason('');
            setConfirmAction({ type: 'bulk-reject', tier: selectedTier, count: currentItems.length });
          }}
          disabled={processing || currentItems.length === 0 || !!confirmAction}
        >
          Reject All
        </button>
        <button className="action-btn" onClick={loadTieredQueue} disabled={loading}>
          Refresh
        </button>
      </div>

      {/* Inline Confirmation Dialog */}
      {confirmAction && (
        <div className="bp-confirm-dialog">
          <div className="bp-confirm-content">
            {confirmAction.type === 'bulk-approve' ? (
              <>
                <p>
                  Approve all <strong>{confirmAction.count}</strong> items
                  in the <strong>{confirmAction.tier}</strong> confidence tier?
                </p>
                <p className="bp-confirm-note">
                  This will create incidents from the extracted data.
                </p>
                <div className="bp-confirm-actions">
                  <button className="action-btn approve" onClick={handleBulkApprove} disabled={processing}>
                    {processing ? 'Approving...' : 'Confirm Approve'}
                  </button>
                  <button className="action-btn" onClick={() => setConfirmAction(null)} disabled={processing}>
                    Cancel
                  </button>
                </div>
              </>
            ) : (
              <>
                <p>
                  Reject all <strong>{confirmAction.count}</strong> items
                  in the <strong>{confirmAction.tier}</strong> confidence tier?
                </p>
                <div className="bp-reject-reason">
                  <label>Rejection reason:</label>
                  <input
                    type="text"
                    value={rejectReason}
                    onChange={e => setRejectReason(e.target.value)}
                    placeholder="Enter reason for rejection..."
                    autoFocus
                    onKeyDown={e => { if (e.key === 'Enter' && rejectReason.trim()) handleBulkReject(); }}
                  />
                </div>
                <div className="bp-confirm-actions">
                  <button
                    className="action-btn reject"
                    onClick={handleBulkReject}
                    disabled={processing || !rejectReason.trim()}
                  >
                    {processing ? 'Rejecting...' : 'Confirm Reject'}
                  </button>
                  <button className="action-btn" onClick={() => { setConfirmAction(null); setRejectReason(''); }} disabled={processing}>
                    Cancel
                  </button>
                </div>
              </>
            )}
          </div>
        </div>
      )}

      {/* Content */}
      <SplitPane
        storageKey="batch-processing"
        defaultLeftWidth={350}
        minLeftWidth={250}
        maxLeftWidth={500}
        left={
          <div className="batch-list">
            {loading ? (
              <div className="loading">Loading queue...</div>
            ) : currentItems.length === 0 ? (
              <div className="empty-state">No items in this tier</div>
            ) : (
              currentItems.map(item => (
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
                      {item.extraction_confidence ? `${(item.extraction_confidence * 100).toFixed(0)}%` : '-'}
                    </span>
                  </div>
                  <div className="item-meta">
                    <span>{item.source_name || 'Unknown source'}</span>
                    {item.published_date && <span>{item.published_date}</span>}
                  </div>
                </div>
              ))
            )}
          </div>
        }
        right={selectedItem ? (
          <div className="batch-detail queue-detail">
            <div className="detail-header">
              <h3>{article?.title || 'Untitled Article'}</h3>
              <div className="header-actions">
                {editMode ? (
                  <>
                    <button className="action-btn small" onClick={() => setEditMode(false)}>
                      Cancel
                    </button>
                  </>
                ) : (
                  <button className="action-btn small primary" onClick={() => setEditMode(true)}>
                    Edit
                  </button>
                )}
                <span
                  className="confidence-badge"
                  style={{ background: getConfidenceColor(fullArticle?.extraction_confidence ?? selectedItem.extraction_confidence) }}
                >
                  {(fullArticle?.extraction_confidence ?? selectedItem.extraction_confidence)
                    ? `${((fullArticle?.extraction_confidence ?? selectedItem.extraction_confidence ?? 0) * 100).toFixed(0)}%`
                    : 'N/A'}
                </span>
              </div>
            </div>

            {loadingArticle ? (
              <div className="loading">Loading article details...</div>
            ) : (
              <>
                {/* Source Section */}
                <div className="detail-section">
                  <h4>Source</h4>
                  {fullArticle?.source_url ? (
                    <a href={fullArticle.source_url} target="_blank" rel="noopener noreferrer">
                      {fullArticle.source_url}
                    </a>
                  ) : (
                    <p>{article?.source_name || 'Unknown'}</p>
                  )}
                  {article?.published_date && (
                    <p>Published: {article.published_date}</p>
                  )}
                </div>

                {/* Edit Form or Extracted Data Display */}
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
                            <option value="us_citizen_collateral">US Citizen Collateral</option>
                            <option value="officer">Officer</option>
                            <option value="multiple">Multiple</option>
                          </select>
                        </div>
                        <div className="form-group">
                          <label>Outcome</label>
                          <select
                            value={editData.outcome_category || ''}
                            onChange={e => setEditData({ ...editData, outcome_category: e.target.value })}
                          >
                            <option value="">Select...</option>
                            <option value="death">Death</option>
                            <option value="serious_injury">Serious Injury</option>
                            <option value="minor_injury">Minor Injury</option>
                            <option value="no_injury">No Injury</option>
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
                            value={editData.offender_immigration_status || ''}
                            onChange={e => setEditData({ ...editData, offender_immigration_status: e.target.value })}
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
                            value={editData.gang_affiliated === true ? 'yes' : editData.gang_affiliated === false ? 'no' : ''}
                            onChange={e => setEditData({ ...editData, gang_affiliated: e.target.value === 'yes' ? true : e.target.value === 'no' ? false : undefined })}
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
                  /* Extracted Data Section */
                  fullArticle?.extracted_data && (
                    (fullArticle.extracted_data as Record<string, unknown>)?.incident ||
                    (fullArticle.extracted_data as Record<string, unknown>)?.actors ? (
                      <ExtractionDetailView
                        data={fullArticle.extracted_data as unknown as UniversalExtractionData}
                        articleContent={fullArticle.content}
                        sourceUrl={fullArticle.source_url}
                      />
                    ) : (
                      <div className="detail-section">
                        <h4>Extracted Data</h4>
                        <ExtractionTable data={fullArticle.extracted_data} />
                      </div>
                    )
                  )
                )}

                {/* AI Suggestions */}
                {!editMode && (
                  <div className="detail-section">
                    <h4>AI Suggestions</h4>
                    {loadingSuggestions ? (
                      <p className="loading-text">Loading suggestions...</p>
                    ) : suggestions.length === 0 ? (
                      <p className="no-data">No suggestions - all fields have high confidence</p>
                    ) : (
                      <div className="suggestions-list">
                        {suggestions.map(suggestion => (
                          <div key={suggestion.field} className="suggestion-item">
                            <div className="suggestion-header">
                              <span className="field-name">{suggestion.field}</span>
                              <span
                                className="field-confidence"
                                style={{ color: getConfidenceColor(suggestion.confidence) }}
                              >
                                {(suggestion.confidence * 100).toFixed(0)}%
                              </span>
                            </div>
                            <div className="suggestion-content">
                              <div className="current-value">
                                <span className="label">Current:</span>
                                <span className="value">{String(suggestion.current_value) || 'Empty'}</span>
                              </div>
                              {suggestion.suggestion != null && (
                                <div className="suggested-value">
                                  <span className="label">Suggested:</span>
                                  <span className="value">{String(suggestion.suggestion)}</span>
                                </div>
                              )}
                              <p className="reason">{suggestion.reason}</p>
                            </div>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                )}

                {/* Article Content */}
                {fullArticle?.content && (
                  <div className="detail-section">
                    <h4>Article Content</h4>
                    <div className="article-content">
                      <HighlightedArticle
                        content={fullArticle.content}
                        highlights={fullArticle.extracted_data ? collectHighlightsFromRecord(fullArticle.extracted_data as Record<string, unknown>) : []}
                      />
                    </div>
                  </div>
                )}
              </>
            )}

            <div className="detail-actions">
              <button
                className="action-btn approve"
                onClick={handleApprove}
                disabled={processing}
              >
                {processing ? 'Processing...' : editMode ? 'Save & Approve' : 'Approve & Create Incident'}
              </button>
              <div className="bp-inline-reject">
                <input
                  type="text"
                  className="bp-reject-input"
                  value={rejectReason}
                  onChange={e => setRejectReason(e.target.value)}
                  placeholder="Rejection reason..."
                  onKeyDown={e => { if (e.key === 'Enter' && rejectReason.trim()) handleReject(); }}
                />
                <button
                  className="action-btn reject"
                  onClick={() => handleReject()}
                  disabled={processing || !rejectReason.trim()}
                >
                  Reject
                </button>
              </div>
            </div>
          </div>
        ) : (
          <div className="batch-detail empty">
            <p>Select an item to view details and AI suggestions</p>
          </div>
        )}
      />
    </div>
  );
}

// Extraction table component (same as in AdminPanel)
function ExtractionTable({ data }: { data: ExtractedIncidentData }) {
  const getConfidenceColor = (confidence?: number): string => {
    if (!confidence) return 'var(--text-muted)';
    if (confidence >= 0.8) return '#22c55e';
    if (confidence >= 0.5) return '#eab308';
    return '#ef4444';
  };

  const fields = [
    { key: 'date', label: 'Date', confidence: data.date_confidence },
    { key: 'state', label: 'State', confidence: data.state_confidence },
    { key: 'city', label: 'City', confidence: data.city_confidence },
    { key: 'incident_type', label: 'Incident Type', confidence: data.incident_type_confidence },
    { key: 'victim_name', label: 'Victim Name', confidence: data.victim_name_confidence },
    { key: 'victim_age', label: 'Victim Age' },
    { key: 'victim_category', label: 'Victim Category' },
    { key: 'outcome_category', label: 'Outcome' },
    { key: 'description', label: 'Description' },
    { key: 'offender_name', label: 'Offender Name' },
    { key: 'offender_immigration_status', label: 'Immigration Status' },
    { key: 'prior_deportations', label: 'Prior Deportations' },
    { key: 'gang_affiliated', label: 'Gang Affiliated' },
  ];

  return (
    <table className="extraction-table">
      <tbody>
        {fields.map(field => {
          const value = data[field.key as keyof ExtractedIncidentData];
          if (value === undefined || value === null || value === '') return null;

          return (
            <tr key={field.key}>
              <td className="field-label">{field.label}</td>
              <td className="field-value">
                {typeof value === 'boolean' ? (value ? 'Yes' : 'No') : String(value)}
              </td>
              {'confidence' in field && field.confidence !== undefined && (
                <td className="field-confidence" style={{ color: getConfidenceColor(field.confidence) }}>
                  {(field.confidence * 100).toFixed(0)}%
                </td>
              )}
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

export default BatchProcessing;
