import type { Incident } from '../types';

interface StreetViewPanelProps {
  incident: Incident;
}

export function StreetViewPanel({ incident }: StreetViewPanelProps) {
  const { lat, lon, city } = incident;
  const stateName = incident.state_name || incident.state || 'Unknown';

  return (
    <div className="street-view-container">
      <div className="street-view-info">
        <span>{city}, {stateName}</span>
        <a
          href={`https://www.google.com/maps/@?api=1&map_action=pano&viewpoint=${lat},${lon}`}
          target="_blank"
          rel="noopener noreferrer"
        >
          Open in Google Maps
        </a>
      </div>
      <iframe
        className="street-view-iframe"
        src={`https://maps.google.com/maps?q=&layer=c&cbll=${lat},${lon}&cbp=11,0,0,0,0&output=svembed`}
        allowFullScreen
        loading="lazy"
      />
    </div>
  );
}
