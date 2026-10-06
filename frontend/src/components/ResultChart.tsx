import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { ChartSpec, ResultTableData } from "../types/api";
import { formatNumber } from "./format";

const CHART_COLORS = ["#2563eb", "#0d9488", "#f59e0b", "#8b5cf6", "#e11d48", "#64748b"];

const AXIS = { fontSize: 11, fill: "#6b7280" };
const compact = new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 });
const ISO_DATE = /^(\d{4})-(\d{2})-(\d{2})$/;

const formatValue = (value: unknown) => (typeof value === "number" ? formatNumber(value) : String(value ?? ""));
const formatAxisValue = (value: unknown) => (typeof value === "number" ? compact.format(value) : String(value ?? ""));

function formatCategory(value: unknown): string {
  const match = typeof value === "string" ? ISO_DATE.exec(value) : null;
  if (!match) return String(value ?? "");
  const date = new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]));
  return date.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

const tooltipStyle = {
  contentStyle: {
    borderRadius: 8,
    border: "1px solid #e5e7eb",
    boxShadow: "0 4px 12px rgba(17, 24, 39, 0.08)",
    fontSize: 12,
  },
  labelStyle: { color: "#111827", fontWeight: 600 },
};

export function ResultChart({ chart, table }: { chart: ChartSpec; table: ResultTableData }) {
  const labelFor = (key: string) => table.columns.find((c) => c.key === key)?.label ?? key;
  const data = table.rows;
  const seriesName = (key: string) => {
    const label = labelFor(key);
    return table.unit && !label.toLowerCase().includes(table.unit.toLowerCase()) ? `${label} (${table.unit})` : label;
  };
  const multi = chart.y.length > 1;
  const common = {
    data,
    margin: { top: 8, right: 8, bottom: 0, left: 0 },
  };
  const axes = (
    <>
      <CartesianGrid vertical={false} stroke="#eef0f3" />
      <XAxis
        dataKey={chart.x}
        tick={AXIS}
        tickLine={false}
        axisLine={{ stroke: "#e5e7eb" }}
        tickFormatter={formatCategory}
        minTickGap={12}
      />
      <YAxis tickFormatter={formatAxisValue} tick={AXIS} tickLine={false} axisLine={false} width={48} />
      <Tooltip formatter={(v) => formatValue(v)} labelFormatter={formatCategory} {...tooltipStyle} />
      {multi ? <Legend iconType="circle" iconSize={8} wrapperStyle={{ fontSize: 12 }} /> : null}
    </>
  );

  return (
    <figure className="result-chart" role="group" aria-label={chart.title || "Usage chart"}>
      <div className="result-chart__head">
        {chart.title ? <figcaption className="result-chart__title">{chart.title}</figcaption> : null}
        {table.unit ? <span className="result-chart__unit">{table.unit}</span> : null}
      </div>
      <div className="result-chart__canvas" aria-hidden="true">
        <ResponsiveContainer width="100%" height={240}>
          {chart.type === "line" ? (
            <LineChart {...common}>
              {axes}
              {chart.y.map((key, i) => (
                <Line
                  key={key}
                  type="monotone"
                  dataKey={key}
                  name={seriesName(key)}
                  stroke={CHART_COLORS[i % CHART_COLORS.length]}
                  strokeWidth={2}
                  dot={false}
                  activeDot={{ r: 4 }}
                  isAnimationActive={false}
                />
              ))}
            </LineChart>
          ) : (
            <BarChart {...common} barCategoryGap="20%">
              {axes}
              {chart.y.map((key, i) => (
                <Bar
                  key={key}
                  dataKey={key}
                  name={seriesName(key)}
                  fill={CHART_COLORS[i % CHART_COLORS.length]}
                  radius={[4, 4, 0, 0]}
                  maxBarSize={36}
                  isAnimationActive={false}
                />
              ))}
            </BarChart>
          )}
        </ResponsiveContainer>
      </div>
    </figure>
  );
}
