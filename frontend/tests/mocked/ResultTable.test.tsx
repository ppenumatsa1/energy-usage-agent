import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { ResultTable } from "../../src/components/ResultTable";
import { sampleResponse } from "./helpers";

describe("ResultTable", () => {
  it("renders columns and formatted rows", () => {
    render(<ResultTable table={sampleResponse.table!} />);
    const table = screen.getByRole("table");
    const headers = within(table).getAllByRole("columnheader").map((h) => h.textContent);
    expect(headers[0]).toContain("Period");
    expect(headers[1]).toContain("Usage (kWh)");
    const rows = within(table).getAllByRole("row");
    expect(rows).toHaveLength(3);
    expect(within(rows[1]).getByText("2026-10-01")).toBeInTheDocument();
    expect(within(rows[1]).getByText("400.12")).toBeInTheDocument();
    expect(within(rows[2]).getByText("834.45")).toBeInTheDocument();
    expect(screen.getByText(/2 rows/)).toBeInTheDocument();
  });

  it("formats thousands separators and sorts by column", async () => {
    render(
      <ResultTable
        table={{
          columns: [
            { key: "site", label: "Site", type: "string" },
            { key: "kwh", label: "kWh", type: "number" },
          ],
          rows: [
            { site: "North", kwh: 1234567.891 },
            { site: "South", kwh: 12 },
          ],
          unit: "kWh",
        }}
      />,
    );
    expect(screen.getByText("1,234,567.89")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /kWh/ }));
    let rows = screen.getAllByRole("row");
    expect(within(rows[1]).getByText("South")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /kWh/ }));
    rows = screen.getAllByRole("row");
    expect(within(rows[1]).getByText("North")).toBeInTheDocument();
  });
});
