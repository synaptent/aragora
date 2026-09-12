'use client';

interface ChartDataItem {
  name: string;
  cost: number;
  percentage: number;
}

interface CostBreakdownChartProps {
  title: string;
  data: ChartDataItem[];
  colors: string[];
}

export function CostBreakdownChart({ title, data, colors }: CostBreakdownChartProps) {
  const maxCost = Math.max(...data.map((d) => d.cost));

  return (
    <div className="bg-[var(--surface)] border border-[var(--border)] rounded p-4">
      <h3 className="text-sm font-theme-data text-[var(--acid-green)] mb-4">
        {'>'} {title.toUpperCase()}
      </h3>

      {/* Donut Chart Visualization */}
      <div className="flex items-center gap-6">
        {/* Simple CSS Donut */}
        <div className="relative w-32 h-32 flex-shrink-0">
          <DonutChart data={data} colors={colors} />
          <div className="absolute inset-0 flex items-center justify-center">
            <div className="text-center">
              <div className="text-lg font-theme-data text-[var(--text)]">
                ${data.reduce((sum, d) => sum + d.cost, 0).toFixed(0)}
              </div>
              <div className="text-xs text-[var(--text-muted)]">Total</div>
            </div>
          </div>
        </div>

        {/* Legend */}
        <div className="flex-1 space-y-2">
          {data.map((item, index) => (
            <div key={item.name} className="flex items-center gap-2">
              <div
                className="w-3 h-3 rounded-full flex-shrink-0"
                style={{ backgroundColor: colors[index % colors.length] }}
              />
              <div className="flex-1 min-w-0">
                <div className="flex items-center justify-between">
                  <span className="text-sm text-[var(--text)] truncate">{item.name}</span>
                  <span className="text-sm font-theme-data text-[var(--text-muted)]">
                    ${item.cost.toFixed(2)}
                  </span>
                </div>
                <div className="text-xs text-[var(--text-muted)]">
                  {item.percentage.toFixed(1)}%
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Bar Chart Alternative */}
      <div className="mt-4 pt-4 border-t border-[var(--border)]">
        <div className="space-y-2">
          {data.map((item, index) => (
            <div key={item.name}>
              <div className="flex items-center justify-between text-xs mb-1">
                <span className="text-[var(--text-muted)]">{item.name}</span>
                <span className="font-theme-data" style={{ color: colors[index % colors.length] }}>
                  {item.percentage.toFixed(1)}%
                </span>
              </div>
              <div className="h-2 bg-[var(--bg)] rounded-full overflow-hidden">
                <div
                  className="h-full transition-all duration-500"
                  style={{
                    width: `${(item.cost / maxCost) * 100}%`,
                    backgroundColor: colors[index % colors.length],
                  }}
                />
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

interface DonutChartProps {
  data: ChartDataItem[];
  colors: string[];
}

function DonutChart({ data, colors }: DonutChartProps) {
  // Calculate total
  const total = data.reduce((sum, d) => sum + d.cost, 0);
  if (total === 0) return null;

  // Calculate segments
  let cumulativePercent = 0;
  const segments = data.map((item, index) => {
    const percent = (item.cost / total) * 100;
    const startAngle = cumulativePercent * 3.6; // Convert to degrees (100% = 360deg)
    const endAngle = (cumulativePercent + percent) * 3.6;
    cumulativePercent += percent;

    return { ...item, color: colors[index % colors.length], startAngle, endAngle, percent };
  });

  // Create conic gradient
  let gradientStops = '';
  let currentAngle = 0;

  segments.forEach((segment) => {
    gradientStops += `${segment.color} ${currentAngle}deg ${currentAngle + segment.percent * 3.6}deg, `;
    currentAngle += segment.percent * 3.6;
  });

  // Remove trailing comma and space
  gradientStops = gradientStops.slice(0, -2);

  return (
    <div
      className="w-full h-full rounded-full"
      style={{
        background: `conic-gradient(${gradientStops})`,
        mask: 'radial-gradient(farthest-side, transparent calc(100% - 16px), black calc(100% - 15px))',
        WebkitMask:
          'radial-gradient(farthest-side, transparent calc(100% - 16px), black calc(100% - 15px))',
      }}
    />
  );
}

export default CostBreakdownChart;
