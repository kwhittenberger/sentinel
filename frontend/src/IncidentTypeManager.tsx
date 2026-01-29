import { useState, useEffect, useCallback } from 'react';
import { SplitPane } from './SplitPane';
import type { IncidentType, FieldType, PipelineStage } from './types';

interface IncidentTypeManagerProps {
  onRefresh?: () => void;
}

const API_BASE = '';

export function IncidentTypeManager({ onRefresh }: IncidentTypeManagerProps) {
  const [types, setTypes] = useState<IncidentType[]>([]);
  const [stages, setStages] = useState<PipelineStage[]>([]);
  const [selectedType, setSelectedType] = useState<IncidentType | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showCreateForm, setShowCreateForm] = useState(false);
  const [showFieldForm, setShowFieldForm] = useState(false);
  const [activeTab, setActiveTab] = useState<'details' | 'fields' | 'pipeline' | 'thresholds'>('details');

  // Form states
  const [formData, setFormData] = useState({
    name: '',
    slug: '',
    display_name: '',
    description: '',
    category: 'enforcement' as 'enforcement' | 'crime',
    icon: '',
    color: '#3b82f6',
    severity_weight: 1.0,
  });

  const [fieldFormData, setFieldFormData] = useState({
    name: '',
    display_name: '',
    field_type: 'string' as FieldType,
    description: '',
    required: false,
    enum_values: '',
    extraction_hint: '',
    display_order: 0,
  });

  const loadTypes = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/api/admin/types`);
      if (!res.ok) throw new Error('Failed to load types');
      const data = await res.json();
      setTypes(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load types');
    } finally {
      setLoading(false);
    }
  }, []);

  const loadStages = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/admin/pipeline/stages`);
      if (!res.ok) throw new Error('Failed to load stages');
      const data = await res.json();
      setStages(data);
    } catch (err) {
      console.error('Failed to load stages:', err);
    }
  }, []);

  const loadTypeDetails = useCallback(async (typeId: string) => {
    try {
      const res = await fetch(`${API_BASE}/api/admin/types/${typeId}`);
      if (!res.ok) throw new Error('Failed to load type details');
      const data = await res.json();
      setSelectedType(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load type details');
    }
  }, []);

  useEffect(() => {
    loadTypes();
    loadStages();
  }, [loadTypes, loadStages]);

  const handleCreateType = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    setError(null);

    try {
      const res = await fetch(`${API_BASE}/api/admin/types`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(formData),
      });

      if (!res.ok) throw new Error('Failed to create type');

      const data = await res.json();
      setShowCreateForm(false);
      setFormData({
        name: '',
        slug: '',
        display_name: '',
        description: '',
        category: 'enforcement',
        icon: '',
        color: '#3b82f6',
        severity_weight: 1.0,
      });
      await loadTypes();
      await loadTypeDetails(data.id);
      onRefresh?.();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create type');
    } finally {
      setSaving(false);
    }
  };

  const handleUpdateType = async (updates: Partial<IncidentType>) => {
    if (!selectedType) return;
    setSaving(true);
    setError(null);

    try {
      const res = await fetch(`${API_BASE}/api/admin/types/${selectedType.id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(updates),
      });

      if (!res.ok) throw new Error('Failed to update type');

      await loadTypeDetails(selectedType.id);
      await loadTypes();
      onRefresh?.();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to update type');
    } finally {
      setSaving(false);
    }
  };

  const handleCreateField = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedType) return;
    setSaving(true);
    setError(null);

    try {
      const fieldData = {
        ...fieldFormData,
        enum_values: fieldFormData.enum_values ? fieldFormData.enum_values.split(',').map(v => v.trim()) : undefined,
      };

      const res = await fetch(`${API_BASE}/api/admin/types/${selectedType.id}/fields`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(fieldData),
      });

      if (!res.ok) throw new Error('Failed to create field');

      setShowFieldForm(false);
      setFieldFormData({
        name: '',
        display_name: '',
        field_type: 'string',
        description: '',
        required: false,
        enum_values: '',
        extraction_hint: '',
        display_order: 0,
      });
      await loadTypeDetails(selectedType.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create field');
    } finally {
      setSaving(false);
    }
  };

  const handleUpdateThresholds = async (thresholds: Record<string, number>) => {
    await handleUpdateType({ approval_thresholds: thresholds } as Partial<IncidentType>);
  };

  if (loading) {
    return <div className="admin-loading">Loading incident types...</div>;
  }

  return (
    <div className="admin-page">
      <div className="page-header">
        <h2>Incident Types</h2>
        <div className="page-actions">
          <button
            className="action-btn primary"
            onClick={() => setShowCreateForm(true)}
          >
            + Create Type
          </button>
        </div>
      </div>

      {error && <div className="error-banner">{error}</div>}

      <SplitPane
        storageKey="incident-types"
        defaultLeftWidth={420}
        minLeftWidth={280}
        maxLeftWidth={700}
        left={
        <div className="list-panel">
          <div className="list-header">
            <h3>Types ({types.length})</h3>
          </div>
          <div className="list-items">
            {types.map((type) => (
              <div
                key={type.id}
                className={`list-item ${selectedType?.id === type.id ? 'selected' : ''}`}
                onClick={() => loadTypeDetails(type.id)}
              >
                <div className="item-icon" style={{ backgroundColor: type.color || '#6b7280' }}>
                  {type.icon || type.name[0].toUpperCase()}
                </div>
                <div className="item-content">
                  <div className="item-title">{type.display_name || type.name}</div>
                  <div className="item-meta">
                    <span className={`badge ${type.category}`}>{type.category}</span>
                    <span>{type.slug}</span>
                  </div>
                </div>
                {!type.is_active && <span className="badge inactive">Inactive</span>}
              </div>
            ))}
          </div>
        </div>
        }
        right={
        <div className="detail-panel">
          {selectedType ? (
            <>
              <div className="detail-header">
                <h3>{selectedType.display_name || selectedType.name}</h3>
                <span className={`badge ${selectedType.category}`}>{selectedType.category}</span>
              </div>

              <div className="detail-tabs">
                <button
                  className={`tab ${activeTab === 'details' ? 'active' : ''}`}
                  onClick={() => setActiveTab('details')}
                >
                  Details
                </button>
                <button
                  className={`tab ${activeTab === 'fields' ? 'active' : ''}`}
                  onClick={() => setActiveTab('fields')}
                >
                  Fields ({selectedType.fields?.length || 0})
                </button>
                <button
                  className={`tab ${activeTab === 'pipeline' ? 'active' : ''}`}
                  onClick={() => setActiveTab('pipeline')}
                >
                  Pipeline
                </button>
                <button
                  className={`tab ${activeTab === 'thresholds' ? 'active' : ''}`}
                  onClick={() => setActiveTab('thresholds')}
                >
                  Thresholds
                </button>
              </div>

              <div className="detail-content">
                {activeTab === 'details' && (
                  <div className="detail-section">
                    <div className="form-group">
                      <label>Slug</label>
                      <input type="text" value={selectedType.slug} disabled />
                    </div>
                    <div className="form-group">
                      <label>Description</label>
                      <textarea
                        value={selectedType.description || ''}
                        onChange={(e) => handleUpdateType({ description: e.target.value })}
                        rows={3}
                      />
                    </div>
                    <div className="form-row">
                      <div className="form-group">
                        <label>Icon</label>
                        <input
                          type="text"
                          value={selectedType.icon || ''}
                          onChange={(e) => handleUpdateType({ icon: e.target.value })}
                          placeholder="e.g. shield"
                        />
                      </div>
                      <div className="form-group">
                        <label>Color</label>
                        <input
                          type="color"
                          value={selectedType.color || '#3b82f6'}
                          onChange={(e) => handleUpdateType({ color: e.target.value })}
                        />
                      </div>
                    </div>
                    <div className="form-row">
                      <div className="form-group">
                        <label>Severity Weight</label>
                        <input
                          type="number"
                          value={selectedType.severity_weight}
                          onChange={(e) => handleUpdateType({ severity_weight: parseFloat(e.target.value) })}
                          min={0}
                          max={10}
                          step={0.1}
                        />
                      </div>
                      <div className="form-group">
                        <label>Active</label>
                        <label className="toggle">
                          <input
                            type="checkbox"
                            checked={selectedType.is_active}
                            onChange={(e) => handleUpdateType({ is_active: e.target.checked })}
                          />
                          <span className="slider"></span>
                        </label>
                      </div>
                    </div>
                  </div>
                )}

                {activeTab === 'fields' && (
                  <div className="detail-section">
                    <div className="section-header">
                      <h4>Custom Fields</h4>
                      <button className="action-btn small" onClick={() => setShowFieldForm(true)}>
                        + Add Field
                      </button>
                    </div>
                    <div className="fields-list">
                      {selectedType.fields?.map((field) => (
                        <div key={field.id} className="field-item">
                          <div className="field-header">
                            <span className="field-name">{field.name}</span>
                            <span className="field-type">{field.field_type}</span>
                            {field.required && <span className="badge required">Required</span>}
                          </div>
                          <div className="field-meta">
                            <span>{field.display_name}</span>
                            {field.enum_values && (
                              <span className="enum-values">
                                Options: {field.enum_values.join(', ')}
                              </span>
                            )}
                          </div>
                          {field.extraction_hint && (
                            <div className="extraction-hint">
                              LLM Hint: {field.extraction_hint}
                            </div>
                          )}
                        </div>
                      ))}
                      {(!selectedType.fields || selectedType.fields.length === 0) && (
                        <p className="no-data">No custom fields defined</p>
                      )}
                    </div>
                  </div>
                )}

                {activeTab === 'pipeline' && (
                  <div className="detail-section">
                    <h4>Pipeline Configuration</h4>
                    <div className="pipeline-stages">
                      {stages.map((stage) => {
                        const config = selectedType.pipeline_config?.find(
                          (pc) => pc.stage_id === stage.id
                        );
                        return (
                          <div key={stage.id} className={`pipeline-stage ${config?.enabled !== false ? 'enabled' : 'disabled'}`}>
                            <div className="stage-toggle">
                              <label className="toggle small">
                                <input
                                  type="checkbox"
                                  checked={config?.enabled !== false}
                                  onChange={() => {/* TODO: Update pipeline config */}}
                                />
                                <span className="slider"></span>
                              </label>
                            </div>
                            <div className="stage-info">
                              <span className="stage-name">{stage.name}</span>
                              <span className="stage-description">{stage.description}</span>
                            </div>
                            <div className="stage-order">
                              Order: {config?.execution_order ?? stage.default_order}
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                )}

                {activeTab === 'thresholds' && (
                  <div className="detail-section">
                    <h4>Approval Thresholds</h4>
                    <div className="threshold-form">
                      <div className="form-group">
                        <label>Auto-Approve Threshold</label>
                        <input
                          type="number"
                          value={(selectedType.approval_thresholds?.min_confidence_auto_approve ?? 0.85) * 100}
                          onChange={(e) => handleUpdateThresholds({
                            ...selectedType.approval_thresholds,
                            min_confidence_auto_approve: parseFloat(e.target.value) / 100,
                          })}
                          min={0}
                          max={100}
                          step={1}
                        />
                        <span className="input-suffix">%</span>
                      </div>
                      <div className="form-group">
                        <label>Review Threshold</label>
                        <input
                          type="number"
                          value={(selectedType.approval_thresholds?.min_confidence_review ?? 0.5) * 100}
                          onChange={(e) => handleUpdateThresholds({
                            ...selectedType.approval_thresholds,
                            min_confidence_review: parseFloat(e.target.value) / 100,
                          })}
                          min={0}
                          max={100}
                          step={1}
                        />
                        <span className="input-suffix">%</span>
                      </div>
                      <div className="form-group">
                        <label>Auto-Reject Below</label>
                        <input
                          type="number"
                          value={(selectedType.approval_thresholds?.auto_reject_below ?? 0.3) * 100}
                          onChange={(e) => handleUpdateThresholds({
                            ...selectedType.approval_thresholds,
                            auto_reject_below: parseFloat(e.target.value) / 100,
                          })}
                          min={0}
                          max={100}
                          step={1}
                        />
                        <span className="input-suffix">%</span>
                      </div>
                      <div className="form-group">
                        <label>Field Confidence Threshold</label>
                        <input
                          type="number"
                          value={(selectedType.approval_thresholds?.field_confidence_threshold ?? 0.7) * 100}
                          onChange={(e) => handleUpdateThresholds({
                            ...selectedType.approval_thresholds,
                            field_confidence_threshold: parseFloat(e.target.value) / 100,
                          })}
                          min={0}
                          max={100}
                          step={1}
                        />
                        <span className="input-suffix">%</span>
                      </div>
                    </div>
                  </div>
                )}
              </div>
            </>
          ) : (
            <div className="empty-state">
              <p>Select an incident type to view details</p>
            </div>
          )}
        </div>
        }
      />

      {/* Create Type Modal */}
      {showCreateForm && (
        <div className="modal-overlay" onClick={() => setShowCreateForm(false)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h3>Create Incident Type</h3>
              <button className="close-btn" onClick={() => setShowCreateForm(false)}>&times;</button>
            </div>
            <form onSubmit={handleCreateType}>
              <div className="modal-body">
                <div className="form-group">
                  <label>Name *</label>
                  <input
                    type="text"
                    value={formData.name}
                    onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                    required
                    placeholder="e.g. Vehicle Pursuit"
                  />
                </div>
                <div className="form-group">
                  <label>Slug (auto-generated if empty)</label>
                  <input
                    type="text"
                    value={formData.slug}
                    onChange={(e) => setFormData({ ...formData, slug: e.target.value })}
                    placeholder="e.g. vehicle_pursuit"
                  />
                </div>
                <div className="form-group">
                  <label>Display Name</label>
                  <input
                    type="text"
                    value={formData.display_name}
                    onChange={(e) => setFormData({ ...formData, display_name: e.target.value })}
                    placeholder="e.g. Vehicle Pursuit Incident"
                  />
                </div>
                <div className="form-group">
                  <label>Category *</label>
                  <select
                    value={formData.category}
                    onChange={(e) => setFormData({ ...formData, category: e.target.value as 'enforcement' | 'crime' })}
                    required
                  >
                    <option value="enforcement">Enforcement</option>
                    <option value="crime">Crime</option>
                  </select>
                </div>
                <div className="form-group">
                  <label>Description</label>
                  <textarea
                    value={formData.description}
                    onChange={(e) => setFormData({ ...formData, description: e.target.value })}
                    rows={3}
                  />
                </div>
                <div className="form-row">
                  <div className="form-group">
                    <label>Color</label>
                    <input
                      type="color"
                      value={formData.color}
                      onChange={(e) => setFormData({ ...formData, color: e.target.value })}
                    />
                  </div>
                  <div className="form-group">
                    <label>Severity Weight</label>
                    <input
                      type="number"
                      value={formData.severity_weight}
                      onChange={(e) => setFormData({ ...formData, severity_weight: parseFloat(e.target.value) })}
                      min={0}
                      max={10}
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
                  {saving ? 'Creating...' : 'Create Type'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Create Field Modal */}
      {showFieldForm && (
        <div className="modal-overlay" onClick={() => setShowFieldForm(false)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h3>Add Custom Field</h3>
              <button className="close-btn" onClick={() => setShowFieldForm(false)}>&times;</button>
            </div>
            <form onSubmit={handleCreateField}>
              <div className="modal-body">
                <div className="form-group">
                  <label>Field Name *</label>
                  <input
                    type="text"
                    value={fieldFormData.name}
                    onChange={(e) => setFieldFormData({ ...fieldFormData, name: e.target.value })}
                    required
                    placeholder="e.g. vehicle_type"
                  />
                </div>
                <div className="form-group">
                  <label>Display Name *</label>
                  <input
                    type="text"
                    value={fieldFormData.display_name}
                    onChange={(e) => setFieldFormData({ ...fieldFormData, display_name: e.target.value })}
                    required
                    placeholder="e.g. Vehicle Type"
                  />
                </div>
                <div className="form-group">
                  <label>Field Type *</label>
                  <select
                    value={fieldFormData.field_type}
                    onChange={(e) => setFieldFormData({ ...fieldFormData, field_type: e.target.value as FieldType })}
                    required
                  >
                    <option value="string">String</option>
                    <option value="text">Text (Long)</option>
                    <option value="integer">Integer</option>
                    <option value="decimal">Decimal</option>
                    <option value="boolean">Boolean</option>
                    <option value="date">Date</option>
                    <option value="datetime">DateTime</option>
                    <option value="enum">Enum (Select)</option>
                    <option value="array">Array</option>
                    <option value="reference">Reference</option>
                  </select>
                </div>
                {fieldFormData.field_type === 'enum' && (
                  <div className="form-group">
                    <label>Enum Values (comma-separated)</label>
                    <input
                      type="text"
                      value={fieldFormData.enum_values}
                      onChange={(e) => setFieldFormData({ ...fieldFormData, enum_values: e.target.value })}
                      placeholder="e.g. sedan, suv, truck, van"
                    />
                  </div>
                )}
                <div className="form-group">
                  <label>Description</label>
                  <textarea
                    value={fieldFormData.description}
                    onChange={(e) => setFieldFormData({ ...fieldFormData, description: e.target.value })}
                    rows={2}
                  />
                </div>
                <div className="form-group">
                  <label>LLM Extraction Hint</label>
                  <textarea
                    value={fieldFormData.extraction_hint}
                    onChange={(e) => setFieldFormData({ ...fieldFormData, extraction_hint: e.target.value })}
                    rows={2}
                    placeholder="Instructions for the LLM on how to extract this field"
                  />
                </div>
                <div className="form-row">
                  <div className="form-group">
                    <label>Required</label>
                    <label className="toggle">
                      <input
                        type="checkbox"
                        checked={fieldFormData.required}
                        onChange={(e) => setFieldFormData({ ...fieldFormData, required: e.target.checked })}
                      />
                      <span className="slider"></span>
                    </label>
                  </div>
                  <div className="form-group">
                    <label>Display Order</label>
                    <input
                      type="number"
                      value={fieldFormData.display_order}
                      onChange={(e) => setFieldFormData({ ...fieldFormData, display_order: parseInt(e.target.value) })}
                    />
                  </div>
                </div>
              </div>
              <div className="modal-footer">
                <button type="button" className="action-btn" onClick={() => setShowFieldForm(false)}>
                  Cancel
                </button>
                <button type="submit" className="action-btn primary" disabled={saving}>
                  {saving ? 'Creating...' : 'Add Field'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

    </div>
  );
}

export default IncidentTypeManager;
