import type { Incident } from './types';

/** Map of state names to their geographic center coordinates and default zoom level */
export const STATE_CENTERS: Record<string, { center: [number, number]; zoom: number }> = {
  'All States': { center: [39.8283, -98.5795], zoom: 4 },
  'California': { center: [36.7783, -119.4179], zoom: 6 },
  'Texas': { center: [31.9686, -99.9018], zoom: 6 },
  'Florida': { center: [27.6648, -81.5158], zoom: 6 },
  'Illinois': { center: [40.6331, -89.3985], zoom: 6 },
  'Minnesota': { center: [46.7296, -94.6859], zoom: 6 },
  'New York': { center: [43.2994, -74.2179], zoom: 6 },
  'Georgia': { center: [32.1656, -82.9001], zoom: 6 },
  'Arizona': { center: [34.0489, -111.0937], zoom: 6 },
};

/** Returns a marker color based on incident severity flags */
export function getMarkerColor(incident: Incident): string {
  if (incident.is_death) return '#dc2626'; // red
  if (incident.is_non_immigrant) return '#f97316'; // orange
  return '#3b82f6'; // blue
}

/** Formats an ISO datetime string to just the date portion (YYYY-MM-DD) */
export function formatDate(dateStr: string): string {
  if (!dateStr) return 'Unknown';
  return dateStr.split('T')[0];
}

/**
 * Adds a small deterministic offset to coordinates to prevent markers at the
 * same location from overlapping. Uses incident ID to generate a consistent
 * pseudo-random offset (~20-50 meters).
 */
export function getJitteredCoords(lat: number, lon: number, id: string): [number, number] {
  let hash = 0;
  for (let i = 0; i < id.length; i++) {
    hash = ((hash << 5) - hash) + id.charCodeAt(i);
    hash = hash & hash;
  }
  const latOffset = ((hash % 100) - 50) * 0.00004;
  const lonOffset = (((hash >> 8) % 100) - 50) * 0.00004;
  return [lat + latOffset, lon + lonOffset];
}

/** Exports a list of incidents to a downloadable CSV file */
export function exportToCSV(
  incidents: Incident[],
  getStateDisplayName: (incident: Incident) => string,
  getTypeDisplayName: (typeName: string | undefined) => string,
): void {
  const headers = ['ID', 'Date', 'State', 'City', 'Type', 'Victim Name', 'Category', 'Outcome', 'Tier', 'Death', 'Non-Immigrant', 'Notes', 'Source URL'];
  const rows = incidents.map(i => [
    i.id,
    i.date || '',
    getStateDisplayName(i),
    i.city || '',
    getTypeDisplayName(i.incident_type),
    i.victim_name || '',
    i.victim_category || '',
    i.outcome_category || '',
    i.tier,
    i.is_death ? 'Yes' : 'No',
    i.is_non_immigrant ? 'Yes' : 'No',
    (i.notes || '').replace(/"/g, '""'),
    i.source_url || ''
  ]);

  const csvContent = [
    headers.join(','),
    ...rows.map(row => row.map(cell => `"${cell}"`).join(','))
  ].join('\n');

  const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
  const link = document.createElement('a');
  link.href = URL.createObjectURL(blob);
  link.download = `sentinel_incidents_${new Date().toISOString().split('T')[0]}.csv`;
  link.click();
}

/** Copies the current page URL to the clipboard and shows a confirmation alert */
export function copyShareLink(): void {
  navigator.clipboard.writeText(window.location.href).then(() => {
    alert('Link copied to clipboard!');
  });
}
