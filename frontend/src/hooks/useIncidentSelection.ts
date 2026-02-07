import { useState, useEffect } from 'react';
import type { Incident, IncidentConnections, UniversalExtractionData } from '../types';
import { fetchIncidentConnections } from '../api';

export interface IncidentSelectionReturn {
  selectedIncident: Incident | null;
  setSelectedIncident: React.Dispatch<React.SetStateAction<Incident | null>>;
  drawerOpen: boolean;
  setDrawerOpen: React.Dispatch<React.SetStateAction<boolean>>;
  fullIncident: Incident | null;
  articleContent: string | null;
  extractionData: UniversalExtractionData | null;
  sourceUrl: string | null;
  connections: IncidentConnections | null;
  connectionsLoading: boolean;
}

export function useIncidentSelection(): IncidentSelectionReturn {
  const [selectedIncident, setSelectedIncident] = useState<Incident | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [fullIncident, setFullIncident] = useState<Incident | null>(null);
  const [articleContent, setArticleContent] = useState<string | null>(null);
  const [extractionData, setExtractionData] = useState<UniversalExtractionData | null>(null);
  const [sourceUrl, setSourceUrl] = useState<string | null>(null);
  const [connections, setConnections] = useState<IncidentConnections | null>(null);
  const [connectionsLoading, setConnectionsLoading] = useState(false);

  // Open drawer when incident selected, close when cleared
  useEffect(() => {
    if (selectedIncident) {
      setDrawerOpen(true);
      // Fetch full incident detail from admin API
      setFullIncident(null);
      setArticleContent(null);
      setExtractionData(null);
      setSourceUrl(null);
      fetch(`/api/admin/incidents/${selectedIncident.id}`)
        .then(res => res.ok ? res.json() : null)
        .then(data => { if (data) setFullIncident(data as Incident); })
        .catch(() => {});
      // Fetch linked articles for content + extraction data
      fetch(`/api/admin/incidents/${selectedIncident.id}/articles`)
        .then(res => res.ok ? res.json() : null)
        .then(data => {
          if (data?.articles?.length > 0) {
            const article = data.articles.find((a: Record<string, unknown>) => a.is_primary) || data.articles[0];
            if (article?.content) setArticleContent(article.content as string);
            if (article?.source_url) setSourceUrl(article.source_url as string);
            // Use extracted_data for the rich ExtractionDetailView
            if (article?.extracted_data && typeof article.extracted_data === 'object') {
              setExtractionData(article.extracted_data as UniversalExtractionData);
            }
          }
        })
        .catch(() => {});
    } else {
      setDrawerOpen(false);
      setFullIncident(null);
      setArticleContent(null);
      setExtractionData(null);
      setSourceUrl(null);
      setConnections(null);
    }
  }, [selectedIncident]);

  // Fetch connections when drawer is open with an incident
  useEffect(() => {
    if (drawerOpen && selectedIncident?.id) {
      setConnectionsLoading(true);
      fetchIncidentConnections(selectedIncident.id)
        .then(setConnections)
        .catch(() => setConnections(null))
        .finally(() => setConnectionsLoading(false));
    }
  }, [drawerOpen, selectedIncident?.id]);

  return {
    selectedIncident,
    setSelectedIncident,
    drawerOpen,
    setDrawerOpen,
    fullIncident,
    articleContent,
    extractionData,
    sourceUrl,
    connections,
    connectionsLoading,
  };
}
