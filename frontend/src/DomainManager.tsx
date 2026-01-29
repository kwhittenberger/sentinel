import { useState, useEffect, useCallback } from 'react';

const API_BASE = '';

interface Domain {
  id: string;
  name: string;
  slug: string;
  description: string | null;
  icon: string | null;
  color: string | null;
  is_active: boolean;
  display_order: number;
  created_at: string;
  updated_at: string | null;
}

interface Category {
  id: string;
  domain_id: string;
  domain_slug: string;
  domain_name: string;
  parent_category_id: string | null;
  name: string;
  slug: string;
  description: string | null;
  icon: string | null;
  is_active: boolean;
  display_order: number;
  required_fields: string[];
  optional_fields: string[];
  field_definitions: Record<string, unknown>;
  created_at: string;
  updated_at: string | null;
}

type SelectedItem = { type: 'domain'; data: Domain } | { type: 'category'; data: Category };

export function DomainManager() {
  const [domains, setDomains] = useState<Domain[]>([]);
  const [categories, setCategories] = useState<Record<string, Category[]>>({});
  const [expandedDomains, setExpandedDomains] = useState<Set<string>>(new Set());
  const [selected, setSelected] = useState<SelectedItem | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showCreateDomain, setShowCreateDomain] = useState(false);
  const [showCreateCategory, setShowCreateCategory] = useState(false);
  const [categoryDomainSlug, setCategoryDomainSlug] = useState('');

  const [domainForm, setDomainForm] = useState({
    name: '',
    slug: '',
    description: '',
    icon: '',
    color: '#3b82f6',
    display_order: 0,
  });

  const [categoryForm, setCategoryForm] = useState({
    name: '',
    slug: '',
    description: '',
    icon: '',
    display_order: 0,
    required_fields: '',
    optional_fields: '',
  });

  const loadDomains = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/api/admin/domains?include_inactive=true`);
      if (!res.ok) throw new Error('Failed to load domains');
      const data = await res.json();
      setDomains(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load domains');
    } finally {
      setLoading(false);
    }
  }, []);

  const loadCategories = useCallback(async (domainSlug: string) => {
    try {
      const res = await fetch(`${API_BASE}/api/admin/domains/${domainSlug}/categories?include_inactive=true`);
      if (!res.ok) throw new Error('Failed to load categories');
      const data = await res.json();
      setCategories(prev => ({ ...prev, [domainSlug]: data }));
    } catch (err) {
      console.error('Failed to load categories:', err);
    }
  }, []);

  useEffect(() => {
    loadDomains();
  }, [loadDomains]);

  const toggleDomain = (slug: string) => {
    setExpandedDomains(prev => {
      const next = new Set(prev);
      if (next.has(slug)) {
        next.delete(slug);
      } else {
        next.add(slug);
        if (!categories[slug]) {
          loadCategories(slug);
        }
      }
      return next;
    });
  };

  const selectDomain = (domain: Domain) => {
    setSelected({ type: 'domain', data: domain });
    if (!expandedDomains.has(domain.slug)) {
      toggleDomain(domain.slug);
    }
  };

  const selectCategory = (category: Category) => {
    setSelected({ type: 'category', data: category });
  };

  const handleCreateDomain = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/api/admin/domains`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(domainForm),
      });
      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || 'Failed to create domain');
      }
      const data = await res.json();
      setShowCreateDomain(false);
      setDomainForm({ name: '', slug: '', description: '', icon: '', color: '#3b82f6', display_order: 0 });
      await loadDomains();
      setSelected({ type: 'domain', data });
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create domain');
    } finally {
      setSaving(false);
    }
  };

  const handleUpdateDomain = async (updates: Partial<Domain>) => {
    if (selected?.type !== 'domain') return;
    setSaving(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/api/admin/domains/${selected.data.slug}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(updates),
      });
      if (!res.ok) throw new Error('Failed to update domain');
      const data = await res.json();
      setSelected({ type: 'domain', data });
      await loadDomains();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to update domain');
    } finally {
      setSaving(false);
    }
  };

  const handleCreateCategory = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      const payload = {
        ...categoryForm,
        required_fields: categoryForm.required_fields
          ? JSON.stringify(categoryForm.required_fields.split(',').map(s => s.trim()).filter(Boolean))
          : '[]',
        optional_fields: categoryForm.optional_fields
          ? JSON.stringify(categoryForm.optional_fields.split(',').map(s => s.trim()).filter(Boolean))
          : '[]',
      };
      const res = await fetch(`${API_BASE}/api/admin/domains/${categoryDomainSlug}/categories`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || 'Failed to create category');
      }
      const data = await res.json();
      setShowCreateCategory(false);
      setCategoryForm({ name: '', slug: '', description: '', icon: '', display_order: 0, required_fields: '', optional_fields: '' });
      await loadCategories(categoryDomainSlug);
      setSelected({ type: 'category', data });
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create category');
    } finally {
      setSaving(false);
    }
  };

  const handleUpdateCategory = async (updates: Record<string, unknown>) => {
    if (selected?.type !== 'category') return;
    setSaving(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/api/admin/categories/${selected.data.id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(updates),
      });
      if (!res.ok) throw new Error('Failed to update category');
      const data = await res.json();
      setSelected({ type: 'category', data });
      await loadCategories(selected.data.domain_slug);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to update category');
    } finally {
      setSaving(false);
    }
  };

  const openCreateCategory = (domainSlug: string) => {
    setCategoryDomainSlug(domainSlug);
    setShowCreateCategory(true);
  };

  if (loading) {
    return <div className="admin-loading">Loading domains...</div>;
  }

  return (
    <div className="admin-page">
      <div className="page-header">
        <h2>Event Domains</h2>
        <div className="page-actions">
          <button className="action-btn primary" onClick={() => setShowCreateDomain(true)}>
            + Create Domain
          </button>
        </div>
      </div>

      {error && <div className="error-banner">{error}</div>}

      <div className="split-view">
        {/* Domains & Categories Tree */}
        <div className="list-panel">
          <div className="list-header">
            <h3>Domains ({domains.length})</h3>
          </div>
          <div className="list-items">
            {domains.map((domain) => (
              <div key={domain.id}>
                <div
                  className={`list-item ${selected?.type === 'domain' && selected.data.id === domain.id ? 'selected' : ''}`}
                  onClick={() => selectDomain(domain)}
                >
                  <div
                    className="item-icon"
                    style={{ backgroundColor: domain.color || '#6b7280' }}
                  >
                    {domain.icon || domain.name[0].toUpperCase()}
                  </div>
                  <div className="item-content">
                    <div className="item-title">{domain.name}</div>
                    <div className="item-meta">
                      <span>{domain.slug}</span>
                    </div>
                  </div>
                  <button
                    className="tree-toggle"
                    onClick={(e) => { e.stopPropagation(); toggleDomain(domain.slug); }}
                  >
                    {expandedDomains.has(domain.slug) ? '\u25BC' : '\u25B6'}
                  </button>
                  {!domain.is_active && <span className="badge inactive">Inactive</span>}
                </div>

                {/* Nested categories */}
                {expandedDomains.has(domain.slug) && (
                  <div className="nested-items">
                    {(categories[domain.slug] || []).map((cat) => (
                      <div
                        key={cat.id}
                        className={`list-item nested ${selected?.type === 'category' && selected.data.id === cat.id ? 'selected' : ''}`}
                        onClick={() => selectCategory(cat)}
                      >
                        <div className="item-content">
                          <div className="item-title">{cat.icon ? `${cat.icon} ` : ''}{cat.name}</div>
                          <div className="item-meta">
                            <span>{cat.slug}</span>
                            {!cat.is_active && <span className="badge inactive">Inactive</span>}
                          </div>
                        </div>
                      </div>
                    ))}
                    <div
                      className="list-item nested add-item"
                      onClick={() => openCreateCategory(domain.slug)}
                    >
                      <span className="add-icon">+</span>
                      <span>Add Category</span>
                    </div>
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>

        {/* Detail Panel */}
        <div className="detail-panel">
          {selected?.type === 'domain' && (
            <DomainDetail
              domain={selected.data}
              onUpdate={handleUpdateDomain}
              saving={saving}
            />
          )}
          {selected?.type === 'category' && (
            <CategoryDetail
              category={selected.data}
              onUpdate={handleUpdateCategory}
              saving={saving}
            />
          )}
          {!selected && (
            <div className="empty-state">
              <p>Select a domain or category to view details</p>
            </div>
          )}
        </div>
      </div>

      {/* Create Domain Modal */}
      {showCreateDomain && (
        <div className="modal-overlay" onClick={() => setShowCreateDomain(false)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h3>Create Event Domain</h3>
              <button className="close-btn" onClick={() => setShowCreateDomain(false)}>&times;</button>
            </div>
            <form onSubmit={handleCreateDomain}>
              <div className="modal-body">
                <div className="form-group">
                  <label>Name *</label>
                  <input
                    type="text"
                    value={domainForm.name}
                    onChange={(e) => setDomainForm({ ...domainForm, name: e.target.value })}
                    required
                    placeholder="e.g. Immigration Enforcement"
                  />
                </div>
                <div className="form-group">
                  <label>Slug *</label>
                  <input
                    type="text"
                    value={domainForm.slug}
                    onChange={(e) => setDomainForm({ ...domainForm, slug: e.target.value })}
                    required
                    placeholder="e.g. immigration"
                  />
                </div>
                <div className="form-group">
                  <label>Description</label>
                  <textarea
                    value={domainForm.description}
                    onChange={(e) => setDomainForm({ ...domainForm, description: e.target.value })}
                    rows={3}
                  />
                </div>
                <div className="form-row">
                  <div className="form-group">
                    <label>Icon</label>
                    <input
                      type="text"
                      value={domainForm.icon}
                      onChange={(e) => setDomainForm({ ...domainForm, icon: e.target.value })}
                      placeholder="e.g. shield"
                    />
                  </div>
                  <div className="form-group">
                    <label>Color</label>
                    <input
                      type="color"
                      value={domainForm.color}
                      onChange={(e) => setDomainForm({ ...domainForm, color: e.target.value })}
                    />
                  </div>
                </div>
                <div className="form-group">
                  <label>Display Order</label>
                  <input
                    type="number"
                    value={domainForm.display_order}
                    onChange={(e) => setDomainForm({ ...domainForm, display_order: parseInt(e.target.value) || 0 })}
                  />
                </div>
              </div>
              <div className="modal-footer">
                <button type="button" className="action-btn" onClick={() => setShowCreateDomain(false)}>
                  Cancel
                </button>
                <button type="submit" className="action-btn primary" disabled={saving}>
                  {saving ? 'Creating...' : 'Create Domain'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Create Category Modal */}
      {showCreateCategory && (
        <div className="modal-overlay" onClick={() => setShowCreateCategory(false)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h3>Create Category in {categoryDomainSlug}</h3>
              <button className="close-btn" onClick={() => setShowCreateCategory(false)}>&times;</button>
            </div>
            <form onSubmit={handleCreateCategory}>
              <div className="modal-body">
                <div className="form-group">
                  <label>Name *</label>
                  <input
                    type="text"
                    value={categoryForm.name}
                    onChange={(e) => setCategoryForm({ ...categoryForm, name: e.target.value })}
                    required
                    placeholder="e.g. Use of Force"
                  />
                </div>
                <div className="form-group">
                  <label>Slug *</label>
                  <input
                    type="text"
                    value={categoryForm.slug}
                    onChange={(e) => setCategoryForm({ ...categoryForm, slug: e.target.value })}
                    required
                    placeholder="e.g. use_of_force"
                  />
                </div>
                <div className="form-group">
                  <label>Description</label>
                  <textarea
                    value={categoryForm.description}
                    onChange={(e) => setCategoryForm({ ...categoryForm, description: e.target.value })}
                    rows={3}
                  />
                </div>
                <div className="form-row">
                  <div className="form-group">
                    <label>Icon</label>
                    <input
                      type="text"
                      value={categoryForm.icon}
                      onChange={(e) => setCategoryForm({ ...categoryForm, icon: e.target.value })}
                      placeholder="e.g. fist"
                    />
                  </div>
                  <div className="form-group">
                    <label>Display Order</label>
                    <input
                      type="number"
                      value={categoryForm.display_order}
                      onChange={(e) => setCategoryForm({ ...categoryForm, display_order: parseInt(e.target.value) || 0 })}
                    />
                  </div>
                </div>
                <div className="form-group">
                  <label>Required Fields (comma-separated)</label>
                  <input
                    type="text"
                    value={categoryForm.required_fields}
                    onChange={(e) => setCategoryForm({ ...categoryForm, required_fields: e.target.value })}
                    placeholder="e.g. date, state, incident_type"
                  />
                </div>
                <div className="form-group">
                  <label>Optional Fields (comma-separated)</label>
                  <input
                    type="text"
                    value={categoryForm.optional_fields}
                    onChange={(e) => setCategoryForm({ ...categoryForm, optional_fields: e.target.value })}
                    placeholder="e.g. city, county, description"
                  />
                </div>
              </div>
              <div className="modal-footer">
                <button type="button" className="action-btn" onClick={() => setShowCreateCategory(false)}>
                  Cancel
                </button>
                <button type="submit" className="action-btn primary" disabled={saving}>
                  {saving ? 'Creating...' : 'Create Category'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      <style>{`
        .tree-toggle {
          background: none;
          border: none;
          color: var(--text-muted);
          cursor: pointer;
          font-size: 10px;
          padding: 4px 8px;
        }

        .tree-toggle:hover {
          color: var(--text-primary);
        }

        .nested-items {
          border-left: 2px solid var(--border-color);
          margin-left: 16px;
        }

        .list-item.nested {
          padding-left: 20px;
          font-size: 13px;
        }

        .list-item.add-item {
          color: var(--text-muted);
          font-size: 12px;
          display: flex;
          align-items: center;
          gap: 6px;
          cursor: pointer;
        }

        .list-item.add-item:hover {
          color: #3b82f6;
        }

        .add-icon {
          font-size: 14px;
          font-weight: bold;
        }

        .close-btn {
          background: none;
          border: none;
          font-size: 24px;
          color: var(--text-secondary);
          cursor: pointer;
          line-height: 1;
        }

        .close-btn:hover {
          color: var(--text-primary);
        }

        .modal-body {
          padding: 20px;
          overflow-y: auto;
        }

        .detail-field-list {
          display: flex;
          flex-wrap: wrap;
          gap: 6px;
        }

        .field-tag {
          padding: 3px 10px;
          background: var(--bg-hover);
          border: 1px solid var(--border-color);
          border-radius: 4px;
          font-size: 12px;
          font-family: monospace;
        }

        .field-tag.required {
          border-color: #f59e0b;
          background: rgba(245, 158, 11, 0.1);
        }

        .field-tag.optional {
          border-color: var(--border-color);
        }

        .domain-color-preview {
          display: inline-block;
          width: 16px;
          height: 16px;
          border-radius: 4px;
          vertical-align: middle;
          margin-left: 8px;
        }
      `}</style>
    </div>
  );
}

function DomainDetail({
  domain,
  onUpdate,
  saving,
}: {
  domain: Domain;
  onUpdate: (updates: Partial<Domain>) => void;
  saving: boolean;
}) {
  return (
    <>
      <div className="detail-header">
        <h3>
          {domain.icon ? `${domain.icon} ` : ''}{domain.name}
          {domain.color && (
            <span className="domain-color-preview" style={{ backgroundColor: domain.color }} />
          )}
        </h3>
        {!domain.is_active && <span className="badge inactive">Inactive</span>}
      </div>

      <div className="detail-content">
        <div className="detail-section">
          <div className="form-group">
            <label>Slug</label>
            <input type="text" value={domain.slug} disabled />
          </div>
          <div className="form-group">
            <label>Description</label>
            <textarea
              value={domain.description || ''}
              onChange={(e) => onUpdate({ description: e.target.value })}
              rows={3}
              disabled={saving}
            />
          </div>
          <div className="form-row">
            <div className="form-group">
              <label>Icon</label>
              <input
                type="text"
                value={domain.icon || ''}
                onChange={(e) => onUpdate({ icon: e.target.value })}
                placeholder="e.g. shield"
                disabled={saving}
              />
            </div>
            <div className="form-group">
              <label>Color</label>
              <input
                type="color"
                value={domain.color || '#3b82f6'}
                onChange={(e) => onUpdate({ color: e.target.value })}
                disabled={saving}
              />
            </div>
          </div>
          <div className="form-row">
            <div className="form-group">
              <label>Display Order</label>
              <input
                type="number"
                value={domain.display_order}
                onChange={(e) => onUpdate({ display_order: parseInt(e.target.value) || 0 })}
                disabled={saving}
              />
            </div>
            <div className="form-group">
              <label>Active</label>
              <label className="toggle">
                <input
                  type="checkbox"
                  checked={domain.is_active}
                  onChange={(e) => onUpdate({ is_active: e.target.checked })}
                  disabled={saving}
                />
                <span className="slider"></span>
              </label>
            </div>
          </div>
          <div className="form-group">
            <label>Created</label>
            <input type="text" value={new Date(domain.created_at).toLocaleString()} disabled />
          </div>
        </div>
      </div>
    </>
  );
}

function CategoryDetail({
  category,
  onUpdate,
  saving,
}: {
  category: Category;
  onUpdate: (updates: Record<string, unknown>) => void;
  saving: boolean;
}) {
  const reqFields: string[] = Array.isArray(category.required_fields) ? category.required_fields : [];
  const optFields: string[] = Array.isArray(category.optional_fields) ? category.optional_fields : [];

  return (
    <>
      <div className="detail-header">
        <h3>{category.icon ? `${category.icon} ` : ''}{category.name}</h3>
        <span className="badge" style={{ background: '#3b82f6', color: 'white' }}>
          {category.domain_name}
        </span>
      </div>

      <div className="detail-content">
        <div className="detail-section">
          <div className="form-group">
            <label>Slug</label>
            <input type="text" value={`${category.domain_slug}/${category.slug}`} disabled />
          </div>
          <div className="form-group">
            <label>Description</label>
            <textarea
              value={category.description || ''}
              onChange={(e) => onUpdate({ description: e.target.value })}
              rows={3}
              disabled={saving}
            />
          </div>
          <div className="form-row">
            <div className="form-group">
              <label>Icon</label>
              <input
                type="text"
                value={category.icon || ''}
                onChange={(e) => onUpdate({ icon: e.target.value })}
                placeholder="e.g. fist"
                disabled={saving}
              />
            </div>
            <div className="form-group">
              <label>Display Order</label>
              <input
                type="number"
                value={category.display_order}
                onChange={(e) => onUpdate({ display_order: parseInt(e.target.value) || 0 })}
                disabled={saving}
              />
            </div>
          </div>
          <div className="form-group">
            <label>Active</label>
            <label className="toggle">
              <input
                type="checkbox"
                checked={category.is_active}
                onChange={(e) => onUpdate({ is_active: e.target.checked })}
                disabled={saving}
              />
              <span className="slider"></span>
            </label>
          </div>

          <h4 style={{ marginTop: '1.5rem', marginBottom: '0.75rem', fontSize: '14px' }}>Required Fields</h4>
          <div className="detail-field-list">
            {reqFields.length > 0 ? reqFields.map((f) => (
              <span key={f} className="field-tag required">{f}</span>
            )) : (
              <span className="no-data">None defined</span>
            )}
          </div>

          <h4 style={{ marginTop: '1.5rem', marginBottom: '0.75rem', fontSize: '14px' }}>Optional Fields</h4>
          <div className="detail-field-list">
            {optFields.length > 0 ? optFields.map((f) => (
              <span key={f} className="field-tag optional">{f}</span>
            )) : (
              <span className="no-data">None defined</span>
            )}
          </div>

          {category.field_definitions && Object.keys(category.field_definitions).length > 0 && (
            <>
              <h4 style={{ marginTop: '1.5rem', marginBottom: '0.75rem', fontSize: '14px' }}>Field Definitions</h4>
              <pre style={{
                background: 'var(--bg-input)',
                padding: '12px',
                borderRadius: '6px',
                fontSize: '12px',
                overflow: 'auto',
                maxHeight: '200px',
              }}>
                {JSON.stringify(category.field_definitions, null, 2)}
              </pre>
            </>
          )}

          <div className="form-group" style={{ marginTop: '1rem' }}>
            <label>Created</label>
            <input type="text" value={new Date(category.created_at).toLocaleString()} disabled />
          </div>
        </div>
      </div>
    </>
  );
}

export default DomainManager;
