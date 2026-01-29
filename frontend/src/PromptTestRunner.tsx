import { useState, useEffect, useCallback } from 'react';

const API_BASE = '';

interface TestDataset {
  id: string;
  name: string;
  description: string | null;
  domain_id: string | null;
  category_id: string | null;
  domain_name: string | null;
  category_name: string | null;
  case_count: number;
  created_at: string;
}

interface TestCase {
  id: string;
  dataset_id: string;
  article_text: string;
  expected_extraction: Record<string, any>;
  importance: string;
  notes: string | null;
  created_at: string;
}

interface TestRun {
  id: string;
  schema_id: string;
  dataset_id: string;
  schema_name: string | null;
  dataset_name: string | null;
  started_at: string;
  completed_at: string | null;
  status: string;
  total_cases: number;
  passed_cases: number | null;
  failed_cases: number | null;
  precision: number | null;
  recall: number | null;
  f1_score: number | null;
  total_input_tokens: number | null;
  total_output_tokens: number | null;
  estimated_cost: number | null;
  results: any[];
}

interface Schema {
  id: string;
  name: string;
}

type Tab = 'datasets' | 'runs';

export function PromptTestRunner() {
  const [tab, setTab] = useState<Tab>('datasets');
  const [datasets, setDatasets] = useState<TestDataset[]>([]);
  const [runs, setRuns] = useState<TestRun[]>([]);
  const [schemas, setSchemas] = useState<Schema[]>([]);
  const [selectedDataset, setSelectedDataset] = useState<TestDataset | null>(null);
  const [testCases, setTestCases] = useState<TestCase[]>([]);
  const [selectedRun, setSelectedRun] = useState<TestRun | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showCreateDataset, setShowCreateDataset] = useState(false);
  const [showCreateCase, setShowCreateCase] = useState(false);
  const [showRunTest, setShowRunTest] = useState(false);
  const [running, setRunning] = useState(false);

  const loadDatasets = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/admin/prompt-tests/datasets`);
      if (!res.ok) throw new Error('Failed to load datasets');
      const data = await res.json();
      setDatasets(data.datasets || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Load failed');
    }
  }, []);

  const loadRuns = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/admin/prompt-tests/runs`);
      if (!res.ok) throw new Error('Failed to load test runs');
      const data = await res.json();
      setRuns(data.runs || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Load failed');
    }
  }, []);

  const loadSchemas = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/admin/extraction-schemas`);
      if (res.ok) {
        const data = await res.json();
        setSchemas((data.schemas || []).map((s: any) => ({ id: s.id, name: s.name })));
      }
    } catch { /* optional */ }
  }, []);

  useEffect(() => {
    Promise.all([loadDatasets(), loadRuns(), loadSchemas()]).finally(() => setLoading(false));
  }, [loadDatasets, loadRuns, loadSchemas]);

  const loadTestCases = async (datasetId: string) => {
    try {
      const res = await fetch(`${API_BASE}/api/admin/prompt-tests/datasets/${datasetId}/cases`);
      if (res.ok) {
        const data = await res.json();
        setTestCases(data.cases || []);
      }
    } catch { /* optional */ }
  };

  const handleSelectDataset = (ds: TestDataset) => {
    setSelectedDataset(ds);
    setSelectedRun(null);
    loadTestCases(ds.id);
  };

  const handleCreateDataset = async (name: string, description: string) => {
    try {
      await fetch(`${API_BASE}/api/admin/prompt-tests/datasets`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, description }),
      });
      setShowCreateDataset(false);
      await loadDatasets();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Create failed');
    }
  };

  const handleCreateCase = async (data: Record<string, any>) => {
    try {
      await fetch(`${API_BASE}/api/admin/prompt-tests/cases`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...data, dataset_id: selectedDataset?.id }),
      });
      setShowCreateCase(false);
      if (selectedDataset) await loadTestCases(selectedDataset.id);
      await loadDatasets();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Create failed');
    }
  };

  const handleRunTest = async (schemaId: string, datasetId: string) => {
    setRunning(true);
    setShowRunTest(false);
    try {
      const res = await fetch(`${API_BASE}/api/admin/prompt-tests/run`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ schema_id: schemaId, dataset_id: datasetId }),
      });
      if (!res.ok) throw new Error('Test run failed');
      await loadRuns();
      setTab('runs');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Run failed');
    } finally {
      setRunning(false);
    }
  };

  const formatPct = (v: number | null) => v != null ? `${(v * 100).toFixed(1)}%` : '—';
  const statusColor = (s: string) => {
    if (s === 'passed') return '#22c55e';
    if (s === 'failed') return '#ef4444';
    if (s === 'running') return '#f59e0b';
    return '#6b7280';
  };

  if (loading) return <div className="admin-loading">Loading prompt testing...</div>;

  return (
    <div className="admin-page">
      <div className="page-header">
        <h2>Prompt Testing</h2>
        <div className="page-actions">
          {running && <span style={{ fontSize: 13, color: 'var(--text-muted)', marginRight: 8 }}>Running test...</span>}
          <button className="action-btn" onClick={() => setShowRunTest(true)} disabled={running}>
            Run Test
          </button>
          <button className="action-btn primary" onClick={() => setShowCreateDataset(true)}>
            + New Dataset
          </button>
        </div>
      </div>

      {error && <div className="error-banner">{error}</div>}

      {/* Tabs */}
      <div style={{ display: 'flex', gap: 0, borderBottom: '1px solid var(--border-color)', marginBottom: 16 }}>
        {(['datasets', 'runs'] as Tab[]).map(t => (
          <button
            key={t}
            onClick={() => { setTab(t); setSelectedRun(null); }}
            style={{
              padding: '8px 20px', fontSize: 13, fontWeight: tab === t ? 600 : 400,
              background: 'none', border: 'none', borderBottom: tab === t ? '2px solid var(--accent-color)' : '2px solid transparent',
              cursor: 'pointer', color: tab === t ? 'var(--text-primary)' : 'var(--text-muted)',
            }}
          >
            {t === 'datasets' ? `Datasets (${datasets.length})` : `Test Runs (${runs.length})`}
          </button>
        ))}
      </div>

      {tab === 'datasets' ? (
        <div className="split-view">
          {/* Dataset List */}
          <div className="list-panel">
            <div className="list-header"><h3>Datasets</h3></div>
            {datasets.length === 0 ? (
              <div className="empty-state"><p>No test datasets. Create one to get started.</p></div>
            ) : (
              <div className="table-container" style={{ border: 'none' }}>
                <table className="data-table">
                  <thead>
                    <tr><th>Name</th><th>Cases</th><th>Created</th></tr>
                  </thead>
                  <tbody>
                    {datasets.map(ds => (
                      <tr key={ds.id}
                        className={selectedDataset?.id === ds.id ? 'selected' : ''}
                        onClick={() => handleSelectDataset(ds)}
                        style={{ cursor: 'pointer' }}
                      >
                        <td style={{ fontWeight: 500 }}>{ds.name}</td>
                        <td>{ds.case_count}</td>
                        <td style={{ fontSize: 12, color: 'var(--text-muted)' }}>
                          {new Date(ds.created_at).toLocaleDateString()}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          {/* Dataset Detail */}
          <div className="detail-panel">
            {selectedDataset ? (
              <>
                <div className="detail-header">
                  <h3>{selectedDataset.name}</h3>
                  <button className="action-btn" onClick={() => setShowCreateCase(true)}>+ Add Case</button>
                </div>
                <div className="detail-content">
                  {selectedDataset.description && (
                    <p style={{ fontSize: 13, color: 'var(--text-muted)', marginBottom: 16 }}>{selectedDataset.description}</p>
                  )}
                  <h4>Test Cases ({testCases.length})</h4>
                  {testCases.length === 0 ? (
                    <div className="empty-state"><p>No test cases yet.</p></div>
                  ) : (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginTop: 8 }}>
                      {testCases.map(tc => (
                        <div key={tc.id} style={{ padding: 12, background: 'var(--bg-secondary)', borderRadius: 8, fontSize: 13 }}>
                          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6 }}>
                            <span style={{
                              padding: '1px 8px', borderRadius: 10, fontSize: 11, fontWeight: 600,
                              background: tc.importance === 'critical' ? '#ef4444' : tc.importance === 'high' ? '#f59e0b' : '#6b7280',
                              color: '#fff',
                            }}>
                              {tc.importance}
                            </span>
                            <span style={{ color: 'var(--text-muted)', fontSize: 11 }}>
                              {Object.keys(tc.expected_extraction).length} expected fields
                            </span>
                          </div>
                          <div style={{ maxHeight: 60, overflow: 'hidden', color: 'var(--text-secondary)' }}>
                            {tc.article_text.substring(0, 200)}...
                          </div>
                          {tc.notes && <div style={{ marginTop: 4, fontStyle: 'italic', color: 'var(--text-muted)' }}>{tc.notes}</div>}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </>
            ) : (
              <div className="empty-state"><p>Select a dataset to view test cases</p></div>
            )}
          </div>
        </div>
      ) : (
        /* Test Runs Tab */
        <div className="split-view">
          <div className="list-panel">
            <div className="list-header"><h3>Test Runs</h3></div>
            {runs.length === 0 ? (
              <div className="empty-state"><p>No test runs yet.</p></div>
            ) : (
              <div className="table-container" style={{ border: 'none' }}>
                <table className="data-table">
                  <thead>
                    <tr><th>Schema</th><th>Status</th><th>F1</th><th>Date</th></tr>
                  </thead>
                  <tbody>
                    {runs.map(r => (
                      <tr key={r.id}
                        className={selectedRun?.id === r.id ? 'selected' : ''}
                        onClick={() => setSelectedRun(r)}
                        style={{ cursor: 'pointer' }}
                      >
                        <td style={{ fontWeight: 500 }}>{r.schema_name || r.schema_id.slice(0, 8)}</td>
                        <td>
                          <span style={{ background: statusColor(r.status), color: '#fff', padding: '2px 8px', borderRadius: 12, fontSize: 11, fontWeight: 600 }}>
                            {r.status}
                          </span>
                        </td>
                        <td style={{ fontWeight: 600 }}>{formatPct(r.f1_score)}</td>
                        <td style={{ fontSize: 12, color: 'var(--text-muted)' }}>
                          {new Date(r.started_at).toLocaleDateString()}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          <div className="detail-panel">
            {selectedRun ? (
              <>
                <div className="detail-header">
                  <h3>Test Run: {selectedRun.schema_name || 'Unknown'}</h3>
                </div>
                <div className="detail-content">
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 12, marginBottom: 20 }}>
                    <div className="stat-card" style={{ padding: 12, textAlign: 'center' }}>
                      <div style={{ fontSize: 24, fontWeight: 700 }}>{formatPct(selectedRun.precision)}</div>
                      <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>Precision</div>
                    </div>
                    <div className="stat-card" style={{ padding: 12, textAlign: 'center' }}>
                      <div style={{ fontSize: 24, fontWeight: 700 }}>{formatPct(selectedRun.recall)}</div>
                      <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>Recall</div>
                    </div>
                    <div className="stat-card" style={{ padding: 12, textAlign: 'center' }}>
                      <div style={{ fontSize: 24, fontWeight: 700 }}>{formatPct(selectedRun.f1_score)}</div>
                      <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>F1 Score</div>
                    </div>
                  </div>
                  <div style={{ display: 'flex', gap: 24, fontSize: 13, marginBottom: 16 }}>
                    <div><span style={{ color: 'var(--text-muted)' }}>Dataset:</span> {selectedRun.dataset_name || '—'}</div>
                    <div><span style={{ color: 'var(--text-muted)' }}>Cases:</span> {selectedRun.total_cases}</div>
                    <div><span style={{ color: 'var(--text-muted)' }}>Passed:</span> {selectedRun.passed_cases ?? '—'}</div>
                    <div><span style={{ color: 'var(--text-muted)' }}>Failed:</span> {selectedRun.failed_cases ?? '—'}</div>
                  </div>
                  {selectedRun.completed_at && (
                    <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>
                      Completed: {new Date(selectedRun.completed_at).toLocaleString()}
                    </div>
                  )}
                </div>
              </>
            ) : (
              <div className="empty-state"><p>Select a test run to view results</p></div>
            )}
          </div>
        </div>
      )}

      {/* Create Dataset Modal */}
      {showCreateDataset && (
        <div className="modal-overlay" onClick={() => setShowCreateDataset(false)}>
          <div className="modal-content" onClick={e => e.stopPropagation()}>
            <h3>Create Test Dataset</h3>
            <CreateDatasetForm onSubmit={handleCreateDataset} onCancel={() => setShowCreateDataset(false)} />
          </div>
        </div>
      )}

      {/* Create Case Modal */}
      {showCreateCase && selectedDataset && (
        <div className="modal-overlay" onClick={() => setShowCreateCase(false)}>
          <div className="modal-content" onClick={e => e.stopPropagation()} style={{ maxWidth: 700 }}>
            <h3>Add Test Case to {selectedDataset.name}</h3>
            <CreateCaseForm onSubmit={handleCreateCase} onCancel={() => setShowCreateCase(false)} />
          </div>
        </div>
      )}

      {/* Run Test Modal */}
      {showRunTest && (
        <div className="modal-overlay" onClick={() => setShowRunTest(false)}>
          <div className="modal-content" onClick={e => e.stopPropagation()}>
            <h3>Run Prompt Test</h3>
            <RunTestForm schemas={schemas} datasets={datasets} onSubmit={handleRunTest} onCancel={() => setShowRunTest(false)} />
          </div>
        </div>
      )}
    </div>
  );
}

function CreateDatasetForm({ onSubmit, onCancel }: { onSubmit: (name: string, desc: string) => void; onCancel: () => void }) {
  const [name, setName] = useState('');
  const [desc, setDesc] = useState('');
  const inputStyle = { width: '100%', padding: '8px 10px', borderRadius: 6, border: '1px solid var(--border-color)', fontSize: 13, background: 'var(--bg-primary)' };
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <div>
        <label style={{ fontSize: 12, fontWeight: 600, display: 'block', marginBottom: 4 }}>Name *</label>
        <input value={name} onChange={e => setName(e.target.value)} style={inputStyle} />
      </div>
      <div>
        <label style={{ fontSize: 12, fontWeight: 600, display: 'block', marginBottom: 4 }}>Description</label>
        <textarea value={desc} onChange={e => setDesc(e.target.value)} rows={3} style={{ ...inputStyle, resize: 'vertical' }} />
      </div>
      <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
        <button className="action-btn" onClick={onCancel}>Cancel</button>
        <button className="action-btn primary" onClick={() => onSubmit(name, desc)} disabled={!name}>Create</button>
      </div>
    </div>
  );
}

function CreateCaseForm({ onSubmit, onCancel }: { onSubmit: (data: Record<string, any>) => void; onCancel: () => void }) {
  const [articleText, setArticleText] = useState('');
  const [expectedJson, setExpectedJson] = useState('{}');
  const [importance, setImportance] = useState('medium');
  const [notes, setNotes] = useState('');
  const inputStyle = { width: '100%', padding: '8px 10px', borderRadius: 6, border: '1px solid var(--border-color)', fontSize: 13, background: 'var(--bg-primary)' };

  const handleSubmit = () => {
    let expected: Record<string, any>;
    try { expected = JSON.parse(expectedJson); } catch { return; }
    onSubmit({ article_text: articleText, expected_extraction: expected, importance, notes: notes || null });
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <div>
        <label style={{ fontSize: 12, fontWeight: 600, display: 'block', marginBottom: 4 }}>Article Text *</label>
        <textarea value={articleText} onChange={e => setArticleText(e.target.value)} rows={6} style={{ ...inputStyle, resize: 'vertical' }} />
      </div>
      <div>
        <label style={{ fontSize: 12, fontWeight: 600, display: 'block', marginBottom: 4 }}>Expected Extraction (JSON) *</label>
        <textarea value={expectedJson} onChange={e => setExpectedJson(e.target.value)} rows={6} style={{ ...inputStyle, fontFamily: 'monospace', resize: 'vertical' }} />
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 2fr', gap: 12 }}>
        <div>
          <label style={{ fontSize: 12, fontWeight: 600, display: 'block', marginBottom: 4 }}>Importance</label>
          <select value={importance} onChange={e => setImportance(e.target.value)} style={inputStyle as any}>
            <option value="critical">Critical</option>
            <option value="high">High</option>
            <option value="medium">Medium</option>
            <option value="low">Low</option>
          </select>
        </div>
        <div>
          <label style={{ fontSize: 12, fontWeight: 600, display: 'block', marginBottom: 4 }}>Notes</label>
          <input value={notes} onChange={e => setNotes(e.target.value)} style={inputStyle} />
        </div>
      </div>
      <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
        <button className="action-btn" onClick={onCancel}>Cancel</button>
        <button className="action-btn primary" onClick={handleSubmit} disabled={!articleText}>Add Case</button>
      </div>
    </div>
  );
}

function RunTestForm({ schemas, datasets, onSubmit, onCancel }: {
  schemas: { id: string; name: string }[];
  datasets: TestDataset[];
  onSubmit: (schemaId: string, datasetId: string) => void;
  onCancel: () => void;
}) {
  const [schemaId, setSchemaId] = useState('');
  const [datasetId, setDatasetId] = useState('');
  const inputStyle = { width: '100%', padding: '8px 10px', borderRadius: 6, border: '1px solid var(--border-color)', fontSize: 13, background: 'var(--bg-primary)' };
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <div>
        <label style={{ fontSize: 12, fontWeight: 600, display: 'block', marginBottom: 4 }}>Schema *</label>
        <select value={schemaId} onChange={e => setSchemaId(e.target.value)} style={inputStyle as any}>
          <option value="">Select schema...</option>
          {schemas.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
        </select>
      </div>
      <div>
        <label style={{ fontSize: 12, fontWeight: 600, display: 'block', marginBottom: 4 }}>Dataset *</label>
        <select value={datasetId} onChange={e => setDatasetId(e.target.value)} style={inputStyle as any}>
          <option value="">Select dataset...</option>
          {datasets.map(d => <option key={d.id} value={d.id}>{d.name} ({d.case_count} cases)</option>)}
        </select>
      </div>
      <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
        <button className="action-btn" onClick={onCancel}>Cancel</button>
        <button className="action-btn primary" onClick={() => onSubmit(schemaId, datasetId)} disabled={!schemaId || !datasetId}>
          Run Test Suite
        </button>
      </div>
    </div>
  );
}

export default PromptTestRunner;
