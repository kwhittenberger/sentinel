import { useState, useEffect, useCallback } from 'react';

const API_BASE = '/api';

interface AutoApprovalSettings {
  min_confidence_auto_approve: number;
  min_confidence_review: number;
  auto_reject_below: number;
  required_fields: string[];
  field_confidence_threshold: number;
  min_severity_auto_approve: number;
  max_severity_auto_reject: number;
  enable_auto_approve: boolean;
  enable_auto_reject: boolean;
  enforcement_confidence_threshold: number;
  crime_confidence_threshold: number;
}

interface DuplicateSettings {
  title_similarity_threshold: number;
  content_similarity_threshold: number;
  entity_match_date_window: number;
  shingle_size: number;
  enable_url_match: boolean;
  enable_title_match: boolean;
  enable_content_match: boolean;
  enable_entity_match: boolean;
}

interface PipelineSettings {
  enable_llm_extraction: boolean;
  enable_duplicate_detection: boolean;
  enable_auto_approval: boolean;
  batch_size: number;
  delay_between_articles_ms: number;
  max_article_length: number;
  default_source_tier: number;
}

interface Feed {
  id: string;
  name: string;
  url: string;
  feed_type: string;
  interval_minutes: number;
  active: boolean;
  last_fetched?: string;
}

interface SettingsPanelProps {
  onClose?: () => void;
}

export function SettingsPanel({ onClose }: SettingsPanelProps) {
  const [activeTab, setActiveTab] = useState<'auto-approval' | 'duplicate' | 'pipeline' | 'feeds'>('auto-approval');
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null);

  const [autoApproval, setAutoApproval] = useState<AutoApprovalSettings | null>(null);
  const [duplicate, setDuplicate] = useState<DuplicateSettings | null>(null);
  const [pipeline, setPipeline] = useState<PipelineSettings | null>(null);
  const [feeds, setFeeds] = useState<Feed[]>([]);
  const [showAddFeed, setShowAddFeed] = useState(false);
  const [newFeed, setNewFeed] = useState({ name: '', url: '', interval_minutes: 60 });

  const loadSettings = useCallback(async () => {
    setLoading(true);
    try {
      const response = await fetch(`${API_BASE}/admin/settings`);
      if (response.ok) {
        const data = await response.json();
        setAutoApproval(data.auto_approval);
        setDuplicate(data.duplicate_detection);
        setPipeline(data.pipeline);
      }

      const feedsResponse = await fetch(`${API_BASE}/admin/feeds`);
      if (feedsResponse.ok) {
        const feedsData = await feedsResponse.json();
        setFeeds(feedsData.feeds || []);
      }
    } catch (err) {
      setMessage({ type: 'error', text: 'Failed to load settings' });
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadSettings();
  }, [loadSettings]);

  const saveAutoApproval = async () => {
    if (!autoApproval) return;
    setSaving(true);
    setMessage(null);
    try {
      const response = await fetch(`${API_BASE}/admin/settings/auto-approval`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(autoApproval),
      });
      if (response.ok) {
        setMessage({ type: 'success', text: 'Auto-approval settings saved' });
      } else {
        setMessage({ type: 'error', text: 'Failed to save settings' });
      }
    } catch {
      setMessage({ type: 'error', text: 'Failed to save settings' });
    } finally {
      setSaving(false);
    }
  };

  const saveDuplicate = async () => {
    if (!duplicate) return;
    setSaving(true);
    setMessage(null);
    try {
      const response = await fetch(`${API_BASE}/admin/settings/duplicate`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(duplicate),
      });
      if (response.ok) {
        setMessage({ type: 'success', text: 'Duplicate detection settings saved' });
      } else {
        setMessage({ type: 'error', text: 'Failed to save settings' });
      }
    } catch {
      setMessage({ type: 'error', text: 'Failed to save settings' });
    } finally {
      setSaving(false);
    }
  };

  const savePipeline = async () => {
    if (!pipeline) return;
    setSaving(true);
    setMessage(null);
    try {
      const response = await fetch(`${API_BASE}/admin/settings/pipeline`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(pipeline),
      });
      if (response.ok) {
        setMessage({ type: 'success', text: 'Pipeline settings saved' });
      } else {
        setMessage({ type: 'error', text: 'Failed to save settings' });
      }
    } catch {
      setMessage({ type: 'error', text: 'Failed to save settings' });
    } finally {
      setSaving(false);
    }
  };

  const addFeed = async () => {
    setSaving(true);
    try {
      const response = await fetch(`${API_BASE}/admin/feeds`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(newFeed),
      });
      if (response.ok) {
        setNewFeed({ name: '', url: '', interval_minutes: 60 });
        setShowAddFeed(false);
        loadSettings();
        setMessage({ type: 'success', text: 'Feed added' });
      }
    } catch {
      setMessage({ type: 'error', text: 'Failed to add feed' });
    } finally {
      setSaving(false);
    }
  };

  const deleteFeed = async (feedId: string) => {
    if (!confirm('Delete this feed?')) return;
    try {
      await fetch(`${API_BASE}/admin/feeds/${feedId}`, { method: 'DELETE' });
      loadSettings();
    } catch {
      setMessage({ type: 'error', text: 'Failed to delete feed' });
    }
  };

  const toggleFeed = async (feedId: string, active: boolean) => {
    try {
      await fetch(`${API_BASE}/admin/feeds/${feedId}/toggle`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ active }),
      });
      loadSettings();
    } catch {
      setMessage({ type: 'error', text: 'Failed to toggle feed' });
    }
  };

  if (loading) {
    return <div className="admin-loading">Loading settings...</div>;
  }

  return (
    <div className="settings-panel">
      <div className="settings-header">
        <h2>Settings</h2>
        {onClose && (
          <button className="admin-close-btn" onClick={onClose}>&times;</button>
        )}
      </div>

      {message && (
        <div className={`settings-message ${message.type}`}>
          {message.text}
        </div>
      )}

      <div className="settings-tabs">
        {(['auto-approval', 'duplicate', 'pipeline', 'feeds'] as const).map(tab => (
          <button
            key={tab}
            className={`settings-tab ${activeTab === tab ? 'active' : ''}`}
            onClick={() => setActiveTab(tab)}
          >
            {tab === 'auto-approval' && 'Auto-Approval'}
            {tab === 'duplicate' && 'Duplicate Detection'}
            {tab === 'pipeline' && 'Pipeline'}
            {tab === 'feeds' && 'RSS Feeds'}
          </button>
        ))}
      </div>

      <div className="settings-content">
        {activeTab === 'auto-approval' && autoApproval && (
          <div className="settings-section">
            <h3>Auto-Approval Thresholds</h3>

            <div className="settings-group">
              <label>Minimum Confidence for Auto-Approve</label>
              <div className="slider-row">
                <input
                  type="range"
                  min="0"
                  max="100"
                  value={autoApproval.min_confidence_auto_approve * 100}
                  onChange={e => setAutoApproval({
                    ...autoApproval,
                    min_confidence_auto_approve: parseInt(e.target.value) / 100
                  })}
                />
                <span className="slider-value">{(autoApproval.min_confidence_auto_approve * 100).toFixed(0)}%</span>
              </div>
            </div>

            <div className="settings-group">
              <label>Enforcement Category Threshold (Higher Scrutiny)</label>
              <div className="slider-row">
                <input
                  type="range"
                  min="0"
                  max="100"
                  value={autoApproval.enforcement_confidence_threshold * 100}
                  onChange={e => setAutoApproval({
                    ...autoApproval,
                    enforcement_confidence_threshold: parseInt(e.target.value) / 100
                  })}
                />
                <span className="slider-value">{(autoApproval.enforcement_confidence_threshold * 100).toFixed(0)}%</span>
              </div>
            </div>

            <div className="settings-group">
              <label>Crime Category Threshold</label>
              <div className="slider-row">
                <input
                  type="range"
                  min="0"
                  max="100"
                  value={autoApproval.crime_confidence_threshold * 100}
                  onChange={e => setAutoApproval({
                    ...autoApproval,
                    crime_confidence_threshold: parseInt(e.target.value) / 100
                  })}
                />
                <span className="slider-value">{(autoApproval.crime_confidence_threshold * 100).toFixed(0)}%</span>
              </div>
            </div>

            <div className="settings-group">
              <label>Minimum Confidence for Review</label>
              <div className="slider-row">
                <input
                  type="range"
                  min="0"
                  max="100"
                  value={autoApproval.min_confidence_review * 100}
                  onChange={e => setAutoApproval({
                    ...autoApproval,
                    min_confidence_review: parseInt(e.target.value) / 100
                  })}
                />
                <span className="slider-value">{(autoApproval.min_confidence_review * 100).toFixed(0)}%</span>
              </div>
            </div>

            <div className="settings-group">
              <label>Auto-Reject Below</label>
              <div className="slider-row">
                <input
                  type="range"
                  min="0"
                  max="100"
                  value={autoApproval.auto_reject_below * 100}
                  onChange={e => setAutoApproval({
                    ...autoApproval,
                    auto_reject_below: parseInt(e.target.value) / 100
                  })}
                />
                <span className="slider-value">{(autoApproval.auto_reject_below * 100).toFixed(0)}%</span>
              </div>
            </div>

            <h3>Behavior</h3>

            <div className="settings-toggle-group">
              <label className="toggle-label">
                <input
                  type="checkbox"
                  checked={autoApproval.enable_auto_approve}
                  onChange={e => setAutoApproval({
                    ...autoApproval,
                    enable_auto_approve: e.target.checked
                  })}
                />
                <span>Enable Auto-Approve</span>
              </label>

              <label className="toggle-label">
                <input
                  type="checkbox"
                  checked={autoApproval.enable_auto_reject}
                  onChange={e => setAutoApproval({
                    ...autoApproval,
                    enable_auto_reject: e.target.checked
                  })}
                />
                <span>Enable Auto-Reject</span>
              </label>
            </div>

            <div className="settings-actions">
              <button className="action-btn primary" onClick={saveAutoApproval} disabled={saving}>
                {saving ? 'Saving...' : 'Save Auto-Approval Settings'}
              </button>
            </div>
          </div>
        )}

        {activeTab === 'duplicate' && duplicate && (
          <div className="settings-section">
            <h3>Similarity Thresholds</h3>

            <div className="settings-group">
              <label>Title Similarity Threshold</label>
              <div className="slider-row">
                <input
                  type="range"
                  min="0"
                  max="100"
                  value={duplicate.title_similarity_threshold * 100}
                  onChange={e => setDuplicate({
                    ...duplicate,
                    title_similarity_threshold: parseInt(e.target.value) / 100
                  })}
                />
                <span className="slider-value">{(duplicate.title_similarity_threshold * 100).toFixed(0)}%</span>
              </div>
            </div>

            <div className="settings-group">
              <label>Content Similarity Threshold</label>
              <div className="slider-row">
                <input
                  type="range"
                  min="0"
                  max="100"
                  value={duplicate.content_similarity_threshold * 100}
                  onChange={e => setDuplicate({
                    ...duplicate,
                    content_similarity_threshold: parseInt(e.target.value) / 100
                  })}
                />
                <span className="slider-value">{(duplicate.content_similarity_threshold * 100).toFixed(0)}%</span>
              </div>
            </div>

            <div className="settings-group">
              <label>Entity Match Date Window (days)</label>
              <input
                type="number"
                min="1"
                max="365"
                value={duplicate.entity_match_date_window}
                onChange={e => setDuplicate({
                  ...duplicate,
                  entity_match_date_window: parseInt(e.target.value) || 30
                })}
                className="settings-input"
              />
            </div>

            <h3>Detection Strategies</h3>

            <div className="settings-toggle-group">
              <label className="toggle-label">
                <input
                  type="checkbox"
                  checked={duplicate.enable_url_match}
                  onChange={e => setDuplicate({
                    ...duplicate,
                    enable_url_match: e.target.checked
                  })}
                />
                <span>URL Matching</span>
              </label>

              <label className="toggle-label">
                <input
                  type="checkbox"
                  checked={duplicate.enable_title_match}
                  onChange={e => setDuplicate({
                    ...duplicate,
                    enable_title_match: e.target.checked
                  })}
                />
                <span>Title Matching</span>
              </label>

              <label className="toggle-label">
                <input
                  type="checkbox"
                  checked={duplicate.enable_content_match}
                  onChange={e => setDuplicate({
                    ...duplicate,
                    enable_content_match: e.target.checked
                  })}
                />
                <span>Content Matching</span>
              </label>

              <label className="toggle-label">
                <input
                  type="checkbox"
                  checked={duplicate.enable_entity_match}
                  onChange={e => setDuplicate({
                    ...duplicate,
                    enable_entity_match: e.target.checked
                  })}
                />
                <span>Entity Matching</span>
              </label>
            </div>

            <div className="settings-actions">
              <button className="action-btn primary" onClick={saveDuplicate} disabled={saving}>
                {saving ? 'Saving...' : 'Save Duplicate Detection Settings'}
              </button>
            </div>
          </div>
        )}

        {activeTab === 'pipeline' && pipeline && (
          <div className="settings-section">
            <h3>Pipeline Features</h3>

            <div className="settings-toggle-group">
              <label className="toggle-label">
                <input
                  type="checkbox"
                  checked={pipeline.enable_llm_extraction}
                  onChange={e => setPipeline({
                    ...pipeline,
                    enable_llm_extraction: e.target.checked
                  })}
                />
                <span>Enable LLM Extraction</span>
              </label>

              <label className="toggle-label">
                <input
                  type="checkbox"
                  checked={pipeline.enable_duplicate_detection}
                  onChange={e => setPipeline({
                    ...pipeline,
                    enable_duplicate_detection: e.target.checked
                  })}
                />
                <span>Enable Duplicate Detection</span>
              </label>

              <label className="toggle-label">
                <input
                  type="checkbox"
                  checked={pipeline.enable_auto_approval}
                  onChange={e => setPipeline({
                    ...pipeline,
                    enable_auto_approval: e.target.checked
                  })}
                />
                <span>Enable Auto-Approval</span>
              </label>
            </div>

            <h3>Batch Processing</h3>

            <div className="settings-group">
              <label>Batch Size</label>
              <input
                type="number"
                min="1"
                max="500"
                value={pipeline.batch_size}
                onChange={e => setPipeline({
                  ...pipeline,
                  batch_size: parseInt(e.target.value) || 50
                })}
                className="settings-input"
              />
            </div>

            <div className="settings-group">
              <label>Delay Between Articles (ms)</label>
              <input
                type="number"
                min="0"
                max="5000"
                value={pipeline.delay_between_articles_ms}
                onChange={e => setPipeline({
                  ...pipeline,
                  delay_between_articles_ms: parseInt(e.target.value) || 500
                })}
                className="settings-input"
              />
            </div>

            <div className="settings-group">
              <label>Max Article Length (chars)</label>
              <input
                type="number"
                min="1000"
                max="100000"
                value={pipeline.max_article_length}
                onChange={e => setPipeline({
                  ...pipeline,
                  max_article_length: parseInt(e.target.value) || 15000
                })}
                className="settings-input"
              />
            </div>

            <div className="settings-group">
              <label>Default Source Tier</label>
              <select
                value={pipeline.default_source_tier}
                onChange={e => setPipeline({
                  ...pipeline,
                  default_source_tier: parseInt(e.target.value)
                })}
                className="settings-select"
              >
                <option value={1}>Tier 1 (Official)</option>
                <option value={2}>Tier 2 (Investigative)</option>
                <option value={3}>Tier 3 (News)</option>
                <option value={4}>Tier 4 (Ad-hoc)</option>
              </select>
            </div>

            <div className="settings-actions">
              <button className="action-btn primary" onClick={savePipeline} disabled={saving}>
                {saving ? 'Saving...' : 'Save Pipeline Settings'}
              </button>
            </div>
          </div>
        )}

        {activeTab === 'feeds' && (
          <div className="settings-section">
            <div className="section-header">
              <h3>RSS Feeds</h3>
              <button className="action-btn" onClick={() => setShowAddFeed(true)}>
                Add Feed
              </button>
            </div>

            {showAddFeed && (
              <div className="add-feed-form">
                <div className="settings-group">
                  <label>Feed Name</label>
                  <input
                    type="text"
                    value={newFeed.name}
                    onChange={e => setNewFeed({ ...newFeed, name: e.target.value })}
                    className="settings-input"
                    placeholder="e.g., AP News Immigration"
                  />
                </div>
                <div className="settings-group">
                  <label>Feed URL</label>
                  <input
                    type="url"
                    value={newFeed.url}
                    onChange={e => setNewFeed({ ...newFeed, url: e.target.value })}
                    className="settings-input"
                    placeholder="https://example.com/feed.rss"
                  />
                </div>
                <div className="settings-group">
                  <label>Fetch Interval (minutes)</label>
                  <input
                    type="number"
                    min="5"
                    max="1440"
                    value={newFeed.interval_minutes}
                    onChange={e => setNewFeed({ ...newFeed, interval_minutes: parseInt(e.target.value) || 60 })}
                    className="settings-input"
                  />
                </div>
                <div className="form-actions">
                  <button className="action-btn primary" onClick={addFeed} disabled={saving}>
                    {saving ? 'Adding...' : 'Add Feed'}
                  </button>
                  <button className="action-btn" onClick={() => setShowAddFeed(false)}>
                    Cancel
                  </button>
                </div>
              </div>
            )}

            <div className="feeds-list">
              {feeds.length === 0 ? (
                <p className="no-data">No feeds configured</p>
              ) : (
                feeds.map(feed => (
                  <div key={feed.id || feed.name} className="feed-item">
                    <div className="feed-info">
                      <div className="feed-name">{feed.name}</div>
                      <div className="feed-url">{feed.url}</div>
                      {feed.last_fetched && (
                        <div className="feed-meta">
                          Last fetched: {new Date(feed.last_fetched).toLocaleString()}
                        </div>
                      )}
                      {feed.interval_minutes && (
                        <div className="feed-meta">
                          Interval: {feed.interval_minutes} minutes
                        </div>
                      )}
                    </div>
                    <div className="feed-actions">
                      {feed.id && (
                        <>
                          <label className="toggle-label small">
                            <input
                              type="checkbox"
                              checked={feed.active}
                              onChange={e => toggleFeed(feed.id, e.target.checked)}
                            />
                            <span>Active</span>
                          </label>
                          <button
                            className="action-btn small reject"
                            onClick={() => deleteFeed(feed.id)}
                          >
                            Delete
                          </button>
                        </>
                      )}
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

export default SettingsPanel;
