import { useState, useEffect, useCallback } from 'react';

const API_BASE = '';

interface ExtractionSchema {
  id: string;
  domain_id: string | null;
  category_id: string | null;
  domain_name: string | null;
  category_name: string | null;
  schema_version: number;
  name: string;
  description: string | null;
  system_prompt: string;
  user_prompt_template: string;
  model_name: string;
  temperature: number;
  max_tokens: number;
  required_fields: string[];
  optional_fields: string[];
  field_definitions: Record<string, any>;
  validation_rules: Record<string, any>;
  confidence_thresholds: Record<string, any>;
  quality_metrics: Record<string, any>;
  min_quality_threshold: number;
  is_active: boolean;
  is_production: boolean;
  deployed_at: string | null;
  created_at: string;
  updated_at: string;
}

interface Domain {
  id: string;
  name: string;
  slug: string;
}

interface Category {
  id: string;
  name: string;
  slug: string;
}

export function ExtractionSchemaManager() {
  const [schemas, setSchemas] = useState<ExtractionSchema[]>([]);
  const [selectedSchema, setSelectedSchema] = useState<ExtractionSchema | null>(null);
  const [domains, setDomains] = useState<Domain[]>([]);
  const [categories, setCategories] = useState<Category[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [editMode, setEditMode] = useState(false);
  const [filterDomain, setFilterDomain] = useState('');

  const loadSchemas = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (filterDomain) params.set('domain_id', filterDomain);
      const res = await fetch(`${API_BASE}/api/admin/extraction-schemas?${params}`);
      if (!res.ok) throw new Error('Failed to load schemas');
      const data = await res.json();
      setSchemas(data.schemas || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load');
    } finally {
      setLoading(false);
    }
  }, [filterDomain]);

  const loadDomains = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/admin/domains`);
      if (res.ok) {
        const data = await res.json();
        setDomains(data.domains || data || []);
      }
    } catch { /* optional */ }
  }, []);

  useEffect(() => { loadSchemas(); }, [loadSchemas]);
  useEffect(() => { loadDomains(); }, [loadDomains]);

  const loadCategories = async (domainSlug: string) => {
    try {
      const res = await fetch(`${API_BASE}/api/admin/domains/${domainSlug}/categories`);
      if (res.ok) {
        const data = await res.json();
        setCategories(data.categories || data || []);
      }
    } catch { /* optional */ }
  };

  const handleCreate = async (formData: Record<string, any>) => {
    try {
      const res = await fetch(`${API_BASE}/api/admin/extraction-schemas`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(formData),
      });
      if (!res.ok) throw new Error('Failed to create schema');
      setShowCreate(false);
      await loadSchemas();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Create failed');
    }
  };

  const handleUpdate = async (formData: Record<string, any>) => {
    if (!selectedSchema) return;
    try {
      const res = await fetch(`${API_BASE}/api/admin/extraction-schemas/${selectedSchema.id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(formData),
      });
      if (!res.ok) throw new Error('Failed to update schema');
      const updated = await res.json();
      setSelectedSchema(updated);
      setEditMode(false);
      await loadSchemas();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Update failed');
    }
  };

  if (loading) {
    return <div className="admin-loading">Loading extraction schemas...</div>;
  }

  return (
    <div className="admin-page">
      <div className="page-header">
        <h2>Extraction Schemas</h2>
        <div className="page-actions">
          <select
            value={filterDomain}
            onChange={(e) => setFilterDomain(e.target.value)}
            style={{ marginRight: 8, padding: '6px 10px', borderRadius: 6, border: '1px solid var(--border-color)', fontSize: 13 }}
          >
            <option value="">All Domains</option>
            {domains.map(d => (
              <option key={d.id} value={d.id}>{d.name}</option>
            ))}
          </select>
          <button className="action-btn primary" onClick={() => setShowCreate(true)}>
            + New Schema
          </button>
        </div>
      </div>

      {error && <div className="error-banner">{error}</div>}

      <div className="split-view">
        {/* Schema List */}
        <div className="list-panel">
          <div className="list-header">
            <h3>Schemas ({schemas.length})</h3>
          </div>
          {schemas.length === 0 ? (
            <div className="empty-state"><p>No extraction schemas found.</p></div>
          ) : (
            <div className="table-container" style={{ border: 'none' }}>
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Name</th>
                    <th>Domain</th>
                    <th>Model</th>
                    <th>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {schemas.map(s => (
                    <tr
                      key={s.id}
                      className={selectedSchema?.id === s.id ? 'selected' : ''}
                      onClick={() => { setSelectedSchema(s); setEditMode(false); }}
                      style={{ cursor: 'pointer' }}
                    >
                      <td style={{ fontWeight: 500 }}>{s.name}</td>
                      <td style={{ fontSize: 12, color: 'var(--text-muted)' }}>
                        {s.domain_name || '—'}{s.category_name ? ` / ${s.category_name}` : ''}
                      </td>
                      <td style={{ fontSize: 12 }}>{s.model_name}</td>
                      <td>
                        {s.is_production ? (
                          <span style={{ background: '#22c55e', color: '#fff', padding: '2px 8px', borderRadius: 12, fontSize: 11, fontWeight: 600 }}>PROD</span>
                        ) : s.is_active ? (
                          <span style={{ background: '#3b82f6', color: '#fff', padding: '2px 8px', borderRadius: 12, fontSize: 11 }}>Active</span>
                        ) : (
                          <span style={{ background: '#6b7280', color: '#fff', padding: '2px 8px', borderRadius: 12, fontSize: 11 }}>Inactive</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {/* Schema Detail */}
        <div className="detail-panel">
          {selectedSchema ? (
            <div>
              <div className="detail-header">
                <h3>{selectedSchema.name}</h3>
                <div style={{ display: 'flex', gap: 8 }}>
                  <button className="action-btn" onClick={() => setEditMode(!editMode)}>
                    {editMode ? 'Cancel' : 'Edit'}
                  </button>
                </div>
              </div>
              <div className="detail-content">
                {editMode ? (
                  <SchemaForm
                    initial={selectedSchema}
                    domains={domains}
                    onSubmit={handleUpdate}
                    onCancel={() => setEditMode(false)}
                    onDomainChange={loadCategories}
                    categories={categories}
                  />
                ) : (
                  <SchemaDetail schema={selectedSchema} />
                )}
              </div>
            </div>
          ) : (
            <div className="empty-state"><p>Select a schema to view details</p></div>
          )}
        </div>
      </div>

      {/* Create Modal */}
      {showCreate && (
        <div className="modal-overlay" onClick={() => setShowCreate(false)}>
          <div className="modal-content" onClick={e => e.stopPropagation()} style={{ maxWidth: 700 }}>
            <h3>Create Extraction Schema</h3>
            <SchemaForm
              domains={domains}
              onSubmit={handleCreate}
              onCancel={() => setShowCreate(false)}
              onDomainChange={loadCategories}
              categories={categories}
            />
          </div>
        </div>
      )}
    </div>
  );
}

function SchemaDetail({ schema }: { schema: ExtractionSchema }) {
  const qm = schema.quality_metrics || {};
  return (
    <>
      <div className="detail-section">
        <h4>Configuration</h4>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, fontSize: 13 }}>
          <div><span style={{ color: 'var(--text-muted)' }}>Version:</span> {schema.schema_version}</div>
          <div><span style={{ color: 'var(--text-muted)' }}>Model:</span> {schema.model_name}</div>
          <div><span style={{ color: 'var(--text-muted)' }}>Temperature:</span> {schema.temperature}</div>
          <div><span style={{ color: 'var(--text-muted)' }}>Max Tokens:</span> {schema.max_tokens}</div>
          <div><span style={{ color: 'var(--text-muted)' }}>Min F1:</span> {schema.min_quality_threshold}</div>
          <div><span style={{ color: 'var(--text-muted)' }}>Deployed:</span> {schema.deployed_at ? new Date(schema.deployed_at).toLocaleDateString() : 'Never'}</div>
        </div>
      </div>

      {Object.keys(qm).length > 0 && (
        <div className="detail-section" style={{ marginTop: 16 }}>
          <h4>Quality Metrics</h4>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 12 }}>
            <div className="stat-card" style={{ padding: 12, textAlign: 'center' }}>
              <div style={{ fontSize: 20, fontWeight: 700 }}>{(qm.precision * 100)?.toFixed(1) || '—'}%</div>
              <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>Precision</div>
            </div>
            <div className="stat-card" style={{ padding: 12, textAlign: 'center' }}>
              <div style={{ fontSize: 20, fontWeight: 700 }}>{(qm.recall * 100)?.toFixed(1) || '—'}%</div>
              <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>Recall</div>
            </div>
            <div className="stat-card" style={{ padding: 12, textAlign: 'center' }}>
              <div style={{ fontSize: 20, fontWeight: 700 }}>{(qm.f1_score * 100)?.toFixed(1) || '—'}%</div>
              <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>F1 Score</div>
            </div>
          </div>
        </div>
      )}

      <div className="detail-section" style={{ marginTop: 16 }}>
        <h4>Fields</h4>
        <div style={{ fontSize: 13 }}>
          <div style={{ marginBottom: 8 }}>
            <span style={{ fontWeight: 600 }}>Required:</span>{' '}
            {(schema.required_fields || []).join(', ') || 'None'}
          </div>
          <div>
            <span style={{ fontWeight: 600 }}>Optional:</span>{' '}
            {(schema.optional_fields || []).join(', ') || 'None'}
          </div>
        </div>
      </div>

      <div className="detail-section" style={{ marginTop: 16 }}>
        <h4>System Prompt</h4>
        <pre style={{ fontSize: 12, whiteSpace: 'pre-wrap', background: 'var(--bg-secondary)', padding: 12, borderRadius: 6, maxHeight: 200, overflow: 'auto' }}>
          {schema.system_prompt}
        </pre>
      </div>

      <div className="detail-section" style={{ marginTop: 16 }}>
        <h4>User Prompt Template</h4>
        <pre style={{ fontSize: 12, whiteSpace: 'pre-wrap', background: 'var(--bg-secondary)', padding: 12, borderRadius: 6, maxHeight: 200, overflow: 'auto' }}>
          {schema.user_prompt_template}
        </pre>
      </div>
    </>
  );
}

function SchemaForm({
  initial,
  domains,
  categories,
  onSubmit,
  onCancel,
  onDomainChange,
}: {
  initial?: ExtractionSchema;
  domains: Domain[];
  categories: Category[];
  onSubmit: (data: Record<string, any>) => void;
  onCancel: () => void;
  onDomainChange: (domainSlug: string) => void;
}) {
  const [name, setName] = useState(initial?.name || '');
  const [description, setDescription] = useState(initial?.description || '');
  const [domainId, setDomainId] = useState(initial?.domain_id || '');
  const [categoryId, setCategoryId] = useState(initial?.category_id || '');
  const [modelName, setModelName] = useState(initial?.model_name || 'claude-sonnet-4-5');
  const [temperature, setTemperature] = useState(initial?.temperature?.toString() || '0.7');
  const [maxTokens, setMaxTokens] = useState(initial?.max_tokens?.toString() || '4000');
  const [systemPrompt, setSystemPrompt] = useState(initial?.system_prompt || '');
  const [userPromptTemplate, setUserPromptTemplate] = useState(initial?.user_prompt_template || '');
  const [requiredFields, setRequiredFields] = useState(
    (initial?.required_fields || []).join(', ')
  );
  const [optionalFields, setOptionalFields] = useState(
    (initial?.optional_fields || []).join(', ')
  );

  const handleDomainSelect = (id: string) => {
    setDomainId(id);
    setCategoryId('');
    const d = domains.find(x => x.id === id);
    if (d) onDomainChange(d.slug);
  };

  const handleSubmit = () => {
    const data: Record<string, any> = {
      name,
      description: description || null,
      domain_id: domainId || null,
      category_id: categoryId || null,
      model_name: modelName,
      temperature: parseFloat(temperature),
      max_tokens: parseInt(maxTokens),
      system_prompt: systemPrompt,
      user_prompt_template: userPromptTemplate,
      required_fields: requiredFields.split(',').map(s => s.trim()).filter(Boolean),
      optional_fields: optionalFields.split(',').map(s => s.trim()).filter(Boolean),
    };
    onSubmit(data);
  };

  const inputStyle = { width: '100%', padding: '8px 10px', borderRadius: 6, border: '1px solid var(--border-color)', fontSize: 13, background: 'var(--bg-primary)' };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <div>
        <label style={{ fontSize: 12, fontWeight: 600, display: 'block', marginBottom: 4 }}>Name *</label>
        <input value={name} onChange={e => setName(e.target.value)} style={inputStyle} />
      </div>
      <div>
        <label style={{ fontSize: 12, fontWeight: 600, display: 'block', marginBottom: 4 }}>Description</label>
        <input value={description} onChange={e => setDescription(e.target.value)} style={inputStyle} />
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
        <div>
          <label style={{ fontSize: 12, fontWeight: 600, display: 'block', marginBottom: 4 }}>Domain</label>
          <select value={domainId} onChange={e => handleDomainSelect(e.target.value)} style={inputStyle as any}>
            <option value="">None</option>
            {domains.map(d => <option key={d.id} value={d.id}>{d.name}</option>)}
          </select>
        </div>
        <div>
          <label style={{ fontSize: 12, fontWeight: 600, display: 'block', marginBottom: 4 }}>Category</label>
          <select value={categoryId} onChange={e => setCategoryId(e.target.value)} style={inputStyle as any}>
            <option value="">None</option>
            {categories.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
        </div>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 12 }}>
        <div>
          <label style={{ fontSize: 12, fontWeight: 600, display: 'block', marginBottom: 4 }}>Model</label>
          <input value={modelName} onChange={e => setModelName(e.target.value)} style={inputStyle} />
        </div>
        <div>
          <label style={{ fontSize: 12, fontWeight: 600, display: 'block', marginBottom: 4 }}>Temperature</label>
          <input type="number" step="0.1" value={temperature} onChange={e => setTemperature(e.target.value)} style={inputStyle} />
        </div>
        <div>
          <label style={{ fontSize: 12, fontWeight: 600, display: 'block', marginBottom: 4 }}>Max Tokens</label>
          <input type="number" value={maxTokens} onChange={e => setMaxTokens(e.target.value)} style={inputStyle} />
        </div>
      </div>
      <div>
        <label style={{ fontSize: 12, fontWeight: 600, display: 'block', marginBottom: 4 }}>System Prompt *</label>
        <textarea value={systemPrompt} onChange={e => setSystemPrompt(e.target.value)} rows={4} style={{ ...inputStyle, resize: 'vertical' }} />
      </div>
      <div>
        <label style={{ fontSize: 12, fontWeight: 600, display: 'block', marginBottom: 4 }}>User Prompt Template *</label>
        <textarea value={userPromptTemplate} onChange={e => setUserPromptTemplate(e.target.value)} rows={4} style={{ ...inputStyle, resize: 'vertical' }} placeholder="Use {article_text} as placeholder" />
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
        <div>
          <label style={{ fontSize: 12, fontWeight: 600, display: 'block', marginBottom: 4 }}>Required Fields (comma-separated)</label>
          <input value={requiredFields} onChange={e => setRequiredFields(e.target.value)} style={inputStyle} />
        </div>
        <div>
          <label style={{ fontSize: 12, fontWeight: 600, display: 'block', marginBottom: 4 }}>Optional Fields (comma-separated)</label>
          <input value={optionalFields} onChange={e => setOptionalFields(e.target.value)} style={inputStyle} />
        </div>
      </div>
      <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', marginTop: 8 }}>
        <button className="action-btn" onClick={onCancel}>Cancel</button>
        <button className="action-btn primary" onClick={handleSubmit} disabled={!name || !systemPrompt || !userPromptTemplate}>
          {initial ? 'Update' : 'Create'}
        </button>
      </div>
    </div>
  );
}

export default ExtractionSchemaManager;
