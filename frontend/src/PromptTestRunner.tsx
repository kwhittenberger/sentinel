import { useState, useEffect, useCallback, useRef } from 'react';
import { SplitPane } from './SplitPane';
import {
  Stage1SummaryBar,
  Stage2ComparisonGrid,
  BestExtractionDiff,
  GoldenExtractionView,
} from './CalibrationReviewComponents';

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
  provider_name: string | null;
  model_name: string | null;
  comparison_id: string | null;
  iteration_number: number | null;
  config_label: string | null;
}

interface ProviderModel {
  provider: string;
  models: string[];
}

interface Schema {
  id: string;
  name: string;
}

interface MetricStats {
  mean: number;
  std: number;
  min: number;
  max: number;
}

interface ConfigStats {
  label: string;
  precision: MetricStats;
  recall: MetricStats;
  f1_score: MetricStats;
  duration_ms: MetricStats;
  passed_rate: number;
  total_tokens: number;
}

interface ComparisonSummary {
  config_a: ConfigStats;
  config_b: ConfigStats;
  winner: string;
  f1_delta: number;
  statistically_significant: boolean;
}

interface Comparison {
  id: string;
  schema_id: string | null;
  dataset_id: string | null;
  schema_name: string | null;
  dataset_name: string | null;
  config_a_provider: string;
  config_a_model: string;
  config_b_provider: string;
  config_b_model: string;
  iterations_per_config: number;
  status: string;
  progress: number;
  total_iterations: number;
  message: string | null;
  error: string | null;
  summary_stats: ComparisonSummary | Record<string, never>;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  mode: string;
  comparison_type: string;
  output_dataset_id: string | null;
  article_count: number | null;
  article_filters: Record<string, any>;
  reviewed_count: number;
  total_articles: number;
}

interface CalibrationArticle {
  id: string;
  comparison_id: string;
  article_id: string;
  article_title: string | null;
  article_content: string | null;
  article_source_url: string | null;
  article_published_date: string | null;
  config_a_extraction: Record<string, any> | null;
  config_a_confidence: number | null;
  config_a_duration_ms: number | null;
  config_a_error: string | null;
  config_b_extraction: Record<string, any> | null;
  config_b_confidence: number | null;
  config_b_duration_ms: number | null;
  config_b_error: string | null;
  config_a_stage1: Record<string, any> | null;
  config_b_stage1: Record<string, any> | null;
  config_a_stage2_results: any[];
  config_b_stage2_results: any[];
  config_a_total_tokens: number | null;
  config_b_total_tokens: number | null;
  config_a_total_latency_ms: number | null;
  config_b_total_latency_ms: number | null;
  review_status: string;
  chosen_config: string | null;
  golden_extraction: Record<string, any> | null;
  reviewer_notes: string | null;
  reviewed_at: string | null;
  created_at: string;
}

// ============================================================
// DatasetsTab — standalone component for the Extraction view
// ============================================================

export function DatasetsTab() {
  const [datasets, setDatasets] = useState<TestDataset[]>([]);
  const [selectedDataset, setSelectedDataset] = useState<TestDataset | null>(null);
  const [testCases, setTestCases] = useState<TestCase[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showCreateDataset, setShowCreateDataset] = useState(false);
  const [showCreateCase, setShowCreateCase] = useState(false);

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

  useEffect(() => {
    loadDatasets().finally(() => setLoading(false));
  }, [loadDatasets]);

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

  if (loading) return <div className="admin-loading">Loading datasets...</div>;

  return (
    <>
      <div className="page-actions" style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 12, marginTop: 8 }}>
        <button className="action-btn primary" onClick={() => setShowCreateDataset(true)}>
          + New Dataset
        </button>
      </div>

      {error && <div className="error-banner">{error}</div>}

      <SplitPane
        storageKey="prompt-test-datasets"
        defaultLeftWidth={420}
        minLeftWidth={280}
        maxLeftWidth={700}
        left={
        <div className="list-panel">
          <div className="list-header"><h3>Datasets ({datasets.length})</h3></div>
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
        }
        right={
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
        }
      />

      {showCreateDataset && (
        <div className="modal-overlay" onClick={() => setShowCreateDataset(false)}>
          <div className="modal-content" onClick={e => e.stopPropagation()}>
            <h3>Create Test Dataset</h3>
            <CreateDatasetForm onSubmit={handleCreateDataset} onCancel={() => setShowCreateDataset(false)} />
          </div>
        </div>
      )}

      {showCreateCase && selectedDataset && (
        <div className="modal-overlay" onClick={() => setShowCreateCase(false)}>
          <div className="modal-content" onClick={e => e.stopPropagation()} style={{ maxWidth: 700 }}>
            <h3>Add Test Case to {selectedDataset.name}</h3>
            <CreateCaseForm onSubmit={handleCreateCase} onCancel={() => setShowCreateCase(false)} />
          </div>
        </div>
      )}
    </>
  );
}

// ============================================================
// PipelineTestingTab — pipeline-oriented testing + legacy comparisons
// ============================================================

export function PipelineTestingTab() {
  const [comparisons, setComparisons] = useState<Comparison[]>([]);
  const [schemas, setSchemas] = useState<Schema[]>([]);
  const [datasets, setDatasets] = useState<TestDataset[]>([]);
  const [providerModels, setProviderModels] = useState<ProviderModel[]>([]);
  const [selectedComparison, setSelectedComparison] = useState<Comparison | null>(null);
  const [comparisonRuns, setComparisonRuns] = useState<{ config_a: TestRun[]; config_b: TestRun[] } | null>(null);
  const [calibrationArticles, setCalibrationArticles] = useState<CalibrationArticle[]>([]);
  const [showComparisonRuns, setShowComparisonRuns] = useState(false);
  const [showRunPipeline, setShowRunPipeline] = useState(false);
  const [showRunCalibration, setShowRunCalibration] = useState(false);
  const [showRunComparison, setShowRunComparison] = useState(false);
  const [showRunTest, setShowRunTest] = useState(false);
  const [reviewingArticle, setReviewingArticle] = useState<CalibrationArticle | null>(null);
  const [showSaveDataset, setShowSaveDataset] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const pollRef = useRef<number | null>(null);

  const loadProviderModels = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/admin/llm/models`);
      if (res.ok) {
        const data = await res.json();
        const providers = data.models || data;
        const result: ProviderModel[] = [];
        if (providers.anthropic) result.push({ provider: 'anthropic', models: providers.anthropic });
        if (providers.ollama) result.push({ provider: 'ollama', models: providers.ollama });
        if (result.length === 0 && typeof providers === 'object') {
          for (const [k, v] of Object.entries(providers)) {
            if (Array.isArray(v)) result.push({ provider: k, models: v as string[] });
          }
        }
        setProviderModels(result);
      }
    } catch { /* optional */ }
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

  const loadDatasets = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/admin/prompt-tests/datasets`);
      if (res.ok) {
        const data = await res.json();
        setDatasets(data.datasets || []);
      }
    } catch { /* optional */ }
  }, []);

  const loadComparisons = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/admin/prompt-tests/comparisons`);
      if (res.ok) {
        const data = await res.json();
        setComparisons(data.comparisons || []);
      }
    } catch { /* optional */ }
  }, []);

  const loadComparisonDetail = useCallback(async (id: string, mode?: string) => {
    try {
      const compRes = await fetch(`${API_BASE}/api/admin/prompt-tests/comparisons/${id}`);
      if (compRes.ok) {
        const comp = await compRes.json();
        setSelectedComparison(comp);
        const effectiveMode = mode || comp.mode;
        if (effectiveMode === 'calibration') {
          const artRes = await fetch(`${API_BASE}/api/admin/prompt-tests/calibrations/${id}/articles`);
          if (artRes.ok) {
            const artData = await artRes.json();
            setCalibrationArticles(artData.articles || []);
          }
        } else {
          const runsRes = await fetch(`${API_BASE}/api/admin/prompt-tests/comparisons/${id}/runs`);
          if (runsRes.ok) {
            const runsData = await runsRes.json();
            setComparisonRuns(runsData);
          }
        }
      }
    } catch { /* optional */ }
  }, []);

  useEffect(() => {
    Promise.all([loadComparisons(), loadProviderModels(), loadSchemas(), loadDatasets()])
      .finally(() => setLoading(false));
  }, [loadComparisons, loadProviderModels, loadSchemas, loadDatasets]);

  // Polling for running comparisons
  useEffect(() => {
    const hasActive = comparisons.some(c => c.status === 'pending' || c.status === 'running');
    if (hasActive) {
      pollRef.current = window.setInterval(() => {
        loadComparisons();
        if (selectedComparison && (selectedComparison.status === 'pending' || selectedComparison.status === 'running')) {
          loadComparisonDetail(selectedComparison.id, selectedComparison.mode);
        }
      }, 5000);
    }
    return () => {
      if (pollRef.current) {
        clearInterval(pollRef.current);
        pollRef.current = null;
      }
    };
  }, [comparisons, selectedComparison, loadComparisons, loadComparisonDetail]);

  const handleRunPipelineTest = async (data: {
    config_a_provider: string;
    config_a_model: string;
    config_b_provider: string;
    config_b_model: string;
    article_count: number;
    article_filters: Record<string, any>;
  }) => {
    setShowRunPipeline(false);
    try {
      const res = await fetch(`${API_BASE}/api/admin/prompt-tests/pipeline-calibrations`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
      });
      if (!res.ok) throw new Error('Failed to create pipeline test');
      await loadComparisons();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Pipeline test failed');
    }
  };

  const handleRunCalibration = async (data: {
    schema_id: string;
    config_a_provider: string;
    config_a_model: string;
    config_b_provider: string;
    config_b_model: string;
    article_count: number;
    article_filters: Record<string, any>;
  }) => {
    setShowRunCalibration(false);
    try {
      const res = await fetch(`${API_BASE}/api/admin/prompt-tests/calibrations`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
      });
      if (!res.ok) throw new Error('Failed to create calibration');
      await loadComparisons();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Calibration failed');
    }
  };

  const handleRunComparison = async (data: {
    schema_id: string;
    dataset_id: string;
    config_a_provider: string;
    config_a_model: string;
    config_b_provider: string;
    config_b_model: string;
    iterations_per_config: number;
  }) => {
    setShowRunComparison(false);
    try {
      const res = await fetch(`${API_BASE}/api/admin/prompt-tests/comparisons`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
      });
      if (!res.ok) throw new Error('Failed to create comparison');
      await loadComparisons();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Comparison failed');
    }
  };

  const handleRunTest = async (schemaId: string, datasetId: string, providerName?: string, modelName?: string) => {
    setRunning(true);
    setShowRunTest(false);
    try {
      const body: Record<string, string> = { schema_id: schemaId, dataset_id: datasetId };
      if (providerName) body.provider_name = providerName;
      if (modelName) body.model_name = modelName;
      const res = await fetch(`${API_BASE}/api/admin/prompt-tests/run`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      if (!res.ok) throw new Error('Test run failed');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Run failed');
    } finally {
      setRunning(false);
    }
  };

  const handleReviewArticle = async (
    articleId: string,
    comparisonId: string,
    chosenConfig: string | null,
    goldenExtraction: Record<string, any> | null,
    notes: string | null,
  ) => {
    try {
      const res = await fetch(
        `${API_BASE}/api/admin/prompt-tests/calibrations/${comparisonId}/articles/${articleId}/review`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            chosen_config: chosenConfig,
            golden_extraction: goldenExtraction,
            reviewer_notes: notes,
          }),
        },
      );
      if (!res.ok) throw new Error('Failed to save review');
      setReviewingArticle(null);
      await loadComparisonDetail(comparisonId, 'calibration');
      await loadComparisons();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Review failed');
    }
  };

  const handleSaveDataset = async (comparisonId: string, name: string, description: string) => {
    try {
      const res = await fetch(
        `${API_BASE}/api/admin/prompt-tests/calibrations/${comparisonId}/save-dataset`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ name, description: description || null }),
        },
      );
      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || 'Failed to save dataset');
      }
      setShowSaveDataset(false);
      await loadComparisonDetail(comparisonId, 'calibration');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Save dataset failed');
    }
  };

  const handleSelectComparison = (comp: Comparison) => {
    setSelectedComparison(comp);
    setComparisonRuns(null);
    setCalibrationArticles([]);
    setShowComparisonRuns(false);
    loadComparisonDetail(comp.id, comp.mode);
  };

  const formatPct = (v: number | null) => v != null ? `${(v * 100).toFixed(1)}%` : '\u2014';
  const formatPctWithStd = (stats: MetricStats) =>
    `${(stats.mean * 100).toFixed(1)}% \u00B1${(stats.std * 100).toFixed(1)}%`;
  const formatMs = (stats: MetricStats) =>
    `${(stats.mean / 1000).toFixed(1)}s \u00B1${(stats.std / 1000).toFixed(1)}s`;

  const statusColor = (s: string) => {
    if (s === 'passed' || s === 'completed') return '#22c55e';
    if (s === 'failed') return '#ef4444';
    if (s === 'running') return '#f59e0b';
    if (s === 'pending') return '#6b7280';
    return '#6b7280';
  };

  if (loading) return <div className="admin-loading">Loading pipeline testing...</div>;

  return (
    <>
      <div className="page-actions" style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginBottom: 12, marginTop: 8 }}>
        {running && <span style={{ fontSize: 13, color: 'var(--text-muted)', alignSelf: 'center' }}>Running...</span>}
        <button className="action-btn primary" onClick={() => setShowRunPipeline(true)}>
          Run Pipeline Test
        </button>
        <button className="action-btn" onClick={() => setShowRunCalibration(true)}>
          Calibrate (Schema)
        </button>
        <button className="action-btn" onClick={() => setShowRunComparison(true)}>
          Compare (Dataset)
        </button>
        <button className="action-btn" onClick={() => setShowRunTest(true)} disabled={running}>
          Run Test
        </button>
      </div>

      {error && <div className="error-banner">{error}</div>}

      <SplitPane
        storageKey="pipeline-testing-comparisons"
        defaultLeftWidth={480}
        minLeftWidth={320}
        maxLeftWidth={750}
        left={
        <div className="list-panel">
          <div className="list-header"><h3>Comparisons ({comparisons.length})</h3></div>
          {comparisons.length === 0 ? (
            <div className="empty-state"><p>No comparisons yet. Click "Run Pipeline Test" to start.</p></div>
          ) : (
            <div className="table-container" style={{ border: 'none' }}>
              <table className="data-table">
                <thead>
                  <tr><th>Type</th><th>Mode</th><th>Status</th><th>Config A</th><th>Config B</th><th>Result</th><th>Date</th></tr>
                </thead>
                <tbody>
                  {comparisons.map(c => {
                    const summary = c.summary_stats as ComparisonSummary | null;
                    const hasSummary = summary && 'winner' in summary;
                    const isCalibration = c.mode === 'calibration';
                    const isPipeline = (c.comparison_type || 'schema') === 'pipeline';
                    return (
                      <tr key={c.id}
                        className={selectedComparison?.id === c.id ? 'selected' : ''}
                        onClick={() => handleSelectComparison(c)}
                        style={{ cursor: 'pointer' }}
                      >
                        <td style={{ fontWeight: 500, fontSize: 11 }}>
                          {isPipeline ? (
                            <span style={{ padding: '1px 6px', borderRadius: 8, fontSize: 10, fontWeight: 600,
                              background: 'rgba(168,85,247,0.15)', color: '#a855f7' }}>pipeline</span>
                          ) : (
                            c.schema_name || (c.schema_id ? c.schema_id.slice(0, 8) : '\u2014')
                          )}
                        </td>
                        <td>
                          <span style={{
                            padding: '1px 6px', borderRadius: 8, fontSize: 10, fontWeight: 600,
                            background: isCalibration ? 'rgba(139,92,246,0.15)' : 'rgba(59,130,246,0.15)',
                            color: isCalibration ? '#8b5cf6' : '#3b82f6',
                          }}>
                            {isCalibration ? 'calibration' : 'dataset'}
                          </span>
                        </td>
                        <td>
                          {(c.status === 'running' || c.status === 'pending') ? (
                            <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                              <span style={{ background: statusColor(c.status), color: '#fff', padding: '2px 8px', borderRadius: 12, fontSize: 11, fontWeight: 600 }}>
                                {c.status}
                              </span>
                              {c.total_iterations > 0 && (
                                <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>
                                  {c.progress}/{c.total_iterations}
                                </span>
                              )}
                            </div>
                          ) : (
                            <span style={{ background: statusColor(c.status), color: '#fff', padding: '2px 8px', borderRadius: 12, fontSize: 11, fontWeight: 600 }}>
                              {c.status}
                            </span>
                          )}
                        </td>
                        <td style={{ fontSize: 11 }}>{c.config_a_provider}/{c.config_a_model.split('/').pop()}</td>
                        <td style={{ fontSize: 11 }}>{c.config_b_provider}/{c.config_b_model.split('/').pop()}</td>
                        <td style={{ fontWeight: 600, fontSize: 12 }}>
                          {isCalibration
                            ? (c.total_articles > 0 ? `${c.reviewed_count}/${c.total_articles} reviewed` : '\u2014')
                            : (hasSummary ? `${(summary!.f1_delta * 100).toFixed(1)}% F1\u0394` : '\u2014')
                          }
                        </td>
                        <td style={{ fontSize: 12, color: 'var(--text-muted)' }}>
                          {new Date(c.created_at).toLocaleDateString()}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
        }
        right={
        <div className="detail-panel">
          {selectedComparison ? (
            <ComparisonDetail
              comparison={selectedComparison}
              runs={comparisonRuns}
              showRuns={showComparisonRuns}
              onToggleRuns={() => setShowComparisonRuns(v => !v)}
              formatPct={formatPct}
              formatPctWithStd={formatPctWithStd}
              formatMs={formatMs}
              statusColor={statusColor}
              calibrationArticles={calibrationArticles}
              onReviewArticle={setReviewingArticle}
              onSaveDataset={() => setShowSaveDataset(true)}
            />
          ) : (
            <div className="empty-state"><p>Select a comparison to view results</p></div>
          )}
        </div>
        }
      />

      {/* Run Pipeline Test Modal (no schema) */}
      {showRunPipeline && (
        <div className="modal-overlay" onClick={() => setShowRunPipeline(false)}>
          <div className="modal-content" onClick={e => e.stopPropagation()} style={{ maxWidth: 700 }}>
            <h3>Run Pipeline Test</h3>
            <RunPipelineCalibrationForm
              providerModels={providerModels}
              onSubmit={handleRunPipelineTest}
              onCancel={() => setShowRunPipeline(false)}
            />
          </div>
        </div>
      )}

      {/* Run Calibration Modal (schema-based) */}
      {showRunCalibration && (
        <div className="modal-overlay" onClick={() => setShowRunCalibration(false)}>
          <div className="modal-content" onClick={e => e.stopPropagation()} style={{ maxWidth: 700 }}>
            <h3>Calibrate Models (Schema)</h3>
            <RunCalibrationForm
              schemas={schemas}
              providerModels={providerModels}
              onSubmit={handleRunCalibration}
              onCancel={() => setShowRunCalibration(false)}
            />
          </div>
        </div>
      )}

      {/* Run Comparison Modal (dataset-based) */}
      {showRunComparison && (
        <div className="modal-overlay" onClick={() => setShowRunComparison(false)}>
          <div className="modal-content" onClick={e => e.stopPropagation()} style={{ maxWidth: 700 }}>
            <h3>Run Model Comparison (Dataset)</h3>
            <RunComparisonForm
              schemas={schemas}
              datasets={datasets}
              providerModels={providerModels}
              onSubmit={handleRunComparison}
              onCancel={() => setShowRunComparison(false)}
            />
          </div>
        </div>
      )}

      {/* Run Test Modal (single schema) */}
      {showRunTest && (
        <div className="modal-overlay" onClick={() => setShowRunTest(false)}>
          <div className="modal-content" onClick={e => e.stopPropagation()}>
            <h3>Run Prompt Test</h3>
            <RunTestForm schemas={schemas} datasets={datasets} providerModels={providerModels} onSubmit={handleRunTest} onCancel={() => setShowRunTest(false)} />
          </div>
        </div>
      )}

      {/* Calibration Review Modal */}
      {reviewingArticle && selectedComparison && (
        <CalibrationReviewModal
          article={reviewingArticle}
          comparison={selectedComparison}
          onSave={(chosenConfig, goldenExtraction, notes) =>
            handleReviewArticle(reviewingArticle.id, selectedComparison.id, chosenConfig, goldenExtraction, notes)
          }
          onCancel={() => setReviewingArticle(null)}
        />
      )}

      {/* Save as Dataset Modal */}
      {showSaveDataset && selectedComparison && (
        <div className="modal-overlay" onClick={() => setShowSaveDataset(false)}>
          <div className="modal-content" onClick={e => e.stopPropagation()}>
            <h3>Save as Golden Dataset</h3>
            <SaveDatasetModal
              reviewedCount={selectedComparison.reviewed_count}
              onSave={(name, description) => handleSaveDataset(selectedComparison.id, name, description)}
              onCancel={() => setShowSaveDataset(false)}
            />
          </div>
        </div>
      )}
    </>
  );
}

// ============================================================
// Legacy PromptTestRunner (kept for backward compat; unused in new nav)
// ============================================================

export function PromptTestRunner() {
  return (
    <div className="admin-page">
      <div className="page-header">
        <h2>Prompt Testing</h2>
      </div>
      <div className="detail-tabs">
        <button className="tab active">Datasets</button>
        <button className="tab">Pipeline Testing</button>
      </div>
      <DatasetsTab />
    </div>
  );
}

// ============================================================
// ComparisonDetail — shared detail view for calibration + dataset comparisons
// ============================================================

function ComparisonDetail({
  comparison,
  runs,
  showRuns,
  onToggleRuns,
  formatPct,
  formatPctWithStd,
  formatMs,
  statusColor,
  calibrationArticles,
  onReviewArticle,
  onSaveDataset,
}: {
  comparison: Comparison;
  runs: { config_a: TestRun[]; config_b: TestRun[] } | null;
  showRuns: boolean;
  onToggleRuns: () => void;
  formatPct: (v: number | null) => string;
  formatPctWithStd: (stats: MetricStats) => string;
  formatMs: (stats: MetricStats) => string;
  statusColor: (s: string) => string;
  calibrationArticles: CalibrationArticle[];
  onReviewArticle: (article: CalibrationArticle) => void;
  onSaveDataset: () => void;
}) {
  const summary = (comparison.summary_stats && 'winner' in comparison.summary_stats)
    ? comparison.summary_stats as ComparisonSummary
    : null;
  const isRunning = comparison.status === 'running' || comparison.status === 'pending';
  const isCalibration = comparison.mode === 'calibration';
  const isPipeline = (comparison.comparison_type || 'schema') === 'pipeline';

  const reviewStatusColor = (s: string) => {
    if (s === 'reviewed') return '#22c55e';
    if (s === 'skipped') return '#6b7280';
    return '#f59e0b';
  };

  return (
    <>
      <div className="detail-header">
        <h3>
          {isPipeline ? 'Pipeline Comparison' : isCalibration ? 'Calibration' : 'Comparison'}
          {comparison.schema_name ? `: ${comparison.schema_name}` : ''}
        </h3>
        {isCalibration && comparison.status === 'completed' && comparison.reviewed_count > 0 && !comparison.output_dataset_id && (
          <button className="action-btn primary" onClick={onSaveDataset}>
            Save as Dataset
          </button>
        )}
      </div>
      <div className="detail-content">
        {/* Status banner */}
        {isRunning && (
          <div style={{
            padding: '10px 16px', borderRadius: 8, marginBottom: 16,
            background: 'rgba(245,158,11,0.1)', border: '1px solid rgba(245,158,11,0.3)',
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
              <span style={{ fontWeight: 600, fontSize: 13, color: '#f59e0b' }}>
                Running... {comparison.message || ''}
              </span>
              <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>
                {comparison.progress}/{comparison.total_iterations}
              </span>
            </div>
            <div style={{
              height: 6, borderRadius: 3, background: 'rgba(245,158,11,0.2)', overflow: 'hidden',
            }}>
              <div style={{
                height: '100%', borderRadius: 3, background: '#f59e0b',
                width: comparison.total_iterations > 0
                  ? `${(comparison.progress / comparison.total_iterations) * 100}%`
                  : '0%',
                transition: 'width 0.3s ease',
              }} />
            </div>
          </div>
        )}

        {comparison.status === 'failed' && (
          <div style={{
            padding: '10px 16px', borderRadius: 8, marginBottom: 16,
            background: 'rgba(239,68,68,0.1)', border: '1px solid rgba(239,68,68,0.3)',
            color: '#ef4444', fontSize: 13,
          }}>
            Failed: {comparison.error || 'Unknown error'}
          </div>
        )}

        {/* Dataset-mode winner banner */}
        {!isCalibration && comparison.status === 'completed' && summary && (
          <div style={{
            padding: '10px 16px', borderRadius: 8, marginBottom: 16,
            background: 'rgba(34,197,94,0.1)', border: '1px solid rgba(34,197,94,0.3)',
          }}>
            <span style={{ fontWeight: 600, fontSize: 13, color: '#22c55e' }}>
              Winner: {summary.winner === 'config_a' ? 'Config A' : 'Config B'}
              {' '}({summary.winner === 'config_a' ? summary.config_a.label : summary.config_b.label})
            </span>
            <span style={{ fontSize: 12, color: 'var(--text-muted)', marginLeft: 12 }}>
              F1 delta: {(summary.f1_delta * 100).toFixed(1)}%
              {summary.statistically_significant && ' (statistically significant)'}
            </span>
          </div>
        )}

        {/* Calibration review progress */}
        {isCalibration && comparison.status === 'completed' && (
          <div style={{
            padding: '10px 16px', borderRadius: 8, marginBottom: 16,
            background: comparison.output_dataset_id
              ? 'rgba(34,197,94,0.1)' : 'rgba(59,130,246,0.1)',
            border: comparison.output_dataset_id
              ? '1px solid rgba(34,197,94,0.3)' : '1px solid rgba(59,130,246,0.3)',
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
              <span style={{ fontWeight: 600, fontSize: 13, color: comparison.output_dataset_id ? '#22c55e' : '#3b82f6' }}>
                {comparison.output_dataset_id
                  ? 'Dataset saved'
                  : `Review progress: ${comparison.reviewed_count}/${comparison.total_articles}`
                }
              </span>
              {!comparison.output_dataset_id && comparison.total_articles > 0 && (
                <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>
                  {Math.round((comparison.reviewed_count / comparison.total_articles) * 100)}%
                </span>
              )}
            </div>
            {!comparison.output_dataset_id && comparison.total_articles > 0 && (
              <div style={{
                height: 6, borderRadius: 3, background: 'rgba(59,130,246,0.2)', overflow: 'hidden',
              }}>
                <div style={{
                  height: '100%', borderRadius: 3, background: '#3b82f6',
                  width: `${(comparison.reviewed_count / comparison.total_articles) * 100}%`,
                  transition: 'width 0.3s ease',
                }} />
              </div>
            )}
          </div>
        )}

        {/* Config info */}
        <div className="detail-section" style={{ marginBottom: 16 }}>
          {isPipeline && (
            <div className="detail-kv">
              <span className="detail-label">Type</span>
              <span className="detail-value">Full Pipeline (Stage 1 + Stage 2)</span>
            </div>
          )}
          {!isCalibration && !isPipeline && (
            <div className="detail-kv">
              <span className="detail-label">Dataset</span>
              <span className="detail-value">{comparison.dataset_name || '\u2014'}</span>
            </div>
          )}
          {isCalibration && (
            <div className="detail-kv">
              <span className="detail-label">Articles</span>
              <span className="detail-value">{comparison.total_articles || comparison.article_count || '\u2014'}</span>
            </div>
          )}
          <div className="detail-kv">
            <span className="detail-label">{isCalibration ? 'Mode' : 'Iterations'}</span>
            <span className="detail-value">
              {isCalibration
                ? (isPipeline ? 'Pipeline Calibration' : 'Schema Calibration')
                : `${comparison.iterations_per_config} per config`}
            </span>
          </div>
          <div className="detail-kv">
            <span className="detail-label">Config A</span>
            <span className="detail-value">{comparison.config_a_provider}/{comparison.config_a_model}</span>
          </div>
          <div className="detail-kv">
            <span className="detail-label">Config B</span>
            <span className="detail-value">{comparison.config_b_provider}/{comparison.config_b_model}</span>
          </div>
        </div>

        {/* Side-by-side metrics table (dataset mode only) */}
        {!isCalibration && summary && (
          <div style={{ marginBottom: 20 }}>
            <h4 style={{ marginBottom: 8 }}>Metrics Comparison</h4>
            <div className="table-container">
              <table className="data-table" style={{ fontSize: 13 }}>
                <thead>
                  <tr>
                    <th></th>
                    <th style={{ textAlign: 'center' }}>
                      Config A
                      <div style={{ fontSize: 10, fontWeight: 400, color: 'var(--text-muted)' }}>
                        {comparison.config_a_provider}/{comparison.config_a_model.split('/').pop()}
                      </div>
                    </th>
                    <th style={{ textAlign: 'center' }}>
                      Config B
                      <div style={{ fontSize: 10, fontWeight: 400, color: 'var(--text-muted)' }}>
                        {comparison.config_b_provider}/{comparison.config_b_model.split('/').pop()}
                      </div>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {([
                    { label: 'Precision', key: 'precision' as const },
                    { label: 'Recall', key: 'recall' as const },
                    { label: 'F1 Score', key: 'f1_score' as const },
                  ] as const).map(({ label, key }) => {
                    const aWins = summary.config_a[key].mean > summary.config_b[key].mean;
                    const bWins = summary.config_b[key].mean > summary.config_a[key].mean;
                    const isF1 = key === 'f1_score';
                    return (
                      <tr key={key}>
                        <td style={{ fontWeight: 500 }}>{label}</td>
                        <td style={{
                          textAlign: 'center', fontWeight: 600,
                          background: (isF1 && summary.winner === 'config_a') ? 'rgba(34,197,94,0.1)' : undefined,
                          color: aWins ? '#22c55e' : undefined,
                        }}>
                          {formatPctWithStd(summary.config_a[key])}
                          {isF1 && summary.winner === 'config_a' && ' \u2605'}
                        </td>
                        <td style={{
                          textAlign: 'center', fontWeight: 600,
                          background: (isF1 && summary.winner === 'config_b') ? 'rgba(34,197,94,0.1)' : undefined,
                          color: bWins ? '#22c55e' : undefined,
                        }}>
                          {formatPctWithStd(summary.config_b[key])}
                          {isF1 && summary.winner === 'config_b' && ' \u2605'}
                        </td>
                      </tr>
                    );
                  })}
                  <tr>
                    <td style={{ fontWeight: 500 }}>Pass Rate</td>
                    <td style={{ textAlign: 'center' }}>{(summary.config_a.passed_rate * 100).toFixed(1)}%</td>
                    <td style={{ textAlign: 'center' }}>{(summary.config_b.passed_rate * 100).toFixed(1)}%</td>
                  </tr>
                  <tr>
                    <td style={{ fontWeight: 500 }}>Avg Duration</td>
                    <td style={{ textAlign: 'center' }}>{formatMs(summary.config_a.duration_ms)}</td>
                    <td style={{ textAlign: 'center' }}>{formatMs(summary.config_b.duration_ms)}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
        )}

        {/* Calibration articles list */}
        {isCalibration && calibrationArticles.length > 0 && (
          <div>
            <h4 style={{ marginBottom: 8 }}>Articles ({calibrationArticles.length})</h4>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              {calibrationArticles.map(art => (
                <div
                  key={art.id}
                  onClick={() => onReviewArticle(art)}
                  style={{
                    padding: '10px 14px', background: 'var(--bg-secondary)', borderRadius: 8,
                    cursor: 'pointer', fontSize: 13, display: 'flex', justifyContent: 'space-between',
                    alignItems: 'center', border: '1px solid transparent',
                  }}
                  onMouseEnter={e => (e.currentTarget.style.borderColor = 'var(--border-color)')}
                  onMouseLeave={e => (e.currentTarget.style.borderColor = 'transparent')}
                >
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontWeight: 500, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {art.article_title || 'Untitled'}
                    </div>
                    <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 2 }}>
                      A: {art.config_a_confidence != null ? `${(art.config_a_confidence * 100).toFixed(0)}%` : (art.config_a_error ? 'error' : '\u2014')}
                      {' | '}
                      B: {art.config_b_confidence != null ? `${(art.config_b_confidence * 100).toFixed(0)}%` : (art.config_b_error ? 'error' : '\u2014')}
                      {isPipeline && art.config_a_total_tokens != null && (
                        <> | tokens: {art.config_a_total_tokens}/{art.config_b_total_tokens}</>
                      )}
                    </div>
                  </div>
                  <span style={{
                    padding: '2px 8px', borderRadius: 12, fontSize: 10, fontWeight: 600,
                    background: reviewStatusColor(art.review_status),
                    color: '#fff', marginLeft: 8, whiteSpace: 'nowrap',
                  }}>
                    {art.review_status}
                    {art.chosen_config && ` (${art.chosen_config})`}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Individual runs (dataset mode, collapsible) */}
        {!isCalibration && runs && (
          <div>
            <button
              className="action-btn"
              onClick={onToggleRuns}
              style={{ marginBottom: 8, fontSize: 12 }}
            >
              {showRuns ? 'Hide' : 'Show'} Individual Runs ({(runs.config_a.length + runs.config_b.length)})
            </button>
            {showRuns && (
              <div style={{ display: 'flex', gap: 16 }}>
                <div style={{ flex: 1 }}>
                  <h5 style={{ marginBottom: 6, fontSize: 12, color: 'var(--text-muted)' }}>
                    Config A ({comparison.config_a_provider}/{comparison.config_a_model.split('/').pop()})
                  </h5>
                  {runs.config_a.map(r => (
                    <div key={r.id} style={{
                      padding: 8, background: 'var(--bg-secondary)', borderRadius: 6,
                      marginBottom: 4, fontSize: 12,
                    }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                        <span>Iter {r.iteration_number}</span>
                        <span style={{
                          background: statusColor(r.status), color: '#fff',
                          padding: '1px 6px', borderRadius: 8, fontSize: 10, fontWeight: 600,
                        }}>
                          {r.status}
                        </span>
                      </div>
                      <div style={{ color: 'var(--text-secondary)', marginTop: 4 }}>
                        P: {formatPct(r.precision)} | R: {formatPct(r.recall)} | F1: {formatPct(r.f1_score)}
                      </div>
                    </div>
                  ))}
                </div>
                <div style={{ flex: 1 }}>
                  <h5 style={{ marginBottom: 6, fontSize: 12, color: 'var(--text-muted)' }}>
                    Config B ({comparison.config_b_provider}/{comparison.config_b_model.split('/').pop()})
                  </h5>
                  {runs.config_b.map(r => (
                    <div key={r.id} style={{
                      padding: 8, background: 'var(--bg-secondary)', borderRadius: 6,
                      marginBottom: 4, fontSize: 12,
                    }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                        <span>Iter {r.iteration_number}</span>
                        <span style={{
                          background: statusColor(r.status), color: '#fff',
                          padding: '1px 6px', borderRadius: 8, fontSize: 10, fontWeight: 600,
                        }}>
                          {r.status}
                        </span>
                      </div>
                      <div style={{ color: 'var(--text-secondary)', marginTop: 4 }}>
                        P: {formatPct(r.precision)} | R: {formatPct(r.recall)} | F1: {formatPct(r.f1_score)}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </>
  );
}

// ============================================================
// Sub-forms
// ============================================================

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

function RunTestForm({ schemas, datasets, providerModels, onSubmit, onCancel }: {
  schemas: { id: string; name: string }[];
  datasets: TestDataset[];
  providerModels: ProviderModel[];
  onSubmit: (schemaId: string, datasetId: string, providerName?: string, modelName?: string) => void;
  onCancel: () => void;
}) {
  const [schemaId, setSchemaId] = useState('');
  const [datasetId, setDatasetId] = useState('');
  const [providerName, setProviderName] = useState('');
  const [modelName, setModelName] = useState('');
  const inputStyle = { width: '100%', padding: '8px 10px', borderRadius: 6, border: '1px solid var(--border-color)', fontSize: 13, background: 'var(--bg-primary)' };

  const availableModels = providerName
    ? providerModels.find(p => p.provider === providerName)?.models || []
    : [];

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
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
        <div>
          <label style={{ fontSize: 12, fontWeight: 600, display: 'block', marginBottom: 4 }}>Provider (optional)</label>
          <select value={providerName} onChange={e => { setProviderName(e.target.value); setModelName(''); }} style={inputStyle as any}>
            <option value="">Schema default</option>
            {providerModels.map(p => <option key={p.provider} value={p.provider}>{p.provider}</option>)}
          </select>
        </div>
        <div>
          <label style={{ fontSize: 12, fontWeight: 600, display: 'block', marginBottom: 4 }}>Model (optional)</label>
          {providerName ? (
            <select value={modelName} onChange={e => setModelName(e.target.value)} style={inputStyle as any}>
              <option value="">Schema default</option>
              {availableModels.map(m => <option key={m} value={m}>{m}</option>)}
            </select>
          ) : (
            <input value={modelName} onChange={e => setModelName(e.target.value)} placeholder="Schema default" style={inputStyle} />
          )}
        </div>
      </div>
      <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
        <button className="action-btn" onClick={onCancel}>Cancel</button>
        <button
          className="action-btn primary"
          onClick={() => onSubmit(schemaId, datasetId, providerName || undefined, modelName || undefined)}
          disabled={!schemaId || !datasetId}
        >
          Run Test Suite
        </button>
      </div>
    </div>
  );
}

function RunComparisonForm({ schemas, datasets, providerModels, onSubmit, onCancel }: {
  schemas: { id: string; name: string }[];
  datasets: TestDataset[];
  providerModels: ProviderModel[];
  onSubmit: (data: {
    schema_id: string;
    dataset_id: string;
    config_a_provider: string;
    config_a_model: string;
    config_b_provider: string;
    config_b_model: string;
    iterations_per_config: number;
  }) => void;
  onCancel: () => void;
}) {
  const [schemaId, setSchemaId] = useState('');
  const [datasetId, setDatasetId] = useState('');
  const [iterations, setIterations] = useState(3);
  const [aProvider, setAProvider] = useState('');
  const [aModel, setAModel] = useState('');
  const [bProvider, setBProvider] = useState('');
  const [bModel, setBModel] = useState('');
  const inputStyle = { width: '100%', padding: '8px 10px', borderRadius: 6, border: '1px solid var(--border-color)', fontSize: 13, background: 'var(--bg-primary)' };

  const canSubmit = schemaId && datasetId && aProvider && aModel && bProvider && bModel && iterations >= 1 && iterations <= 10;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 120px', gap: 12 }}>
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
            {datasets.map(d => <option key={d.id} value={d.id}>{d.name} ({d.case_count})</option>)}
          </select>
        </div>
        <div>
          <label style={{ fontSize: 12, fontWeight: 600, display: 'block', marginBottom: 4 }}>Iterations</label>
          <input
            type="number" min={1} max={10} value={iterations}
            onChange={e => setIterations(Math.max(1, Math.min(10, parseInt(e.target.value) || 1)))}
            style={inputStyle}
          />
        </div>
      </div>

      <ConfigPairForm
        providerModels={providerModels}
        aProvider={aProvider} aModel={aModel}
        bProvider={bProvider} bModel={bModel}
        setAProvider={setAProvider} setAModel={setAModel}
        setBProvider={setBProvider} setBModel={setBModel}
        inputStyle={inputStyle}
      />

      <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
        <button className="action-btn" onClick={onCancel}>Cancel</button>
        <button
          className="action-btn primary"
          onClick={() => onSubmit({
            schema_id: schemaId, dataset_id: datasetId,
            config_a_provider: aProvider, config_a_model: aModel,
            config_b_provider: bProvider, config_b_model: bModel,
            iterations_per_config: iterations,
          })}
          disabled={!canSubmit}
        >
          Run Comparison
        </button>
      </div>
    </div>
  );
}

/** Pipeline calibration form — no schema dropdown */
function RunPipelineCalibrationForm({ providerModels, onSubmit, onCancel }: {
  providerModels: ProviderModel[];
  onSubmit: (data: {
    config_a_provider: string;
    config_a_model: string;
    config_b_provider: string;
    config_b_model: string;
    article_count: number;
    article_filters: Record<string, any>;
  }) => void;
  onCancel: () => void;
}) {
  const [articleCount, setArticleCount] = useState(20);
  const [filterStatus, setFilterStatus] = useState('');
  const [filterMinDate, setFilterMinDate] = useState('');
  const [filterMaxDate, setFilterMaxDate] = useState('');
  const [aProvider, setAProvider] = useState('');
  const [aModel, setAModel] = useState('');
  const [bProvider, setBProvider] = useState('');
  const [bModel, setBModel] = useState('');
  const inputStyle = { width: '100%', padding: '8px 10px', borderRadius: 6, border: '1px solid var(--border-color)', fontSize: 13, background: 'var(--bg-primary)' };

  const canSubmit = aProvider && aModel && bProvider && bModel && articleCount >= 1 && articleCount <= 100;

  const buildFilters = () => {
    const filters: Record<string, any> = {};
    if (filterStatus) filters.status = filterStatus;
    if (filterMinDate) filters.min_date = filterMinDate;
    if (filterMaxDate) filters.max_date = filterMaxDate;
    return filters;
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
      <p style={{ fontSize: 13, color: 'var(--text-secondary)', margin: 0 }}>
        Runs the full two-stage extraction pipeline (Stage 1 + all auto-selected Stage 2 schemas) for each article with each model config.
      </p>

      <div>
        <label style={{ fontSize: 12, fontWeight: 600, display: 'block', marginBottom: 4 }}>Article Count</label>
        <input
          type="number" min={1} max={100} value={articleCount}
          onChange={e => setArticleCount(Math.max(1, Math.min(100, parseInt(e.target.value) || 1)))}
          style={{ ...inputStyle, maxWidth: 120 }}
        />
      </div>

      {/* Article filters */}
      <div style={{ padding: 12, border: '1px solid var(--border-color)', borderRadius: 8 }}>
        <div style={{ fontSize: 12, fontWeight: 700, marginBottom: 8, color: 'var(--text-muted)' }}>Filters (optional)</div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 10 }}>
          <div>
            <label style={{ fontSize: 11, fontWeight: 600, display: 'block', marginBottom: 3 }}>Status</label>
            <select value={filterStatus} onChange={e => setFilterStatus(e.target.value)} style={inputStyle as any}>
              <option value="">Any</option>
              <option value="pending">Pending</option>
              <option value="processed">Processed</option>
              <option value="ingested">Ingested</option>
            </select>
          </div>
          <div>
            <label style={{ fontSize: 11, fontWeight: 600, display: 'block', marginBottom: 3 }}>Min Date</label>
            <input type="date" value={filterMinDate} onChange={e => setFilterMinDate(e.target.value)} style={inputStyle} />
          </div>
          <div>
            <label style={{ fontSize: 11, fontWeight: 600, display: 'block', marginBottom: 3 }}>Max Date</label>
            <input type="date" value={filterMaxDate} onChange={e => setFilterMaxDate(e.target.value)} style={inputStyle} />
          </div>
        </div>
      </div>

      <ConfigPairForm
        providerModels={providerModels}
        aProvider={aProvider} aModel={aModel}
        bProvider={bProvider} bModel={bModel}
        setAProvider={setAProvider} setAModel={setAModel}
        setBProvider={setBProvider} setBModel={setBModel}
        inputStyle={inputStyle}
      />

      <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
        <button className="action-btn" onClick={onCancel}>Cancel</button>
        <button
          className="action-btn primary"
          onClick={() => onSubmit({
            config_a_provider: aProvider, config_a_model: aModel,
            config_b_provider: bProvider, config_b_model: bModel,
            article_count: articleCount, article_filters: buildFilters(),
          })}
          disabled={!canSubmit}
        >
          Run Pipeline Test
        </button>
      </div>
    </div>
  );
}

function RunCalibrationForm({ schemas, providerModels, onSubmit, onCancel }: {
  schemas: { id: string; name: string }[];
  providerModels: ProviderModel[];
  onSubmit: (data: {
    schema_id: string;
    config_a_provider: string;
    config_a_model: string;
    config_b_provider: string;
    config_b_model: string;
    article_count: number;
    article_filters: Record<string, any>;
  }) => void;
  onCancel: () => void;
}) {
  const [schemaId, setSchemaId] = useState('');
  const [articleCount, setArticleCount] = useState(20);
  const [filterStatus, setFilterStatus] = useState('');
  const [filterMinDate, setFilterMinDate] = useState('');
  const [filterMaxDate, setFilterMaxDate] = useState('');
  const [aProvider, setAProvider] = useState('');
  const [aModel, setAModel] = useState('');
  const [bProvider, setBProvider] = useState('');
  const [bModel, setBModel] = useState('');
  const inputStyle = { width: '100%', padding: '8px 10px', borderRadius: 6, border: '1px solid var(--border-color)', fontSize: 13, background: 'var(--bg-primary)' };

  const canSubmit = schemaId && aProvider && aModel && bProvider && bModel && articleCount >= 1 && articleCount <= 100;

  const buildFilters = () => {
    const filters: Record<string, any> = {};
    if (filterStatus) filters.status = filterStatus;
    if (filterMinDate) filters.min_date = filterMinDate;
    if (filterMaxDate) filters.max_date = filterMaxDate;
    return filters;
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 120px', gap: 12 }}>
        <div>
          <label style={{ fontSize: 12, fontWeight: 600, display: 'block', marginBottom: 4 }}>Schema *</label>
          <select value={schemaId} onChange={e => setSchemaId(e.target.value)} style={inputStyle as any}>
            <option value="">Select schema...</option>
            {schemas.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
          </select>
        </div>
        <div>
          <label style={{ fontSize: 12, fontWeight: 600, display: 'block', marginBottom: 4 }}>Article Count</label>
          <input
            type="number" min={1} max={100} value={articleCount}
            onChange={e => setArticleCount(Math.max(1, Math.min(100, parseInt(e.target.value) || 1)))}
            style={inputStyle}
          />
        </div>
      </div>

      <div style={{ padding: 12, border: '1px solid var(--border-color)', borderRadius: 8 }}>
        <div style={{ fontSize: 12, fontWeight: 700, marginBottom: 8, color: 'var(--text-muted)' }}>Filters (optional)</div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 10 }}>
          <div>
            <label style={{ fontSize: 11, fontWeight: 600, display: 'block', marginBottom: 3 }}>Status</label>
            <select value={filterStatus} onChange={e => setFilterStatus(e.target.value)} style={inputStyle as any}>
              <option value="">Any</option>
              <option value="pending">Pending</option>
              <option value="processed">Processed</option>
              <option value="ingested">Ingested</option>
            </select>
          </div>
          <div>
            <label style={{ fontSize: 11, fontWeight: 600, display: 'block', marginBottom: 3 }}>Min Date</label>
            <input type="date" value={filterMinDate} onChange={e => setFilterMinDate(e.target.value)} style={inputStyle} />
          </div>
          <div>
            <label style={{ fontSize: 11, fontWeight: 600, display: 'block', marginBottom: 3 }}>Max Date</label>
            <input type="date" value={filterMaxDate} onChange={e => setFilterMaxDate(e.target.value)} style={inputStyle} />
          </div>
        </div>
      </div>

      <ConfigPairForm
        providerModels={providerModels}
        aProvider={aProvider} aModel={aModel}
        bProvider={bProvider} bModel={bModel}
        setAProvider={setAProvider} setAModel={setAModel}
        setBProvider={setBProvider} setBModel={setBModel}
        inputStyle={inputStyle}
      />

      <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
        <button className="action-btn" onClick={onCancel}>Cancel</button>
        <button
          className="action-btn primary"
          onClick={() => onSubmit({
            schema_id: schemaId,
            config_a_provider: aProvider, config_a_model: aModel,
            config_b_provider: bProvider, config_b_model: bModel,
            article_count: articleCount, article_filters: buildFilters(),
          })}
          disabled={!canSubmit}
        >
          Run Calibration
        </button>
      </div>
    </div>
  );
}

/** Shared Config A/B pair UI */
function ConfigPairForm({ providerModels, aProvider, aModel, bProvider, bModel, setAProvider, setAModel, setBProvider, setBModel, inputStyle }: {
  providerModels: ProviderModel[];
  aProvider: string; aModel: string;
  bProvider: string; bModel: string;
  setAProvider: (v: string) => void; setAModel: (v: string) => void;
  setBProvider: (v: string) => void; setBModel: (v: string) => void;
  inputStyle: Record<string, any>;
}) {
  const aModels = aProvider ? providerModels.find(p => p.provider === aProvider)?.models || [] : [];
  const bModels = bProvider ? providerModels.find(p => p.provider === bProvider)?.models || [] : [];

  return (
    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
      <div style={{ padding: 12, border: '1px solid var(--border-color)', borderRadius: 8 }}>
        <div style={{ fontSize: 12, fontWeight: 700, marginBottom: 8, color: 'var(--text-primary)' }}>Config A</div>
        <div style={{ marginBottom: 8 }}>
          <label style={{ fontSize: 11, fontWeight: 600, display: 'block', marginBottom: 3 }}>Provider *</label>
          <select value={aProvider} onChange={e => { setAProvider(e.target.value); setAModel(''); }} style={inputStyle as any}>
            <option value="">Select...</option>
            {providerModels.map(p => <option key={p.provider} value={p.provider}>{p.provider}</option>)}
          </select>
        </div>
        <div>
          <label style={{ fontSize: 11, fontWeight: 600, display: 'block', marginBottom: 3 }}>Model *</label>
          {aProvider ? (
            <select value={aModel} onChange={e => setAModel(e.target.value)} style={inputStyle as any}>
              <option value="">Select...</option>
              {aModels.map(m => <option key={m} value={m}>{m}</option>)}
            </select>
          ) : (
            <input value={aModel} onChange={e => setAModel(e.target.value)} placeholder="Select provider first" style={inputStyle} />
          )}
        </div>
      </div>

      <div style={{ padding: 12, border: '1px solid var(--border-color)', borderRadius: 8 }}>
        <div style={{ fontSize: 12, fontWeight: 700, marginBottom: 8, color: 'var(--text-primary)' }}>Config B</div>
        <div style={{ marginBottom: 8 }}>
          <label style={{ fontSize: 11, fontWeight: 600, display: 'block', marginBottom: 3 }}>Provider *</label>
          <select value={bProvider} onChange={e => { setBProvider(e.target.value); setBModel(''); }} style={inputStyle as any}>
            <option value="">Select...</option>
            {providerModels.map(p => <option key={p.provider} value={p.provider}>{p.provider}</option>)}
          </select>
        </div>
        <div>
          <label style={{ fontSize: 11, fontWeight: 600, display: 'block', marginBottom: 3 }}>Model *</label>
          {bProvider ? (
            <select value={bModel} onChange={e => setBModel(e.target.value)} style={inputStyle as any}>
              <option value="">Select...</option>
              {bModels.map(m => <option key={m} value={m}>{m}</option>)}
            </select>
          ) : (
            <input value={bModel} onChange={e => setBModel(e.target.value)} placeholder="Select provider first" style={inputStyle} />
          )}
        </div>
      </div>
    </div>
  );
}

function CalibrationReviewModal({ article, comparison, onSave, onCancel }: {
  article: CalibrationArticle;
  comparison: Comparison;
  onSave: (chosenConfig: string | null, goldenExtraction: Record<string, any> | null, notes: string | null) => void;
  onCancel: () => void;
}) {
  const [chosenConfig, setChosenConfig] = useState<string | null>(article.chosen_config);
  const [goldenJson, setGoldenJson] = useState(() => {
    if (article.golden_extraction) return JSON.stringify(article.golden_extraction, null, 2);
    if (article.chosen_config === 'A' && article.config_a_extraction) return JSON.stringify(article.config_a_extraction, null, 2);
    if (article.chosen_config === 'B' && article.config_b_extraction) return JSON.stringify(article.config_b_extraction, null, 2);
    return '';
  });
  const [notes, setNotes] = useState(article.reviewer_notes || '');
  const [editing, setEditing] = useState(false);
  const [jsonError, setJsonError] = useState<string | null>(null);
  const isPipeline = (comparison.comparison_type || 'schema') === 'pipeline';

  const chooseConfig = (config: string) => {
    setChosenConfig(config);
    const extraction = config === 'A' ? article.config_a_extraction : article.config_b_extraction;
    if (extraction) {
      setGoldenJson(JSON.stringify(extraction, null, 2));
    }
  };

  const handleSave = () => {
    if (!goldenJson.trim()) {
      onSave(chosenConfig, null, notes || null);
      return;
    }
    try {
      const parsed = JSON.parse(goldenJson);
      setJsonError(null);
      onSave(chosenConfig, parsed, notes || null);
    } catch {
      setJsonError('Invalid JSON');
    }
  };

  const inputStyle = { width: '100%', padding: '8px 10px', borderRadius: 6, border: '1px solid var(--border-color)', fontSize: 13, background: 'var(--bg-primary)' };

  const parseJsonbField = (val: unknown): any => {
    if (val == null) return null;
    if (typeof val === 'string') { try { return JSON.parse(val); } catch { return val; } }
    return val;
  };
  const stage1A = parseJsonbField(article.config_a_stage1);
  const stage1B = parseJsonbField(article.config_b_stage1);
  const stage2A = parseJsonbField(article.config_a_stage2_results) || [];
  const stage2B = parseJsonbField(article.config_b_stage2_results) || [];

  const configALabel = `${comparison.config_a_provider}/${comparison.config_a_model.split('/').pop()}`;
  const configBLabel = `${comparison.config_b_provider}/${comparison.config_b_model.split('/').pop()}`;

  return (
    <div className="modal-overlay" onClick={onCancel}>
      <div className="modal-content" onClick={e => e.stopPropagation()} style={{ maxWidth: 1100 }}>
        <h3>Review Article</h3>

        {/* Article info */}
        <div style={{ marginBottom: 16 }}>
          <div style={{ fontWeight: 600, fontSize: 14, marginBottom: 4 }}>
            {article.article_title || 'Untitled'}
          </div>
          {article.article_source_url && (
            <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 4 }}>
              {article.article_source_url}
            </div>
          )}
          <div style={{
            maxHeight: 120, overflow: 'auto', fontSize: 12, color: 'var(--text-secondary)',
            padding: 8, background: 'var(--bg-secondary)', borderRadius: 6,
          }}>
            {(article.article_content || '').substring(0, 500)}
            {(article.article_content || '').length > 500 && '...'}
          </div>
        </div>

        {/* Pipeline: Stage 1 IR Comparison */}
        {isPipeline && <Stage1SummaryBar stage1A={stage1A} stage1B={stage1B} />}

        {/* Pipeline: Stage 2 Results */}
        {isPipeline && <Stage2ComparisonGrid stage2A={stage2A} stage2B={stage2B} />}

        {/* Best extraction diff */}
        <BestExtractionDiff
          configALabel={configALabel}
          configBLabel={configBLabel}
          extractionA={article.config_a_extraction}
          extractionB={article.config_b_extraction}
          confidenceA={article.config_a_confidence}
          confidenceB={article.config_b_confidence}
          errorA={article.config_a_error}
          errorB={article.config_b_error}
          chosenConfig={chosenConfig}
          onChoose={chooseConfig}
        />

        {/* Golden extraction */}
        <GoldenExtractionView
          goldenJson={goldenJson}
          editing={editing}
          onToggleEdit={() => setEditing(v => !v)}
          onJsonChange={v => { setGoldenJson(v); setJsonError(null); }}
          jsonError={jsonError}
        />

        {/* Notes */}
        <div style={{ marginBottom: 16 }}>
          <label style={{ fontSize: 12, fontWeight: 600, display: 'block', marginBottom: 4 }}>Notes</label>
          <input value={notes} onChange={e => setNotes(e.target.value)} style={inputStyle} placeholder="Optional reviewer notes" />
        </div>

        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
          <button className="action-btn" onClick={onCancel}>Cancel</button>
          <button className="action-btn primary" onClick={handleSave}>Save Review</button>
        </div>
      </div>
    </div>
  );
}

function SaveDatasetModal({ reviewedCount, onSave, onCancel }: {
  reviewedCount: number;
  onSave: (name: string, description: string) => void;
  onCancel: () => void;
}) {
  const [name, setName] = useState('');
  const [desc, setDesc] = useState('');
  const inputStyle = { width: '100%', padding: '8px 10px', borderRadius: 6, border: '1px solid var(--border-color)', fontSize: 13, background: 'var(--bg-primary)' };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <p style={{ fontSize: 13, color: 'var(--text-secondary)', margin: 0 }}>
        This will create a golden dataset from {reviewedCount} reviewed article{reviewedCount !== 1 ? 's' : ''}.
        Each reviewed article with a golden extraction becomes a test case.
      </p>
      <div>
        <label style={{ fontSize: 12, fontWeight: 600, display: 'block', marginBottom: 4 }}>Dataset Name *</label>
        <input value={name} onChange={e => setName(e.target.value)} style={inputStyle} placeholder="e.g., Calibration Dataset v1" />
      </div>
      <div>
        <label style={{ fontSize: 12, fontWeight: 600, display: 'block', marginBottom: 4 }}>Description</label>
        <textarea value={desc} onChange={e => setDesc(e.target.value)} rows={3} style={{ ...inputStyle, resize: 'vertical' }} />
      </div>
      <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
        <button className="action-btn" onClick={onCancel}>Cancel</button>
        <button className="action-btn primary" onClick={() => onSave(name, desc)} disabled={!name}>Save Dataset</button>
      </div>
    </div>
  );
}

export default PromptTestRunner;
