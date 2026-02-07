import { useState, useCallback } from 'react';
import { OperationsBar } from './OperationsBar';
import { BatchProcessing } from './BatchProcessing';
import { DataSourcesPanel } from './DataSourcesPanel';
import { EnrichmentPanel } from './EnrichmentPanel';
import { ExtractionSchemaManager } from './ExtractionSchemaManager';
import { TwoStageExtractionView } from './TwoStageExtractionView';
import { DatasetsTab, PipelineTestingTab } from './PromptTestRunner';

type PipelineTab = 'queue' | 'sources' | 'schemas' | 'testing' | 'explorer' | 'datasets' | 'enrichment';

const TABS: { key: PipelineTab; label: string }[] = [
  { key: 'queue', label: 'Queue' },
  { key: 'sources', label: 'Sources' },
  { key: 'schemas', label: 'Schemas' },
  { key: 'testing', label: 'Testing' },
  { key: 'explorer', label: 'Explorer' },
  { key: 'datasets', label: 'Datasets' },
  { key: 'enrichment', label: 'Enrichment' },
];

interface PipelineViewProps {
  onRefresh?: () => void;
}

export function PipelineView({ onRefresh }: PipelineViewProps) {
  const [activeTab, setActiveTab] = useState<PipelineTab>('queue');
  const [opsExpanded, setOpsExpanded] = useState<boolean>(() => {
    const stored = localStorage.getItem('ops-bar-expanded');
    return stored !== null ? stored === 'true' : true;
  });

  const handleOpsToggle = useCallback(() => {
    setOpsExpanded(prev => {
      const next = !prev;
      localStorage.setItem('ops-bar-expanded', String(next));
      return next;
    });
  }, []);

  const handleOperationComplete = useCallback(() => {
    onRefresh?.();
  }, [onRefresh]);

  return (
    <div className="pipeline-view">
      <OperationsBar
        expanded={opsExpanded}
        onToggle={handleOpsToggle}
        onOperationComplete={handleOperationComplete}
      />

      <div className="pipeline-tabs">
        {TABS.map(tab => (
          <button
            key={tab.key}
            className={`pipeline-tab ${activeTab === tab.key ? 'active' : ''}`}
            onClick={() => setActiveTab(tab.key)}
          >
            {tab.label}
          </button>
        ))}
      </div>

      <div className="pipeline-tab-content">
        {activeTab === 'queue' && <BatchProcessing hideOpsBar onRefresh={onRefresh} />}
        {activeTab === 'sources' && <DataSourcesPanel />}
        {activeTab === 'schemas' && <ExtractionSchemaManager />}
        {activeTab === 'testing' && <PipelineTestingTab />}
        {activeTab === 'explorer' && <TwoStageExtractionView />}
        {activeTab === 'datasets' && <DatasetsTab />}
        {activeTab === 'enrichment' && <EnrichmentPanel />}
      </div>
    </div>
  );
}

export default PipelineView;
