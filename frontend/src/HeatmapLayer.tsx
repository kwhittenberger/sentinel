import { useEffect, useRef, useState, Component, type ReactNode } from 'react';
import { useMap, useMapEvents } from 'react-leaflet';
import L from 'leaflet';

interface HeatmapLayerProps {
  points: [number, number, number][]; // [lat, lon, intensity]
  onMapClick?: (lat: number, lon: number) => void;
  options?: {
    radius?: number;
    blur?: number;
    maxZoom?: number;
    max?: number;
    minOpacity?: number;
    gradient?: Record<number, string>;
  };
}

// Track if leaflet.heat has been loaded
let heatPluginLoaded = false;
let heatPluginLoading: Promise<boolean> | null = null;

async function loadHeatPlugin(): Promise<boolean> {
  if (heatPluginLoaded) return true;
  if (heatPluginLoading) return heatPluginLoading;

  heatPluginLoading = new Promise<boolean>((resolve) => {
    // Make L available globally BEFORE loading leaflet.heat
    (window as any).L = L;

    // Load leaflet.heat via script tag to ensure it runs in global context
    const script = document.createElement('script');
    script.src = '/leaflet-heat.js';
    script.async = true;

    script.onload = () => {
      const windowL = (window as any).L;

      if (typeof windowL?.heatLayer === 'function') {
        heatPluginLoaded = true;
        resolve(true);
      } else {
        console.error('leaflet.heat did not attach to window.L');
        resolve(false);
      }
    };

    script.onerror = (e) => {
      console.error('Failed to load leaflet.heat from CDN', e);
      resolve(false);
    };

    document.head.appendChild(script);
  });

  return heatPluginLoading;
}

// Error boundary to catch rendering errors
interface ErrorBoundaryState {
  hasError: boolean;
}

class HeatmapErrorBoundary extends Component<{ children: ReactNode }, ErrorBoundaryState> {
  constructor(props: { children: ReactNode }) {
    super(props);
    this.state = { hasError: false };
  }

  static getDerivedStateFromError(): ErrorBoundaryState {
    return { hasError: true };
  }

  componentDidCatch(error: Error) {
    console.error('HeatmapLayer error:', error);
  }

  render() {
    if (this.state.hasError) {
      return null;
    }
    return this.props.children;
  }
}

// Component to handle map click events
function MapClickHandler({ onMapClick }: { onMapClick?: (lat: number, lon: number) => void }) {
  useMapEvents({
    click: (e) => {
      if (onMapClick) {
        onMapClick(e.latlng.lat, e.latlng.lng);
      }
    },
  });
  return null;
}

function HeatmapLayerInner({ points, onMapClick, options = {} }: HeatmapLayerProps) {
  const map = useMap();
  const heatLayerRef = useRef<L.Layer | null>(null);
  const [isReady, setIsReady] = useState(heatPluginLoaded);
  const [loadFailed, setLoadFailed] = useState(false);

  // Load the heat plugin
  useEffect(() => {
    let mounted = true;

    if (!isReady && !loadFailed) {
      loadHeatPlugin().then(success => {
        if (mounted) {
          if (success) {
            setIsReady(true);
          } else {
            setLoadFailed(true);
          }
        }
      });
    }

    return () => { mounted = false; };
  }, [isReady, loadFailed]);

  // Create/update the heat layer
  useEffect(() => {
    if (!isReady || loadFailed) return;

    // Clean up previous layer
    if (heatLayerRef.current) {
      map.removeLayer(heatLayerRef.current);
      heatLayerRef.current = null;
    }

    if (points.length === 0) {
      return;
    }

    try {
      // Use window.L.heatLayer since that's where the CDN script attaches it
      const windowL = (window as any).L;
      const heatLayer = windowL.heatLayer(points, {
        radius: options.radius ?? 25,
        blur: options.blur ?? 15,
        maxZoom: options.maxZoom ?? 17,
        max: options.max ?? 1.0,
        minOpacity: options.minOpacity ?? 0.4,
        gradient: options.gradient ?? {
          0.0: '#3b82f6',
          0.3: '#10b981',
          0.5: '#f59e0b',
          0.7: '#f97316',
          1.0: '#dc2626',
        },
      });

      heatLayer.addTo(map);
      heatLayerRef.current = heatLayer;
    } catch (err) {
      console.error('Failed to create heat layer:', err);
      setLoadFailed(true);
    }

    return () => {
      if (heatLayerRef.current) {
        map.removeLayer(heatLayerRef.current);
        heatLayerRef.current = null;
      }
    };
  }, [map, points, isReady, loadFailed, options.radius, options.blur, options.maxZoom, options.max, options.minOpacity, options.gradient]);

  return <MapClickHandler onMapClick={onMapClick} />;
}

export function HeatmapLayer(props: HeatmapLayerProps) {
  return (
    <HeatmapErrorBoundary>
      <HeatmapLayerInner {...props} />
    </HeatmapErrorBoundary>
  );
}
