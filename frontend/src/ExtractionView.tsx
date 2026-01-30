import { useState } from 'react';
import { ExtractionSchemaManager } from './ExtractionSchemaManager';
import { TwoStageExtractionView } from './TwoStageExtractionView';
import { DatasetsTab, PipelineTestingTab } from './PromptTestRunner';

type ExtractionTab = 'schemas' | 'pipeline' | 'datasets' | 'testing';

export function ExtractionView() {
  const [tab, setTab] = useState<ExtractionTab>('schemas');

  return (
    <div className="admin-page">
      <div className="page-header">
        <h2>Extraction</h2>
      </div>
      <div className="detail-tabs">
        <button
          className={`tab ${tab === 'schemas' ? 'active' : ''}`}
          onClick={() => setTab('schemas')}
        >
          Schemas
        </button>
        <button
          className={`tab ${tab === 'pipeline' ? 'active' : ''}`}
          onClick={() => setTab('pipeline')}
        >
          Pipeline Explorer
        </button>
        <button
          className={`tab ${tab === 'datasets' ? 'active' : ''}`}
          onClick={() => setTab('datasets')}
        >
          Datasets
        </button>
        <button
          className={`tab ${tab === 'testing' ? 'active' : ''}`}
          onClick={() => setTab('testing')}
        >
          Pipeline Testing
        </button>
      </div>
      {tab === 'schemas' && <ExtractionSchemaManager />}
      {tab === 'pipeline' && <TwoStageExtractionView />}
      {tab === 'datasets' && <DatasetsTab />}
      {tab === 'testing' && <PipelineTestingTab />}
    </div>
  );
}

export default ExtractionView;
