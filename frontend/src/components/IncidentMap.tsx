import { useEffect } from 'react';
import { MapContainer, TileLayer, CircleMarker, Tooltip, useMap } from 'react-leaflet';
import MarkerClusterGroup from 'react-leaflet-cluster';
import { HeatmapLayer } from '../HeatmapLayer';
import type { Incident } from '../types';

// Map center changer component - only updates when center/zoom actually change
function ChangeView({ center, zoom }: { center: [number, number]; zoom: number }) {
  const map = useMap();
  useEffect(() => {
    map.setView(center, zoom);
  }, [map, center[0], center[1], zoom]);
  return null;
}

// Add small offset to prevent markers at same coords from overlapping
// Uses incident ID to generate consistent offset
function getJitteredCoords(lat: number, lon: number, id: string): [number, number] {
  let hash = 0;
  for (let i = 0; i < id.length; i++) {
    hash = ((hash << 5) - hash) + id.charCodeAt(i);
    hash = hash & hash;
  }
  const latOffset = ((hash % 100) - 50) * 0.00004;
  const lonOffset = (((hash >> 8) % 100) - 50) * 0.00004;
  return [lat + latOffset, lon + lonOffset];
}

function getMarkerColor(incident: Incident): string {
  if (incident.is_death) return '#dc2626'; // red
  if (incident.is_non_immigrant) return '#f97316'; // orange
  return '#3b82f6'; // blue
}

interface IncidentMapProps {
  incidents: Incident[];
  selectedIncident: Incident | null;
  mapCenter: [number, number];
  mapZoom: number;
  mapStyle: 'street' | 'satellite';
  showHeatmap: boolean;
  loading: boolean;
  onMarkerClick: (incident: Incident) => void;
  onHeatmapClick: (lat: number, lon: number) => void;
  getTypeDisplayName: (name: string | undefined) => string;
  getStateDisplayName: (incident: Incident) => string;
  formatDate: (dateStr: string) => string;
}

export function IncidentMap({
  incidents,
  mapCenter,
  mapZoom,
  mapStyle,
  showHeatmap,
  loading,
  onMarkerClick,
  onHeatmapClick,
  getTypeDisplayName,
  getStateDisplayName,
  formatDate,
}: IncidentMapProps) {
  return (
    <div className="map-container">
      {loading && <div className="loading-overlay">Loading...</div>}
      <MapContainer center={mapCenter} zoom={mapZoom} maxZoom={20} style={{ height: '100%', width: '100%' }}>
        <ChangeView center={mapCenter} zoom={mapZoom} />
        {mapStyle === 'street' ? (
          <TileLayer
            attribution='&copy; <a href="https://carto.com/">CARTO</a>'
            url="https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png"
            maxZoom={20}
          />
        ) : (
          <TileLayer
            attribution='&copy; Google'
            url="https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}"
            maxZoom={20}
          />
        )}
        {showHeatmap ? (
          <HeatmapLayer
            points={incidents
              .filter((inc) => inc.lat && inc.lon)
              .map((inc) => [inc.lat!, inc.lon!, inc.is_death ? 1.0 : 0.5] as [number, number, number])}
            onMapClick={onHeatmapClick}
          />
        ) : (
          <MarkerClusterGroup
            chunkedLoading
            maxClusterRadius={40}
            spiderfyOnMaxZoom={true}
            showCoverageOnHover={false}
          >
            {incidents
              .filter((inc) => inc.lat && inc.lon)
              .map((incident) => (
                <CircleMarker
                  key={incident.id}
                  center={getJitteredCoords(incident.lat!, incident.lon!, incident.id)}
                  radius={8}
                  pathOptions={{
                    color: getMarkerColor(incident),
                    fillColor: getMarkerColor(incident),
                    fillOpacity: 0.7,
                  }}
                  eventHandlers={{
                    click: () => onMarkerClick(incident),
                  }}
                >
                  <Tooltip>
                    <strong>{incident.city}, {getStateDisplayName(incident)}</strong>
                    {incident.victim_name && (
                      <>
                        <br />
                        <em>{incident.victim_name}</em>
                      </>
                    )}
                    <br />
                    {getTypeDisplayName(incident.incident_type)}
                    <br />
                    {formatDate(incident.date)}
                  </Tooltip>
                </CircleMarker>
              ))}
          </MarkerClusterGroup>
        )}
      </MapContainer>
    </div>
  );
}

export { getJitteredCoords, getMarkerColor };
