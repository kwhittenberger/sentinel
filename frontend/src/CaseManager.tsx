import { useState, useEffect, useCallback } from 'react';
import { SplitPane } from './SplitPane';

const API_BASE = '';

interface Case {
  id: string;
  case_number: string | null;
  case_type: string;
  jurisdiction: string | null;
  court_name: string | null;
  filed_date: string | null;
  closed_date: string | null;
  status: string;
  domain_slug: string | null;
  category_slug: string | null;
  custom_fields: Record<string, unknown>;
  data_classification: string;
  notes: string | null;
  created_at: string;
}

interface Charge {
  id: string;
  case_id: string;
  charge_number: number;
  charge_code: string | null;
  charge_description: string;
  charge_level: string;
  charge_class: string | null;
  severity: number | null;
  status: string;
  is_violent_crime: boolean;
  jail_days: number | null;
  fine_amount: number | null;
}

interface ChargeEvent {
  id: string;
  charge_id: string;
  event_type: string;
  actor_type: string | null;
  actor_name: string | null;
  reason: string | null;
  event_date: string;
  charge_number?: number;
  charge_description?: string;
}

interface CaseLink {
  id: string;
  case_id: string;
  incident_id?: string;
  actor_id?: string;
  title?: string;
  date?: string;
  canonical_name?: string;
  role_name?: string;
  incident_role?: string;
  sequence_order?: number;
}

type DetailTab = 'details' | 'charges' | 'history' | 'incidents' | 'actors';

export function CaseManager() {
  const [cases, setCases] = useState<Case[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [selectedCase, setSelectedCase] = useState<Case | null>(null);
  const [charges, setCharges] = useState<Charge[]>([]);
  const [history, setHistory] = useState<ChargeEvent[]>([]);
  const [linkedIncidents, setLinkedIncidents] = useState<CaseLink[]>([]);
  const [linkedActors, setLinkedActors] = useState<CaseLink[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<DetailTab>('details');
  const [showCreateCase, setShowCreateCase] = useState(false);
  const [showCreateCharge, setShowCreateCharge] = useState(false);

  // Filters
  const [filterStatus, setFilterStatus] = useState('');
  const [filterType, setFilterType] = useState('');
  const [searchTerm, setSearchTerm] = useState('');

  const [caseForm, setCaseForm] = useState({
    case_number: '',
    case_type: 'criminal',
    jurisdiction: '',
    court_name: '',
    status: 'active',
    notes: '',
  });

  const [chargeForm, setChargeForm] = useState({
    charge_number: 1,
    charge_code: '',
    charge_description: '',
    charge_level: 'misdemeanor',
    is_violent_crime: false,
  });

  const loadCases = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (filterStatus) params.set('status', filterStatus);
      if (filterType) params.set('case_type', filterType);
      if (searchTerm) params.set('search', searchTerm);
      params.set('page', String(page));

      const res = await fetch(`${API_BASE}/api/admin/cases?${params}`);
      if (!res.ok) throw new Error('Failed to load cases');
      const data = await res.json();
      setCases(data.cases);
      setTotal(data.total);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load cases');
    } finally {
      setLoading(false);
    }
  }, [filterStatus, filterType, searchTerm, page]);

  useEffect(() => {
    loadCases();
  }, [loadCases]);

  const loadCaseDetail = useCallback(async (caseId: string) => {
    try {
      const [chargesRes, historyRes, incidentsRes, actorsRes] = await Promise.all([
        fetch(`${API_BASE}/api/admin/cases/${caseId}/charges`).then(r => r.json()).catch(() => []),
        fetch(`${API_BASE}/api/admin/cases/${caseId}/charge-history`).then(r => r.json()).catch(() => []),
        fetch(`${API_BASE}/api/admin/cases/${caseId}/incidents`).then(r => r.json()).catch(() => []),
        fetch(`${API_BASE}/api/admin/cases/${caseId}/actors`).then(r => r.json()).catch(() => []),
      ]);
      setCharges(chargesRes);
      setHistory(historyRes);
      setLinkedIncidents(incidentsRes);
      setLinkedActors(actorsRes);
    } catch (err) {
      console.error('Failed to load case details:', err);
    }
  }, []);

  const selectCase = (c: Case) => {
    setSelectedCase(c);
    setActiveTab('details');
    loadCaseDetail(c.id);
  };

  const handleCreateCase = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/api/admin/cases`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(caseForm),
      });
      if (!res.ok) throw new Error('Failed to create case');
      const data = await res.json();
      setShowCreateCase(false);
      setCaseForm({ case_number: '', case_type: 'criminal', jurisdiction: '', court_name: '', status: 'active', notes: '' });
      await loadCases();
      selectCase(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create case');
    } finally {
      setSaving(false);
    }
  };

  const handleUpdateCase = async (updates: Partial<Case>) => {
    if (!selectedCase) return;
    setSaving(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/api/admin/cases/${selectedCase.id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(updates),
      });
      if (!res.ok) throw new Error('Failed to update case');
      const data = await res.json();
      setSelectedCase(data);
      await loadCases();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to update case');
    } finally {
      setSaving(false);
    }
  };

  const handleCreateCharge = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedCase) return;
    setSaving(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/api/admin/cases/${selectedCase.id}/charges`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(chargeForm),
      });
      if (!res.ok) throw new Error('Failed to create charge');
      setShowCreateCharge(false);
      setChargeForm({ charge_number: charges.length + 2, charge_code: '', charge_description: '', charge_level: 'misdemeanor', is_violent_crime: false });
      await loadCaseDetail(selectedCase.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create charge');
    } finally {
      setSaving(false);
    }
  };

  const statusColor = (status: string) => {
    switch (status) {
      case 'active': return '#3b82f6';
      case 'closed': return '#6b7280';
      case 'appealed': return '#f59e0b';
      case 'dismissed': return '#22c55e';
      case 'sealed': return '#8b5cf6';
      default: return '#6b7280';
    }
  };

  const chargeStatusColor = (status: string) => {
    switch (status) {
      case 'filed': return '#3b82f6';
      case 'amended': return '#f59e0b';
      case 'reduced': return '#eab308';
      case 'dismissed': return '#22c55e';
      case 'convicted': return '#ef4444';
      case 'acquitted': return '#10b981';
      default: return '#6b7280';
    }
  };

  if (loading && cases.length === 0) {
    return <div className="admin-loading">Loading cases...</div>;
  }

  return (
    <div className="admin-page">
      <div className="page-header">
        <h2>Cases</h2>
        <div className="page-actions">
          <button className="action-btn primary" onClick={() => setShowCreateCase(true)}>
            + Create Case
          </button>
        </div>
      </div>

      {error && <div className="error-banner">{error}</div>}

      {/* Filters */}
      <div className="browser-toolbar">
        <div className="search-row">
          <input
            className="search-input"
            type="text"
            placeholder="Search cases..."
            value={searchTerm}
            onChange={(e) => { setSearchTerm(e.target.value); setPage(1); }}
          />
        </div>
        <div className="filter-row">
          <select
            className="filter-select"
            value={filterStatus}
            onChange={(e) => { setFilterStatus(e.target.value); setPage(1); }}
          >
            <option value="">All Statuses</option>
            <option value="active">Active</option>
            <option value="closed">Closed</option>
            <option value="appealed">Appealed</option>
            <option value="dismissed">Dismissed</option>
            <option value="sealed">Sealed</option>
          </select>
          <select
            className="filter-select"
            value={filterType}
            onChange={(e) => { setFilterType(e.target.value); setPage(1); }}
          >
            <option value="">All Types</option>
            <option value="criminal">Criminal</option>
            <option value="civil">Civil</option>
            <option value="immigration">Immigration</option>
            <option value="administrative">Administrative</option>
          </select>
          <span className="page-info">{total} cases</span>
        </div>
      </div>

      <SplitPane
        storageKey="cases"
        defaultLeftWidth={420}
        minLeftWidth={280}
        maxLeftWidth={700}
        left={
        <div className="list-panel">
          <div className="list-items">
            {cases.map((c) => (
              <div
                key={c.id}
                className={`list-item ${selectedCase?.id === c.id ? 'selected' : ''}`}
                onClick={() => selectCase(c)}
              >
                <div className="item-content">
                  <div className="item-title">{c.case_number || 'No case number'}</div>
                  <div className="item-meta">
                    <span style={{ color: statusColor(c.status), fontWeight: 600 }}>{c.status}</span>
                    <span>{c.case_type}</span>
                    {c.filed_date && <span>{c.filed_date}</span>}
                  </div>
                  {c.jurisdiction && (
                    <div className="item-meta">
                      <span>{c.jurisdiction}</span>
                    </div>
                  )}
                </div>
              </div>
            ))}
            {cases.length === 0 && <p className="no-data" style={{ padding: '1rem' }}>No cases found</p>}
          </div>
          {total > 50 && (
            <div className="pagination">
              <button className="action-btn small" disabled={page <= 1} onClick={() => setPage(p => p - 1)}>Prev</button>
              <span className="page-info">Page {page}</span>
              <button className="action-btn small" disabled={cases.length < 50} onClick={() => setPage(p => p + 1)}>Next</button>
            </div>
          )}
        </div>
        }
        right={
        <div className="detail-panel">
          {selectedCase ? (
            <>
              <div className="detail-header">
                <h3>{selectedCase.case_number || 'Case'}</h3>
                <span style={{
                  padding: '2px 10px', borderRadius: 4, fontSize: 12, fontWeight: 600,
                  background: statusColor(selectedCase.status), color: 'white',
                }}>
                  {selectedCase.status}
                </span>
              </div>

              <div className="detail-tabs">
                {(['details', 'charges', 'history', 'incidents', 'actors'] as DetailTab[]).map(tab => (
                  <button
                    key={tab}
                    className={`tab ${activeTab === tab ? 'active' : ''}`}
                    onClick={() => setActiveTab(tab)}
                  >
                    {tab === 'details' ? 'Details' :
                     tab === 'charges' ? `Charges (${charges.length})` :
                     tab === 'history' ? `History (${history.length})` :
                     tab === 'incidents' ? `Incidents (${linkedIncidents.length})` :
                     `Actors (${linkedActors.length})`}
                  </button>
                ))}
              </div>

              <div className="detail-content">
                {activeTab === 'details' && (
                  <div className="detail-section">
                    <div className="form-group">
                      <label>Case Number</label>
                      <input type="text" value={selectedCase.case_number || ''} disabled />
                    </div>
                    <div className="form-row">
                      <div className="form-group">
                        <label>Type</label>
                        <select
                          value={selectedCase.case_type}
                          onChange={(e) => handleUpdateCase({ case_type: e.target.value })}
                          disabled={saving}
                        >
                          <option value="criminal">Criminal</option>
                          <option value="civil">Civil</option>
                          <option value="immigration">Immigration</option>
                          <option value="administrative">Administrative</option>
                        </select>
                      </div>
                      <div className="form-group">
                        <label>Status</label>
                        <select
                          value={selectedCase.status}
                          onChange={(e) => handleUpdateCase({ status: e.target.value })}
                          disabled={saving}
                        >
                          <option value="active">Active</option>
                          <option value="closed">Closed</option>
                          <option value="appealed">Appealed</option>
                          <option value="dismissed">Dismissed</option>
                          <option value="sealed">Sealed</option>
                        </select>
                      </div>
                    </div>
                    <div className="form-group">
                      <label>Jurisdiction</label>
                      <input
                        type="text"
                        value={selectedCase.jurisdiction || ''}
                        onChange={(e) => handleUpdateCase({ jurisdiction: e.target.value })}
                        disabled={saving}
                      />
                    </div>
                    <div className="form-group">
                      <label>Court</label>
                      <input
                        type="text"
                        value={selectedCase.court_name || ''}
                        onChange={(e) => handleUpdateCase({ court_name: e.target.value })}
                        disabled={saving}
                      />
                    </div>
                    <div className="form-group">
                      <label>Notes</label>
                      <textarea
                        value={selectedCase.notes || ''}
                        onChange={(e) => handleUpdateCase({ notes: e.target.value })}
                        rows={3}
                        disabled={saving}
                      />
                    </div>
                    <div className="form-row">
                      <div className="form-group">
                        <label>Filed Date</label>
                        <input type="text" value={selectedCase.filed_date || 'N/A'} disabled />
                      </div>
                      <div className="form-group">
                        <label>Classification</label>
                        <input type="text" value={selectedCase.data_classification} disabled />
                      </div>
                    </div>
                  </div>
                )}

                {activeTab === 'charges' && (
                  <div className="detail-section">
                    <div className="section-header">
                      <h4>Charges</h4>
                      <button className="action-btn small" onClick={() => {
                        setChargeForm(f => ({ ...f, charge_number: charges.length + 1 }));
                        setShowCreateCharge(true);
                      }}>
                        + Add Charge
                      </button>
                    </div>
                    <div className="fields-list">
                      {charges.map((ch) => (
                        <div key={ch.id} className="field-item">
                          <div className="field-header">
                            <span className="field-name">Count {ch.charge_number}</span>
                            <span style={{
                              fontSize: 11, fontWeight: 600, padding: '2px 8px',
                              borderRadius: 4, color: 'white',
                              background: chargeStatusColor(ch.status),
                            }}>
                              {ch.status}
                            </span>
                            {ch.is_violent_crime && (
                              <span style={{
                                fontSize: 11, fontWeight: 600, padding: '2px 8px',
                                borderRadius: 4, color: 'white', background: '#ef4444',
                              }}>
                                Violent
                              </span>
                            )}
                          </div>
                          <div style={{ fontSize: 13, marginTop: 4 }}>{ch.charge_description}</div>
                          <div className="field-meta">
                            <span>{ch.charge_level}</span>
                            {ch.charge_code && <span>Code: {ch.charge_code}</span>}
                            {ch.charge_class && <span>Class {ch.charge_class}</span>}
                          </div>
                          {(ch.jail_days || ch.fine_amount) && (
                            <div className="field-meta" style={{ marginTop: 4 }}>
                              {ch.jail_days != null && <span>Jail: {ch.jail_days} days</span>}
                              {ch.fine_amount != null && <span>Fine: ${ch.fine_amount.toLocaleString()}</span>}
                            </div>
                          )}
                        </div>
                      ))}
                      {charges.length === 0 && <p className="no-data">No charges filed</p>}
                    </div>
                  </div>
                )}

                {activeTab === 'history' && (
                  <div className="detail-section">
                    <h4>Charge History</h4>
                    <div className="fields-list">
                      {history.map((evt) => (
                        <div key={evt.id} className="field-item">
                          <div className="field-header">
                            <span className="field-name">{evt.event_type}</span>
                            <span className="field-type">{evt.event_date}</span>
                          </div>
                          {evt.charge_description && (
                            <div style={{ fontSize: 12, color: 'var(--text-secondary)', marginTop: 2 }}>
                              Count {evt.charge_number}: {evt.charge_description}
                            </div>
                          )}
                          {evt.actor_name && (
                            <div className="field-meta">
                              <span>{evt.actor_type}: {evt.actor_name}</span>
                            </div>
                          )}
                          {evt.reason && (
                            <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 4, fontStyle: 'italic' }}>
                              {evt.reason}
                            </div>
                          )}
                        </div>
                      ))}
                      {history.length === 0 && <p className="no-data">No charge history</p>}
                    </div>
                  </div>
                )}

                {activeTab === 'incidents' && (
                  <div className="detail-section">
                    <h4>Linked Incidents</h4>
                    <div className="fields-list">
                      {linkedIncidents.map((link) => (
                        <div key={link.id} className="field-item">
                          <div className="field-header">
                            <span className="field-name">{link.title || link.incident_id}</span>
                            {link.incident_role && <span className="field-type">{link.incident_role}</span>}
                          </div>
                          {link.date && <div className="field-meta"><span>{link.date}</span></div>}
                        </div>
                      ))}
                      {linkedIncidents.length === 0 && <p className="no-data">No linked incidents</p>}
                    </div>
                  </div>
                )}

                {activeTab === 'actors' && (
                  <div className="detail-section">
                    <h4>Case Participants</h4>
                    <div className="fields-list">
                      {linkedActors.map((link) => (
                        <div key={link.id} className="field-item">
                          <div className="field-header">
                            <span className="field-name">{link.canonical_name || link.actor_id}</span>
                            {link.role_name && <span className="field-type">{link.role_name}</span>}
                          </div>
                        </div>
                      ))}
                      {linkedActors.length === 0 && <p className="no-data">No participants linked</p>}
                    </div>
                  </div>
                )}
              </div>
            </>
          ) : (
            <div className="empty-state">
              <p>Select a case to view details</p>
            </div>
          )}
        </div>
        }
      />

      {/* Create Case Modal */}
      {showCreateCase && (
        <div className="modal-overlay" onClick={() => setShowCreateCase(false)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h3>Create Case</h3>
              <button className="close-btn" onClick={() => setShowCreateCase(false)}>&times;</button>
            </div>
            <form onSubmit={handleCreateCase}>
              <div className="modal-body">
                <div className="form-group">
                  <label>Case Number</label>
                  <input
                    type="text"
                    value={caseForm.case_number}
                    onChange={(e) => setCaseForm({ ...caseForm, case_number: e.target.value })}
                    placeholder="e.g. CR-2026-00123"
                  />
                </div>
                <div className="form-row">
                  <div className="form-group">
                    <label>Type *</label>
                    <select
                      value={caseForm.case_type}
                      onChange={(e) => setCaseForm({ ...caseForm, case_type: e.target.value })}
                      required
                    >
                      <option value="criminal">Criminal</option>
                      <option value="civil">Civil</option>
                      <option value="immigration">Immigration</option>
                      <option value="administrative">Administrative</option>
                    </select>
                  </div>
                  <div className="form-group">
                    <label>Status</label>
                    <select
                      value={caseForm.status}
                      onChange={(e) => setCaseForm({ ...caseForm, status: e.target.value })}
                    >
                      <option value="active">Active</option>
                      <option value="closed">Closed</option>
                      <option value="appealed">Appealed</option>
                      <option value="dismissed">Dismissed</option>
                    </select>
                  </div>
                </div>
                <div className="form-group">
                  <label>Jurisdiction</label>
                  <input
                    type="text"
                    value={caseForm.jurisdiction}
                    onChange={(e) => setCaseForm({ ...caseForm, jurisdiction: e.target.value })}
                    placeholder="e.g. King County, WA"
                  />
                </div>
                <div className="form-group">
                  <label>Court Name</label>
                  <input
                    type="text"
                    value={caseForm.court_name}
                    onChange={(e) => setCaseForm({ ...caseForm, court_name: e.target.value })}
                    placeholder="e.g. King County Superior Court"
                  />
                </div>
                <div className="form-group">
                  <label>Notes</label>
                  <textarea
                    value={caseForm.notes}
                    onChange={(e) => setCaseForm({ ...caseForm, notes: e.target.value })}
                    rows={3}
                  />
                </div>
              </div>
              <div className="modal-footer">
                <button type="button" className="action-btn" onClick={() => setShowCreateCase(false)}>Cancel</button>
                <button type="submit" className="action-btn primary" disabled={saving}>
                  {saving ? 'Creating...' : 'Create Case'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Create Charge Modal */}
      {showCreateCharge && (
        <div className="modal-overlay" onClick={() => setShowCreateCharge(false)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h3>Add Charge</h3>
              <button className="close-btn" onClick={() => setShowCreateCharge(false)}>&times;</button>
            </div>
            <form onSubmit={handleCreateCharge}>
              <div className="modal-body">
                <div className="form-row">
                  <div className="form-group">
                    <label>Count # *</label>
                    <input
                      type="number"
                      value={chargeForm.charge_number}
                      onChange={(e) => setChargeForm({ ...chargeForm, charge_number: parseInt(e.target.value) || 1 })}
                      required
                      min={1}
                    />
                  </div>
                  <div className="form-group">
                    <label>Statute Code</label>
                    <input
                      type="text"
                      value={chargeForm.charge_code}
                      onChange={(e) => setChargeForm({ ...chargeForm, charge_code: e.target.value })}
                      placeholder="e.g. RCW 9A.36.021"
                    />
                  </div>
                </div>
                <div className="form-group">
                  <label>Description *</label>
                  <textarea
                    value={chargeForm.charge_description}
                    onChange={(e) => setChargeForm({ ...chargeForm, charge_description: e.target.value })}
                    required
                    rows={2}
                    placeholder="e.g. Assault in the Second Degree"
                  />
                </div>
                <div className="form-row">
                  <div className="form-group">
                    <label>Level *</label>
                    <select
                      value={chargeForm.charge_level}
                      onChange={(e) => setChargeForm({ ...chargeForm, charge_level: e.target.value })}
                    >
                      <option value="felony">Felony</option>
                      <option value="misdemeanor">Misdemeanor</option>
                      <option value="infraction">Infraction</option>
                      <option value="violation">Violation</option>
                    </select>
                  </div>
                  <div className="form-group">
                    <label>Violent Crime</label>
                    <label className="toggle">
                      <input
                        type="checkbox"
                        checked={chargeForm.is_violent_crime}
                        onChange={(e) => setChargeForm({ ...chargeForm, is_violent_crime: e.target.checked })}
                      />
                      <span className="slider"></span>
                    </label>
                  </div>
                </div>
              </div>
              <div className="modal-footer">
                <button type="button" className="action-btn" onClick={() => setShowCreateCharge(false)}>Cancel</button>
                <button type="submit" className="action-btn primary" disabled={saving}>
                  {saving ? 'Creating...' : 'Add Charge'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      <style>{`
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
      `}</style>
    </div>
  );
}

export default CaseManager;
