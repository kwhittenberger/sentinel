import { useEffect } from 'react';
import type { Incident } from '../types';

export interface KeyboardNavigationDeps {
  incidents: Incident[];
  selectedIncident: Incident | null;
  setSelectedIncident: React.Dispatch<React.SetStateAction<Incident | null>>;
  setCustomView: React.Dispatch<React.SetStateAction<{ center: [number, number]; zoom: number } | null>>;
  setShowHeatmap: React.Dispatch<React.SetStateAction<boolean>>;
  setDarkMode: React.Dispatch<React.SetStateAction<boolean>>;
  setViewTab: React.Dispatch<React.SetStateAction<'map' | 'streetview' | 'charts'>>;
  zoomToIncident: (incident: Incident) => void;
}

export function useKeyboardNavigation({
  incidents,
  selectedIncident,
  setSelectedIncident,
  setCustomView,
  setShowHeatmap,
  setDarkMode,
  setViewTab,
  zoomToIncident,
}: KeyboardNavigationDeps): void {
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      // Ignore if typing in an input
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLSelectElement) {
        return;
      }

      const incidentsWithCoords = incidents.filter(i => i.lat && i.lon);
      const currentIndex = selectedIncident
        ? incidentsWithCoords.findIndex(i => i.id === selectedIncident.id)
        : -1;

      switch (e.key) {
        case 'ArrowDown':
        case 'j':
          e.preventDefault();
          if (incidentsWithCoords.length > 0) {
            const nextIndex = currentIndex < incidentsWithCoords.length - 1 ? currentIndex + 1 : 0;
            const nextIncident = incidentsWithCoords[nextIndex];
            setSelectedIncident(nextIncident);
            zoomToIncident(nextIncident);
          }
          break;
        case 'ArrowUp':
        case 'k':
          e.preventDefault();
          if (incidentsWithCoords.length > 0) {
            const prevIndex = currentIndex > 0 ? currentIndex - 1 : incidentsWithCoords.length - 1;
            const prevIncident = incidentsWithCoords[prevIndex];
            setSelectedIncident(prevIncident);
            zoomToIncident(prevIncident);
          }
          break;
        case 'Escape':
          setSelectedIncident(null);
          setCustomView(null);
          break;
        case 'h':
          if (!e.ctrlKey && !e.metaKey) {
            setShowHeatmap(prev => !prev);
          }
          break;
        case 'd':
          if (!e.ctrlKey && !e.metaKey) {
            setDarkMode(prev => !prev);
          }
          break;
        case 'm':
          setViewTab('map');
          break;
        case 'c':
          if (!e.ctrlKey && !e.metaKey) {
            setViewTab('charts');
          }
          break;
        case 's':
          if (!e.ctrlKey && !e.metaKey && selectedIncident?.lat && selectedIncident?.lon) {
            setViewTab('streetview');
          }
          break;
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [incidents, selectedIncident, setSelectedIncident, setCustomView, setShowHeatmap, setDarkMode, setViewTab, zoomToIncident]);
}
