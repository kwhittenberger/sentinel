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

interface EventClusteringSettings {
  max_distance_km: number;
  require_coordinates: boolean;
  max_time_window_days: number;
  require_same_incident_type: boolean;
  require_same_category: boolean;
  min_cluster_size: number;
  min_confidence_threshold: number;
  enable_ai_similarity: boolean;
  ai_similarity_threshold: number;
  enable_actor_matching: boolean;
}

interface LLMStageConfig {
  provider: string;
  model: string;
  max_tokens: number;
  enabled: boolean;
}

type LLMStageKey = 'triage' | 'extraction_universal' | 'extraction_async' | 'extraction' | 'pipeline_extraction' | 'relevance_ai' | 'enrichment_reextract';

interface LLMSettings {
  default_provider: string;
  default_model: string;
  fallback_provider: string;
  fallback_model: string;
  ollama_base_url: string;
  triage: LLMStageConfig;
  extraction_universal: LLMStageConfig;
  extraction_async: LLMStageConfig;
  extraction: LLMStageConfig;
  pipeline_extraction: LLMStageConfig;
  relevance_ai: LLMStageConfig;
  enrichment_reextract: LLMStageConfig;
}

interface ProviderStatus {
  [name: string]: { available: boolean; name: string };
}

interface Feed {
  id: string;
  name: string;
  url: string;
  source_type: string;
  tier: number;
  fetcher_class?: string;
  interval_minutes: number;
  active: boolean;
  last_fetched?: string;
  last_error?: string;
}

interface SettingsPanelProps {
  onClose?: () => void;
}

export function SettingsPanel({ onClose }: SettingsPanelProps) {
  const [activeTab, setActiveTab] = useState<'auto-approval' | 'duplicate' | 'pipeline' | 'clustering' | 'feeds' | 'llm'>('auto-approval');
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null);

  const [autoApproval, setAutoApproval] = useState<AutoApprovalSettings | null>(null);
  const [duplicate, setDuplicate] = useState<DuplicateSettings | null>(null);
  const [pipeline, setPipeline] = useState<PipelineSettings | null>(null);
  const [clustering, setClustering] = useState<EventClusteringSettings | null>(null);
  const [feeds, setFeeds] = useState<Feed[]>([]);
  const [showAddFeed, setShowAddFeed] = useState(false);
  const [newFeed, setNewFeed] = useState({ name: '', url: '', interval_minutes: 60 });
  const [llm, setLlm] = useState<LLMSettings | null>(null);
  const [providerStatus, setProviderStatus] = useState<ProviderStatus>({});
  const [availableModels, setAvailableModels] = useState<Record<string, string[]>>({});

  const loadSettings = useCallback(async () => {
    setLoading(true);
    try {
      const response = await fetch(`${API_BASE}/admin/settings`);
      if (response.ok) {
        const data = await response.json();
        setAutoApproval(data.auto_approval);
        setDuplicate(data.duplicate_detection);
        setPipeline(data.pipeline);
        setClustering(data.event_clustering);
      }

      const feedsResponse = await fetch(`${API_BASE}/admin/feeds`);
      if (feedsResponse.ok) {
        const feedsData = await feedsResponse.json();
        setFeeds(feedsData.feeds || []);
      }

      // Load LLM settings
      const llmResponse = await fetch(`${API_BASE}/admin/settings/llm`);
      if (llmResponse.ok) {
        setLlm(await llmResponse.json());
      }

      // Load provider status
      const statusResponse = await fetch(`${API_BASE}/admin/llm/providers`);
      if (statusResponse.ok) {
        const statusData = await statusResponse.json();
        setProviderStatus(statusData.providers || {});
      }

      // Load available models
      const modelsResponse = await fetch(`${API_BASE}/admin/llm/models`);
      if (modelsResponse.ok) {
        const modelsData = await modelsResponse.json();
        setAvailableModels(modelsData.models || {});
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

  const saveClustering = async () => {
    if (!clustering) return;
    setSaving(true);
    setMessage(null);
    try {
      const response = await fetch(`${API_BASE}/admin/settings/event-clustering`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(clustering),
      });
      if (response.ok) {
        setMessage({ type: 'success', text: 'Event clustering settings saved' });
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

  const saveLlm = async () => {
    if (!llm) return;
    setSaving(true);
    setMessage(null);
    try {
      const response = await fetch(`${API_BASE}/admin/settings/llm`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(llm),
      });
      if (response.ok) {
        setMessage({ type: 'success', text: 'LLM provider settings saved' });
        // Refresh provider status and models after save
        const statusResponse = await fetch(`${API_BASE}/admin/llm/providers`);
        if (statusResponse.ok) {
          const statusData = await statusResponse.json();
          setProviderStatus(statusData.providers || {});
        }
        const modelsResponse = await fetch(`${API_BASE}/admin/llm/models`);
        if (modelsResponse.ok) {
          const modelsData = await modelsResponse.json();
          setAvailableModels(modelsData.models || {});
        }
      } else {
        setMessage({ type: 'error', text: 'Failed to save LLM settings' });
      }
    } catch {
      setMessage({ type: 'error', text: 'Failed to save LLM settings' });
    } finally {
      setSaving(false);
    }
  };

  const updateStageConfig = (stageKey: LLMStageKey, field: string, value: string | number | boolean) => {
    if (!llm) return;
    setLlm({
      ...llm,
      [stageKey]: {
        ...llm[stageKey],
        [field]: value,
      },
    });
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
          <button className="admin-close-btn" onClick={onClose} aria-label="Close settings">&times;</button>
        )}
      </div>

      {message && (
        <div className={`settings-message ${message.type}`}>
          {message.text}
        </div>
      )}

      <div className="settings-tabs">
        {(['auto-approval', 'duplicate', 'pipeline', 'clustering', 'feeds', 'llm'] as const).map(tab => (
          <button
            key={tab}
            className={`settings-tab ${activeTab === tab ? 'active' : ''}`}
            onClick={() => setActiveTab(tab)}
          >
            {tab === 'auto-approval' && 'Auto-Approval'}
            {tab === 'duplicate' && 'Duplicate Detection'}
            {tab === 'pipeline' && 'Pipeline'}
            {tab === 'clustering' && 'Event Clustering'}
            {tab === 'feeds' && 'Data Sources'}
            {tab === 'llm' && 'LLM Providers'}
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

        {activeTab === 'clustering' && clustering && (
          <div className="settings-section">
            <h3>Geographic Clustering</h3>

            <div className="settings-group">
              <label>Maximum Distance (km)</label>
              <div className="slider-row">
                <input
                  type="range"
                  min="1"
                  max="200"
                  value={clustering.max_distance_km}
                  onChange={e => setClustering({
                    ...clustering,
                    max_distance_km: parseFloat(e.target.value)
                  })}
                />
                <span>{clustering.max_distance_km} km</span>
              </div>
              <p className="settings-hint">Max distance between incidents to consider them related</p>
            </div>

            <label className="toggle-label">
              <input
                type="checkbox"
                checked={clustering.require_coordinates}
                onChange={e => setClustering({
                  ...clustering,
                  require_coordinates: e.target.checked
                })}
              />
              <span>Require Coordinates (if unchecked, falls back to city/state matching)</span>
            </label>

            <h3>Temporal Clustering</h3>

            <div className="settings-group">
              <label>Maximum Time Window (days)</label>
              <div className="slider-row">
                <input
                  type="range"
                  min="1"
                  max="30"
                  value={clustering.max_time_window_days}
                  onChange={e => setClustering({
                    ...clustering,
                    max_time_window_days: parseInt(e.target.value)
                  })}
                />
                <span>{clustering.max_time_window_days} days</span>
              </div>
              <p className="settings-hint">Max days apart for incidents to be considered related</p>
            </div>

            <h3>Matching Criteria</h3>

            <div className="settings-toggle-group">
              <label className="toggle-label">
                <input
                  type="checkbox"
                  checked={clustering.require_same_incident_type}
                  onChange={e => setClustering({
                    ...clustering,
                    require_same_incident_type: e.target.checked
                  })}
                />
                <span>Require Same Incident Type</span>
              </label>

              <label className="toggle-label">
                <input
                  type="checkbox"
                  checked={clustering.require_same_category}
                  onChange={e => setClustering({
                    ...clustering,
                    require_same_category: e.target.checked
                  })}
                />
                <span>Require Same Category (enforcement/crime)</span>
              </label>

              <label className="toggle-label">
                <input
                  type="checkbox"
                  checked={clustering.enable_actor_matching}
                  onChange={e => setClustering({
                    ...clustering,
                    enable_actor_matching: e.target.checked
                  })}
                />
                <span>Consider Shared Actors</span>
              </label>
            </div>

            <h3>Cluster Settings</h3>

            <div className="settings-group">
              <label>Minimum Cluster Size</label>
              <input
                type="number"
                min="2"
                max="10"
                value={clustering.min_cluster_size}
                onChange={e => setClustering({
                  ...clustering,
                  min_cluster_size: parseInt(e.target.value) || 2
                })}
                className="settings-input"
              />
              <p className="settings-hint">Minimum incidents needed to form an event</p>
            </div>

            <div className="settings-group">
              <label>Minimum Confidence Threshold</label>
              <div className="slider-row">
                <input
                  type="range"
                  min="0"
                  max="100"
                  value={clustering.min_confidence_threshold * 100}
                  onChange={e => setClustering({
                    ...clustering,
                    min_confidence_threshold: parseInt(e.target.value) / 100
                  })}
                />
                <span>{(clustering.min_confidence_threshold * 100).toFixed(0)}%</span>
              </div>
            </div>

            <h3>AI-Assisted Clustering (Future)</h3>

            <div className="settings-toggle-group">
              <label className="toggle-label">
                <input
                  type="checkbox"
                  checked={clustering.enable_ai_similarity}
                  onChange={e => setClustering({
                    ...clustering,
                    enable_ai_similarity: e.target.checked
                  })}
                  disabled
                />
                <span>Enable AI Similarity Analysis (coming soon)</span>
              </label>
            </div>

            {clustering.enable_ai_similarity && (
              <div className="settings-group">
                <label>AI Similarity Threshold</label>
                <div className="slider-row">
                  <input
                    type="range"
                    min="0"
                    max="100"
                    value={clustering.ai_similarity_threshold * 100}
                    onChange={e => setClustering({
                      ...clustering,
                      ai_similarity_threshold: parseInt(e.target.value) / 100
                    })}
                  />
                  <span>{(clustering.ai_similarity_threshold * 100).toFixed(0)}%</span>
                </div>
              </div>
            )}

            <div className="settings-actions">
              <button className="action-btn primary" onClick={saveClustering} disabled={saving}>
                {saving ? 'Saving...' : 'Save Clustering Settings'}
              </button>
            </div>
          </div>
        )}

        {activeTab === 'llm' && llm && (
          <div className="settings-section">
            <h3>Provider Status</h3>
            <div className="provider-status-grid">
              {Object.entries(providerStatus).map(([name, status]) => (
                <div key={name} className="provider-status-item">
                  <span className={`status-dot ${status.available ? 'available' : 'unavailable'}`} />
                  <span className="provider-name">{name}</span>
                  <span className="provider-availability">
                    {status.available ? 'Available' : 'Unavailable'}
                  </span>
                </div>
              ))}
            </div>

            <h3>Global Defaults</h3>

            <div className="settings-group">
              <label>Default Provider</label>
              <select
                value={llm.default_provider}
                onChange={e => setLlm({ ...llm, default_provider: e.target.value })}
                className="settings-select"
              >
                <option value="anthropic">Anthropic (Claude)</option>
                <option value="ollama">Ollama (Local)</option>
              </select>
            </div>

            <div className="settings-group">
              <label>Default Model</label>
              <input
                type="text"
                value={llm.default_model}
                onChange={e => setLlm({ ...llm, default_model: e.target.value })}
                className="settings-input"
                placeholder="e.g., claude-sonnet-4-20250514"
              />
            </div>

            <div className="settings-group">
              <label>Fallback Provider</label>
              <select
                value={llm.fallback_provider}
                onChange={e => setLlm({ ...llm, fallback_provider: e.target.value })}
                className="settings-select"
              >
                <option value="anthropic">Anthropic (Claude)</option>
                <option value="ollama">Ollama (Local)</option>
              </select>
            </div>

            <div className="settings-group">
              <label>Fallback Model</label>
              <input
                type="text"
                value={llm.fallback_model}
                onChange={e => setLlm({ ...llm, fallback_model: e.target.value })}
                className="settings-input"
              />
            </div>

            <div className="settings-group">
              <label>Ollama Base URL</label>
              <input
                type="text"
                value={llm.ollama_base_url}
                onChange={e => setLlm({ ...llm, ollama_base_url: e.target.value })}
                className="settings-input"
                placeholder="http://localhost:11434/v1"
              />
            </div>

            <h3>Per-Stage Configuration</h3>
            <p className="settings-hint">Override provider and model for each pipeline stage.</p>

            <div className="llm-stages-table">
              <table>
                <thead>
                  <tr>
                    <th>Stage</th>
                    <th>Provider</th>
                    <th>Model</th>
                    <th>Max Tokens</th>
                  </tr>
                </thead>
                <tbody>
                  {([
                    { key: 'triage', label: 'Triage' },
                    { key: 'extraction_universal', label: 'Universal Extraction' },
                    { key: 'extraction_async', label: 'Async Extraction' },
                    { key: 'extraction', label: 'Extraction' },
                    { key: 'pipeline_extraction', label: 'Pipeline Extraction' },
                    { key: 'relevance_ai', label: 'AI Relevance' },
                    { key: 'enrichment_reextract', label: 'Enrichment Re-extract' },
                  ] as const).map(stage => {
                    const cfg = llm[stage.key];
                    if (!cfg) return null;
                    const providerModels = availableModels[cfg.provider] || [];
                    return (
                      <tr key={stage.key}>
                        <td>{stage.label}</td>
                        <td>
                          <select
                            value={cfg.provider}
                            onChange={e => updateStageConfig(stage.key, 'provider', e.target.value)}
                            className="settings-select-sm"
                          >
                            <option value="anthropic">Anthropic</option>
                            <option value="ollama">Ollama</option>
                          </select>
                        </td>
                        <td>
                          {providerModels.length > 0 ? (
                            <select
                              value={cfg.model}
                              onChange={e => updateStageConfig(stage.key, 'model', e.target.value)}
                              className="settings-select-sm"
                            >
                              {providerModels.map(m => (
                                <option key={m} value={m}>{m}</option>
                              ))}
                              {!providerModels.includes(cfg.model) && (
                                <option value={cfg.model}>{cfg.model}</option>
                              )}
                            </select>
                          ) : (
                            <input
                              type="text"
                              value={cfg.model}
                              onChange={e => updateStageConfig(stage.key, 'model', e.target.value)}
                              className="settings-input-sm"
                            />
                          )}
                        </td>
                        <td>
                          <input
                            type="number"
                            min="100"
                            max="16000"
                            value={cfg.max_tokens}
                            onChange={e => updateStageConfig(stage.key, 'max_tokens', parseInt(e.target.value) || 500)}
                            className="settings-input-sm"
                          />
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>

            <div className="settings-actions">
              <button className="action-btn primary" onClick={saveLlm} disabled={saving}>
                {saving ? 'Saving...' : 'Save LLM Settings'}
              </button>
            </div>
          </div>
        )}

        {activeTab === 'feeds' && (
          <div className="settings-section">
            <div className="section-header">
              <h3>Data Sources</h3>
              <button className="action-btn" onClick={() => setShowAddFeed(true)}>
                Add Source
              </button>
            </div>

            {showAddFeed && (
              <div className="add-feed-form">
                <div className="settings-group">
                  <label>Source Name</label>
                  <input
                    type="text"
                    value={newFeed.name}
                    onChange={e => setNewFeed({ ...newFeed, name: e.target.value })}
                    className="settings-input"
                    placeholder="e.g., AP News Immigration"
                  />
                </div>
                <div className="settings-group">
                  <label>URL</label>
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
                    max="10080"
                    value={newFeed.interval_minutes}
                    onChange={e => setNewFeed({ ...newFeed, interval_minutes: parseInt(e.target.value) || 60 })}
                    className="settings-input"
                  />
                </div>
                <div className="form-actions">
                  <button className="action-btn primary" onClick={addFeed} disabled={saving}>
                    {saving ? 'Adding...' : 'Add Source'}
                  </button>
                  <button className="action-btn" onClick={() => setShowAddFeed(false)}>
                    Cancel
                  </button>
                </div>
              </div>
            )}

            <div className="feeds-list">
              {feeds.length === 0 ? (
                <p className="no-data">No sources configured</p>
              ) : (
                feeds.map(feed => (
                  <div key={feed.id || feed.name} className="feed-item">
                    <div className="feed-info">
                      <div className="feed-name">{feed.name}</div>
                      <div className="feed-url">{feed.url}</div>
                      <div className="feed-meta">
                        {feed.source_type || 'news'} &middot; Tier {feed.tier || 3} &middot; {feed.interval_minutes}m interval
                      </div>
                      {feed.last_fetched && (
                        <div className="feed-meta">
                          Last fetched: {new Date(feed.last_fetched).toLocaleString()}
                        </div>
                      )}
                      {feed.last_error && (
                        <div className="feed-meta" style={{ color: '#e74c3c' }}>
                          Error: {feed.last_error}
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
