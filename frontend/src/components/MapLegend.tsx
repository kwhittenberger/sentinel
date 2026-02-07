export function MapLegend() {
  return (
    <div className="legend">
      <span className="legend-item">
        <span className="legend-dot death"></span> Death
      </span>
      <span className="legend-item">
        <span className="legend-dot non-immigrant"></span> Non-immigrant
      </span>
      <span className="legend-item">
        <span className="legend-dot other"></span> Other
      </span>
      <span className="keyboard-hint" title="j/k or arrows: navigate | h: heatmap | d: dark mode | m/c/s: views | Esc: clear">
        Keyboard: j/k h d m c s Esc
      </span>
    </div>
  );
}
