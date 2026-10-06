import { useMemo, useState } from "react";
import type { ResultTableData, TableColumn, TableRow } from "../types/api";
import { formatCell, plural } from "./format";

interface SortState {
  key: string;
  dir: "asc" | "desc";
}

function compare(a: TableRow[string], b: TableRow[string]): number {
  if (a === b) return 0;
  if (a === null || a === undefined) return 1;
  if (b === null || b === undefined) return -1;
  if (typeof a === "number" && typeof b === "number") return a - b;
  return String(a).localeCompare(String(b), undefined, { numeric: true });
}

/** Adds the unit to number headers unless the backend labels already carry it (e.g. "Period A kWh"). */
function unitFor(col: TableColumn, columns: TableColumn[], unit: string): string | null {
  if (col.type !== "number" || !unit) return null;
  const labelled = columns.some((c) => c.label.toLowerCase().includes(unit.toLowerCase()));
  return labelled ? null : unit;
}

export function ResultTable({ table, caption }: { table: ResultTableData; caption?: string }) {
  const [sort, setSort] = useState<SortState | null>(null);
  const [copied, setCopied] = useState(false);

  const rows = useMemo(() => {
    if (!sort) return table.rows;
    const sorted = [...table.rows].sort((r1, r2) => compare(r1[sort.key], r2[sort.key]));
    return sort.dir === "asc" ? sorted : sorted.reverse();
  }, [table.rows, sort]);

  const toggleSort = (key: string) =>
    setSort((s) => (s?.key === key ? { key, dir: s.dir === "asc" ? "desc" : "asc" } : { key, dir: "asc" }));

  const copy = async () => {
    const header = table.columns.map((c) => c.label).join("\t");
    const body = rows.map((r) => table.columns.map((c) => r[c.key] ?? "").join("\t"));
    try {
      await navigator.clipboard.writeText([header, ...body].join("\n"));
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      setCopied(false);
    }
  };

  return (
    <div className="result-table">
      <div className="result-table__toolbar">
        <span className="result-table__title">
          {caption || "Result"}
          <span className="result-table__count"> · {plural(table.rows.length, "row")}</span>
        </span>
        <button type="button" className="btn btn--ghost btn--xs" onClick={() => void copy()}>
          {copied ? "Copied" : "Copy table"}
        </button>
      </div>
      <div className="result-table__scroll" tabIndex={0} role="region" aria-label={`${caption || "Result"} table`}>
        <table>
          {caption ? <caption className="visually-hidden">{caption}</caption> : null}
          <thead>
            <tr>
              {table.columns.map((col) => {
                const active = sort?.key === col.key;
                const ariaSort = active ? (sort.dir === "asc" ? "ascending" : "descending") : "none";
                const unit = unitFor(col, table.columns, table.unit);
                return (
                  <th key={col.key} scope="col" aria-sort={ariaSort} className={col.type === "number" ? "num" : undefined}>
                    <button type="button" className="th-sort" onClick={() => toggleSort(col.key)}>
                      {col.label}
                      {unit ? <span className="th-unit"> ({unit})</span> : null}
                      <span aria-hidden="true" className={`th-sort__icon${active ? " th-sort__icon--active" : ""}`}>
                        {active ? (sort.dir === "asc" ? "▲" : "▼") : "↕"}
                      </span>
                    </button>
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, i) => (
              <tr key={i}>
                {table.columns.map((col) => (
                  <td key={col.key} className={col.type === "number" ? "num" : undefined}>
                    {formatCell(row[col.key], col.type)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
