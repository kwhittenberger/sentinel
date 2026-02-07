import { useState, useEffect, useCallback } from 'react';
import { SplitPane } from './SplitPane';
import type { Prompt, PromptType, PromptStatus, PromptExecutionStats } from './types';

interface PromptManagerProps {
  onRefresh?: () => void;
}

const API_BASE = '';

const PROMPT_TYPES: PromptType[] = ['extraction', 'classification', 'entity_resolution', 'pattern_detection', 'summarization', 'analysis'];
const PROMPT_STATUSES: PromptStatus[] = ['draft', 'active', 'testing', 'deprecated', 'archived'];

export function PromptManager({ onRefresh }: PromptManagerProps) {
  const [prompts, setPrompts] = useState<Prompt[]>([]);
  const [selectedPrompt, setSelectedPrompt] = useState<Prompt | null>(null);
  const [executionStats, setExecutionStats] = useState<PromptExecutionStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showCreateForm, setShowCreateForm] = useState(false);
  const [filterType, setFilterType] = useState<string>('');
  const [filterStatus, setFilterStatus] = useState<string>('');
  const [activeTab, setActiveTab] = useState<'editor' | 'versions' | 'stats'>('editor');

  // Form states
  const [formData, setFormData] = useState({
    name: '',
    slug: '',
    description: '',
    prompt_type: 'extraction' as PromptType,
    system_prompt: '',
    user_prompt_template: '',
    model_name: 'claude-sonnet-4-20250514',
    max_tokens: 2000,
    temperature: 0.0,
  });

  // Edit states
  const [editData, setEditData] = useState<{
    system_prompt: string;
    user_prompt_template: string;
    description: string;
  } | null>(null);

  const loadPrompts = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (filterType) params.append('prompt_type', filterType);
      if (filterStatus) params.append('status', filterStatus);

      const res = await fetch(`${API_BASE}/api/admin/prompts?${params}`);
      if (!res.ok) throw new Error('Failed to load prompts');
      const data = await res.json();
      setPrompts(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load prompts');
    } finally {
      setLoading(false);
    }
  }, [filterType, filterStatus]);

  const loadPromptDetails = useCallback(async (promptId: string) => {
    try {
      const res = await fetch(`${API_BASE}/api/admin/prompts/${promptId}`);
      if (!res.ok) throw new Error('Failed to load prompt details');
      const data = await res.json();
      setSelectedPrompt(data);
      setEditData({
        system_prompt: data.system_prompt,
        user_prompt_template: data.user_prompt_template,
        description: data.description || '',
      });

      // Load execution stats
      const statsRes = await fetch(`${API_BASE}/api/admin/prompts/${promptId}/executions`);
      if (statsRes.ok) {
        const stats = await statsRes.json();
        setExecutionStats(stats);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load prompt details');
    }
  }, []);

  useEffect(() => {
    loadPrompts();
  }, [loadPrompts]);

  const handleCreatePrompt = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    setError(null);

    try {
      const res = await fetch(`${API_BASE}/api/admin/prompts`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(formData),
      });

      if (!res.ok) throw new Error('Failed to create prompt');

      const data = await res.json();
      setShowCreateForm(false);
      setFormData({
        name: '',
        slug: '',
        description: '',
        prompt_type: 'extraction',
        system_prompt: '',
        user_prompt_template: '',
        model_name: 'claude-sonnet-4-20250514',
        max_tokens: 2000,
        temperature: 0.0,
      });
      await loadPrompts();
      await loadPromptDetails(data.id);
      onRefresh?.();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create prompt');
    } finally {
      setSaving(false);
    }
  };

  const handleSaveVersion = async () => {
    if (!selectedPrompt || !editData) return;

    // Check if anything changed
    if (
      editData.system_prompt === selectedPrompt.system_prompt &&
      editData.user_prompt_template === selectedPrompt.user_prompt_template &&
      editData.description === (selectedPrompt.description || '')
    ) {
      setError('No changes to save');
      return;
    }

    setSaving(true);
    setError(null);

    try {
      const res = await fetch(`${API_BASE}/api/admin/prompts/${selectedPrompt.id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(editData),
      });

      if (!res.ok) throw new Error('Failed to save version');

      const data = await res.json();
      await loadPromptDetails(data.id);
      await loadPrompts();
      onRefresh?.();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to save version');
    } finally {
      setSaving(false);
    }
  };

  const handleActivate = async (promptId: string) => {
    setSaving(true);
    setError(null);

    try {
      const res = await fetch(`${API_BASE}/api/admin/prompts/${promptId}/activate`, {
        method: 'POST',
      });

      if (!res.ok) throw new Error('Failed to activate prompt');

      await loadPromptDetails(promptId);
      await loadPrompts();
      onRefresh?.();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to activate prompt');
    } finally {
      setSaving(false);
    }
  };

  if (loading && prompts.length === 0) {
    return <div className="admin-loading">Loading prompts...</div>;
  }

  return (
    <div className="admin-page">
      <div className="page-header">
        <h2>Prompt Manager</h2>
        <div className="page-actions">
          <button
            className="action-btn primary"
            onClick={() => setShowCreateForm(true)}
          >
            + Create Prompt
          </button>
        </div>
      </div>

      {error && <div className="error-banner">{error}</div>}

      {/* Filters */}
      <div className="filter-bar">
        <select value={filterType} onChange={(e) => setFilterType(e.target.value)}>
          <option value="">All Types</option>
          {PROMPT_TYPES.map((type) => (
            <option key={type} value={type}>{type}</option>
          ))}
        </select>
        <select value={filterStatus} onChange={(e) => setFilterStatus(e.target.value)}>
          <option value="">All Statuses</option>
          {PROMPT_STATUSES.map((status) => (
            <option key={status} value={status}>{status}</option>
          ))}
        </select>
      </div>

      <SplitPane
        storageKey="prompts"
        defaultLeftWidth={420}
        minLeftWidth={280}
        maxLeftWidth={700}
        left={
        <div className="list-panel">
          <div className="list-header">
            <h3>Prompts ({prompts.length})</h3>
          </div>
          <div className="list-items">
            {prompts.map((prompt) => (
              <div
                key={prompt.id}
                className={`list-item ${selectedPrompt?.id === prompt.id ? 'selected' : ''}`}
                onClick={() => loadPromptDetails(prompt.id)}
              >
                <div className="item-content">
                  <div className="item-title">{prompt.name}</div>
                  <div className="item-meta">
                    <span className={`badge ${prompt.prompt_type}`}>{prompt.prompt_type}</span>
                    <span className={`badge status-${prompt.status}`}>{prompt.status}</span>
                    <span>v{prompt.version}</span>
                  </div>
                </div>
              </div>
            ))}
            {prompts.length === 0 && (
              <div className="empty-list">No prompts found</div>
            )}
          </div>
        </div>
        }
        right={
        <div className="detail-panel">
          {selectedPrompt ? (
            <>
              <div className="detail-header">
                <div>
                  <h3>{selectedPrompt.name}</h3>
                  <div className="prompt-meta">
                    <span className={`badge ${selectedPrompt.prompt_type}`}>{selectedPrompt.prompt_type}</span>
                    <span className={`badge status-${selectedPrompt.status}`}>{selectedPrompt.status}</span>
                    <span>v{selectedPrompt.version}</span>
                    <span className="slug">{selectedPrompt.slug}</span>
                  </div>
                </div>
                <div className="header-actions">
                  {selectedPrompt.status !== 'active' && (
                    <button
                      className="action-btn primary"
                      onClick={() => handleActivate(selectedPrompt.id)}
                      disabled={saving}
                    >
                      Activate
                    </button>
                  )}
                </div>
              </div>

              <div className="detail-tabs">
                <button
                  className={`tab ${activeTab === 'editor' ? 'active' : ''}`}
                  onClick={() => setActiveTab('editor')}
                >
                  Editor
                </button>
                <button
                  className={`tab ${activeTab === 'versions' ? 'active' : ''}`}
                  onClick={() => setActiveTab('versions')}
                >
                  Versions ({selectedPrompt.version_history?.length || 0})
                </button>
                <button
                  className={`tab ${activeTab === 'stats' ? 'active' : ''}`}
                  onClick={() => setActiveTab('stats')}
                >
                  Stats
                </button>
              </div>

              <div className="detail-content">
                {activeTab === 'editor' && editData && (
                  <div className="prompt-editor">
                    <div className="form-group">
                      <label>Description</label>
                      <textarea
                        value={editData.description}
                        onChange={(e) => setEditData({ ...editData, description: e.target.value })}
                        rows={2}
                        placeholder="Brief description of this prompt"
                      />
                    </div>

                    <div className="form-group">
                      <label>System Prompt</label>
                      <textarea
                        value={editData.system_prompt}
                        onChange={(e) => setEditData({ ...editData, system_prompt: e.target.value })}
                        rows={8}
                        className="code-editor"
                      />
                    </div>

                    <div className="form-group">
                      <label>User Prompt Template</label>
                      <div className="template-hint">
                        Use {'{{variable}}'} for template variables
                      </div>
                      <textarea
                        value={editData.user_prompt_template}
                        onChange={(e) => setEditData({ ...editData, user_prompt_template: e.target.value })}
                        rows={12}
                        className="code-editor"
                      />
                    </div>

                    <div className="editor-footer">
                      <div className="model-info">
                        Model: {selectedPrompt.model_name} | Max tokens: {selectedPrompt.max_tokens} | Temp: {selectedPrompt.temperature}
                      </div>
                      <button
                        className="action-btn primary"
                        onClick={handleSaveVersion}
                        disabled={saving}
                      >
                        {saving ? 'Saving...' : 'Save as New Version'}
                      </button>
                    </div>
                  </div>
                )}

                {activeTab === 'versions' && (
                  <div className="versions-list">
                    {selectedPrompt.version_history?.map((version) => (
                      <div
                        key={version.id}
                        className={`version-item ${version.id === selectedPrompt.id ? 'current' : ''}`}
                      >
                        <div className="version-info">
                          <span className="version-number">v{version.version}</span>
                          <span className={`badge status-${version.status}`}>{version.status}</span>
                        </div>
                        <div className="version-date">
                          {new Date(version.created_at).toLocaleString()}
                        </div>
                        {version.status !== 'active' && version.id !== selectedPrompt.id && (
                          <button
                            className="action-btn small"
                            onClick={() => handleActivate(version.id)}
                            disabled={saving}
                          >
                            Activate
                          </button>
                        )}
                      </div>
                    ))}
                  </div>
                )}

                {activeTab === 'stats' && executionStats && (
                  <div className="stats-panel">
                    <div className="stats-grid">
                      <div className="stat-card">
                        <div className="stat-value">{executionStats.total_executions}</div>
                        <div className="stat-label">Total Executions</div>
                      </div>
                      <div className="stat-card success">
                        <div className="stat-value">{(executionStats.success_rate * 100).toFixed(1)}%</div>
                        <div className="stat-label">Success Rate</div>
                      </div>
                      <div className="stat-card">
                        <div className="stat-value">
                          {executionStats.avg_latency_ms ? Math.round(executionStats.avg_latency_ms) : '-'}
                        </div>
                        <div className="stat-label">Avg Latency (ms)</div>
                      </div>
                      <div className="stat-card">
                        <div className="stat-value">
                          {executionStats.avg_confidence ? (executionStats.avg_confidence * 100).toFixed(0) : '-'}%
                        </div>
                        <div className="stat-label">Avg Confidence</div>
                      </div>
                    </div>
                    <div className="token-stats">
                      <p>
                        Avg Input Tokens: {executionStats.avg_input_tokens?.toFixed(0) || '-'} |
                        Avg Output Tokens: {executionStats.avg_output_tokens?.toFixed(0) || '-'}
                      </p>
                    </div>
                  </div>
                )}
              </div>
            </>
          ) : (
            <div className="empty-state">
              <p>Select a prompt to view and edit</p>
            </div>
          )}
        </div>
        }
      />

      {/* Create Prompt Modal */}
      {showCreateForm && (
        <div className="modal-overlay" onClick={() => setShowCreateForm(false)}>
          <div className="modal large" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h3>Create New Prompt</h3>
              <button className="close-btn" onClick={() => setShowCreateForm(false)} aria-label="Close create prompt dialog">&times;</button>
            </div>
            <form onSubmit={handleCreatePrompt}>
              <div className="modal-body">
                <div className="form-row">
                  <div className="form-group">
                    <label>Name *</label>
                    <input
                      type="text"
                      value={formData.name}
                      onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                      required
                      placeholder="e.g. Vehicle Pursuit Extraction"
                    />
                  </div>
                  <div className="form-group">
                    <label>Slug *</label>
                    <input
                      type="text"
                      value={formData.slug}
                      onChange={(e) => setFormData({ ...formData, slug: e.target.value })}
                      required
                      placeholder="e.g. vehicle_pursuit_extraction"
                    />
                  </div>
                </div>

                <div className="form-row">
                  <div className="form-group">
                    <label>Prompt Type *</label>
                    <select
                      value={formData.prompt_type}
                      onChange={(e) => setFormData({ ...formData, prompt_type: e.target.value as PromptType })}
                      required
                    >
                      {PROMPT_TYPES.map((type) => (
                        <option key={type} value={type}>{type}</option>
                      ))}
                    </select>
                  </div>
                  <div className="form-group">
                    <label>Model</label>
                    <select
                      value={formData.model_name}
                      onChange={(e) => setFormData({ ...formData, model_name: e.target.value })}
                    >
                      <option value="claude-sonnet-4-20250514">claude-sonnet-4</option>
                      <option value="claude-3-5-sonnet-20241022">claude-3-5-sonnet</option>
                      <option value="claude-3-haiku-20240307">claude-3-haiku</option>
                    </select>
                  </div>
                </div>

                <div className="form-group">
                  <label>Description</label>
                  <textarea
                    value={formData.description}
                    onChange={(e) => setFormData({ ...formData, description: e.target.value })}
                    rows={2}
                  />
                </div>

                <div className="form-group">
                  <label>System Prompt *</label>
                  <textarea
                    value={formData.system_prompt}
                    onChange={(e) => setFormData({ ...formData, system_prompt: e.target.value })}
                    rows={6}
                    required
                    className="code-editor"
                    placeholder="You are an expert data extractor..."
                  />
                </div>

                <div className="form-group">
                  <label>User Prompt Template *</label>
                  <textarea
                    value={formData.user_prompt_template}
                    onChange={(e) => setFormData({ ...formData, user_prompt_template: e.target.value })}
                    rows={8}
                    required
                    className="code-editor"
                    placeholder={'ARTICLE TEXT:\n{{article_text}}\n\nExtract the incident data...'}
                  />
                </div>

                <div className="form-row">
                  <div className="form-group">
                    <label>Max Tokens</label>
                    <input
                      type="number"
                      value={formData.max_tokens}
                      onChange={(e) => setFormData({ ...formData, max_tokens: parseInt(e.target.value) })}
                      min={100}
                      max={8000}
                    />
                  </div>
                  <div className="form-group">
                    <label>Temperature</label>
                    <input
                      type="number"
                      value={formData.temperature}
                      onChange={(e) => setFormData({ ...formData, temperature: parseFloat(e.target.value) })}
                      min={0}
                      max={1}
                      step={0.1}
                    />
                  </div>
                </div>
              </div>
              <div className="modal-footer">
                <button type="button" className="action-btn" onClick={() => setShowCreateForm(false)}>
                  Cancel
                </button>
                <button type="submit" className="action-btn primary" disabled={saving}>
                  {saving ? 'Creating...' : 'Create Prompt'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

    </div>
  );
}

export default PromptManager;
