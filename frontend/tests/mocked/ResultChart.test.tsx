import { render, screen } from "@testing-library/react";
import { cloneElement, isValidElement, type ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";
import { ResultChart } from "../../src/components/ResultChart";
import { sampleResponse } from "./helpers";

vi.mock("recharts", async (importOriginal) => {
  const actual = await importOriginal<typeof import("recharts")>();
  return {
    ...actual,
    // jsdom has no layout, so give the chart a fixed size.
    ResponsiveContainer: ({ children }: { children: ReactNode }) => (
      <div style={{ width: 800, height: 280 }}>
        {isValidElement<{ width?: number; height?: number }>(children)
          ? cloneElement(children, { width: 800, height: 280 })
          : children}
      </div>
    ),
  };
});

describe("ResultChart", () => {
  it.each(["line", "bar"] as const)("renders a %s chart", (type) => {
    const { container } = render(
      <ResultChart chart={{ ...sampleResponse.chart!, type, title: `Usage ${type}` }} table={sampleResponse.table!} />,
    );
    expect(screen.getByRole("group", { name: `Usage ${type}` })).toBeInTheDocument();
    expect(screen.getByText(`Usage ${type}`)).toBeInTheDocument();
    expect(container.querySelector("svg")).not.toBeNull();
  });

  it("renders multiple series", () => {
    const table = {
      columns: [
        { key: "period", label: "Period", type: "string" as const },
        { key: "a", label: "This month", type: "number" as const },
        { key: "b", label: "Last month", type: "number" as const },
      ],
      rows: [
        { period: "1", a: 1, b: 2 },
        { period: "2", a: 3, b: 4 },
      ],
      unit: "kWh",
    };
    const { container } = render(<ResultChart chart={{ type: "bar", x: "period", y: ["a", "b"], title: "" }} table={table} />);
    expect(container.querySelector("svg")).not.toBeNull();
  });
});
