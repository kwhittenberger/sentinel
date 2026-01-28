import { useState, useEffect, useCallback } from 'react';
import type { Incident, IncidentCategory } from './types';
import { SplitPane } from './SplitPane';
import { IncidentDetailView } from './IncidentDetailView';

const API_BASE = '/api';

interface IncidentBrowserProps {
  onClose?: () => void;
}

interface PaginatedResponse {
  incidents: Incident[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

export function IncidentBrowser({ onClose }: IncidentBrowserProps) {
  const [incidents, setIncidents] = useState<Incident[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize] = useState(50);
  const [totalPages, setTotalPages] = useState(0);
  const [loading, setLoading] = useState(true);

  // Filters
  const [search, setSearch] = useState('');
  const [categoryFilter, setCategoryFilter] = useState<IncidentCategory | ''>('');
  const [stateFilter, setStateFilter] = useState('');
  const [dateStart, setDateStart] = useState('');
  const [dateEnd, setDateEnd] = useState('');

  // Edit state
  const [selectedIncident, setSelectedIncident] = useState<Incident | null>(null);
  const [editMode, setEditMode] = useState(false);
  const [editData, setEditData] = useState<Partial<Incident>>({});
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null);

  const loadIncidents = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      params.set('page', String(page));
      params.set('page_size', String(pageSize));
      if (search) params.set('search', search);
      if (categoryFilter) params.set('category', categoryFilter);
      if (stateFilter) params.set('state', stateFilter);
      if (dateStart) params.set('date_start', dateStart);
      if (dateEnd) params.set('date_end', dateEnd);

      const response = await fetch(`${API_BASE}/admin/incidents?${params}`);
      if (response.ok) {
        const data: PaginatedResponse = await response.json();
        setIncidents(data.incidents);
        setTotal(data.total);
        setTotalPages(data.total_pages);
      }
    } catch (err) {
      setMessage({ type: 'error', text: 'Failed to load incidents' });
    } finally {
      setLoading(false);
    }
  }, [page, pageSize, search, categoryFilter, stateFilter, dateStart, dateEnd]);

  useEffect(() => {
    loadIncidents();
  }, [loadIncidents]);

  const handleSearch = () => {
    setPage(1);
    loadIncidents();
  };

  const handleSelectIncident = async (incident: Incident) => {
    try {
      const response = await fetch(`${API_BASE}/admin/incidents/${incident.id}`);
      if (response.ok) {
        const fullIncident = await response.json();
        setSelectedIncident(fullIncident);
        setEditData(fullIncident);
        setEditMode(false);
      }
    } catch {
      setMessage({ type: 'error', text: 'Failed to load incident details' });
    }
  };

  const handleSave = async () => {
    if (!selectedIncident) return;
    setSaving(true);
    setMessage(null);
    try {
      const response = await fetch(`${API_BASE}/admin/incidents/${selectedIncident.id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(editData),
      });
      if (response.ok) {
        setMessage({ type: 'success', text: 'Incident updated' });
        setEditMode(false);
        setSelectedIncident({ ...selectedIncident, ...editData } as Incident);
        loadIncidents();
      } else {
        setMessage({ type: 'error', text: 'Failed to update incident' });
      }
    } catch {
      setMessage({ type: 'error', text: 'Failed to update incident' });
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async () => {
    if (!selectedIncident) return;
    if (!confirm('Are you sure you want to archive this incident?')) return;

    try {
      const response = await fetch(`${API_BASE}/admin/incidents/${selectedIncident.id}`, {
        method: 'DELETE',
      });
      if (response.ok) {
        setMessage({ type: 'success', text: 'Incident archived' });
        setSelectedIncident(null);
        loadIncidents();
      }
    } catch {
      setMessage({ type: 'error', text: 'Failed to delete incident' });
    }
  };

  const handleExport = async (format: 'json' | 'csv') => {
    const params = new URLSearchParams();
    params.set('format', format);
    if (categoryFilter) params.set('category', categoryFilter);
    if (stateFilter) params.set('state', stateFilter);
    if (dateStart) params.set('date_start', dateStart);
    if (dateEnd) params.set('date_end', dateEnd);

    const response = await fetch(`${API_BASE}/admin/incidents/export?${params}`);
    if (response.ok) {
      if (format === 'csv') {
        const blob = await response.blob();
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = 'incidents.csv';
        a.click();
      } else {
        const data = await response.json();
        const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = 'incidents.json';
        a.click();
      }
    }
  };

  const getOutcomeColor = (outcome?: string): string => {
    if (!outcome) return 'var(--text-muted)';
    if (outcome === 'death') return '#ef4444';
    if (outcome === 'serious_injury') return '#f97316';
    if (outcome === 'minor_injury') return '#eab308';
    return '#22c55e';
  };

  return (
    <div className="incident-browser">
      <div className="browser-header">
        <h2>Incident Browser</h2>
        {onClose && (
          <button className="admin-close-btn" onClick={onClose}>&times;</button>
        )}
      </div>

      {message && (
        <div className={`settings-message ${message.type}`}>
          {message.text}
        </div>
      )}

      <div className="browser-toolbar">
        <div className="search-row">
          <input
            type="text"
            placeholder="Search incidents..."
            value={search}
            onChange={e => setSearch(e.target.value)}
            onKeyPress={e => e.key === 'Enter' && handleSearch()}
            className="search-input"
          />
          <button className="action-btn" onClick={handleSearch}>Search</button>
        </div>

        <div className="filter-row">
          <select
            value={categoryFilter}
            onChange={e => setCategoryFilter(e.target.value as IncidentCategory | '')}
            className="filter-select"
          >
            <option value="">All Categories</option>
            <option value="enforcement">Enforcement</option>
            <option value="crime">Crime</option>
          </select>

          <input
            type="text"
            placeholder="State"
            value={stateFilter}
            onChange={e => setStateFilter(e.target.value)}
            className="filter-input"
          />

          <input
            type="date"
            value={dateStart}
            onChange={e => setDateStart(e.target.value)}
            className="filter-input"
          />
          <span className="date-sep">to</span>
          <input
            type="date"
            value={dateEnd}
            onChange={e => setDateEnd(e.target.value)}
            className="filter-input"
          />

          <div className="export-buttons">
            <button className="action-btn small" onClick={() => handleExport('csv')}>
              Export CSV
            </button>
            <button className="action-btn small" onClick={() => handleExport('json')}>
              Export JSON
            </button>
          </div>
        </div>
      </div>

      <SplitPane
        storageKey="incident-browser"
        defaultLeftWidth={450}
        minLeftWidth={300}
        maxLeftWidth={700}
        left={
          <div className="incidents-list">
            {loading ? (
              <div className="loading">Loading...</div>
            ) : incidents.length === 0 ? (
              <div className="empty-state">No incidents found</div>
            ) : (
              <>
                <table className="incidents-table">
                  <thead>
                    <tr>
                      <th>Date</th>
                      <th>State</th>
                      <th>Type</th>
                      <th>Category</th>
                      <th>Outcome</th>
                    </tr>
                  </thead>
                  <tbody>
                    {incidents.map(inc => (
                      <tr
                        key={inc.id}
                        className={selectedIncident?.id === inc.id ? 'selected' : ''}
                        onClick={() => handleSelectIncident(inc)}
                      >
                        <td>{inc.date?.substring(0, 10)}</td>
                        <td>{inc.state}</td>
                        <td>{inc.incident_type}</td>
                        <td>
                          <span className={`category-badge ${inc.category}`}>
                            {inc.category}
                          </span>
                        </td>
                        <td>
                          <span style={{ color: getOutcomeColor(inc.outcome_category) }}>
                            {inc.outcome_category || '-'}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>

                <div className="pagination">
                  <button
                    className="action-btn small"
                    disabled={page <= 1}
                    onClick={() => setPage(p => Math.max(1, p - 1))}
                  >
                    Previous
                  </button>
                  <span className="page-info">
                    Page {page} of {totalPages} ({total} total)
                  </span>
                  <button
                    className="action-btn small"
                    disabled={page >= totalPages}
                    onClick={() => setPage(p => p + 1)}
                  >
                    Next
                  </button>
                </div>
              </>
            )}
          </div>
        }
        right={selectedIncident ? (
          <div className="incident-detail">
            <div className="detail-header">
              <h3>Incident Details</h3>
              <div className="detail-actions">
                {editMode ? (
                  <>
                    <button className="action-btn primary" onClick={handleSave} disabled={saving}>
                      {saving ? 'Saving...' : 'Save'}
                    </button>
                    <button className="action-btn" onClick={() => setEditMode(false)}>
                      Cancel
                    </button>
                  </>
                ) : (
                  <>
                    <button className="action-btn primary" onClick={() => setEditMode(true)}>
                      Edit
                    </button>
                    <button className="action-btn reject" onClick={handleDelete}>
                      Archive
                    </button>
                  </>
                )}
              </div>
            </div>

            <div className="detail-content">
              {editMode ? (
                <div className="edit-form">
                  <div className="form-group">
                    <label>Date</label>
                    <input
                      type="date"
                      value={editData.date?.substring(0, 10) || ''}
                      onChange={e => setEditData({ ...editData, date: e.target.value })}
                    />
                  </div>

                  <div className="form-row">
                    <div className="form-group">
                      <label>State</label>
                      <input
                        type="text"
                        value={editData.state || ''}
                        onChange={e => setEditData({ ...editData, state: e.target.value })}
                      />
                    </div>
                    <div className="form-group">
                      <label>City</label>
                      <input
                        type="text"
                        value={editData.city || ''}
                        onChange={e => setEditData({ ...editData, city: e.target.value })}
                      />
                    </div>
                  </div>

                  <div className="form-group">
                    <label>Incident Type</label>
                    <input
                      type="text"
                      value={editData.incident_type || ''}
                      onChange={e => setEditData({ ...editData, incident_type: e.target.value })}
                    />
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

                  <div className="form-group">
                    <label>Description</label>
                    <textarea
                      value={editData.description || ''}
                      onChange={e => setEditData({ ...editData, description: e.target.value })}
                      rows={4}
                    />
                  </div>

                  <div className="form-group">
                    <label>Notes</label>
                    <textarea
                      value={editData.notes || ''}
                      onChange={e => setEditData({ ...editData, notes: e.target.value })}
                      rows={3}
                    />
                  </div>

                  <div className="form-group">
                    <label>Source URL</label>
                    <input
                      type="url"
                      value={editData.source_url || ''}
                      onChange={e => setEditData({ ...editData, source_url: e.target.value })}
                    />
                  </div>
                </div>
              ) : (
                <IncidentDetailView
                  incident={selectedIncident}
                  showSource={true}
                />
              )}
            </div>
          </div>
        ) : (
          <div className="incident-detail empty">
            <p>Select an incident to view details</p>
          </div>
        )}
      />
    </div>
  );
}

export default IncidentBrowser;
