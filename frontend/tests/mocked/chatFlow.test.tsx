import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "../../src/App";
import type { RuntimeConfig } from "../../src/types/config";
import { jsonResponse, mockFetch, problemResponse, sampleResponse, sseResponse } from "./helpers";

vi.mock("recharts", async (importOriginal) => {
  const actual = await importOriginal<typeof import("recharts")>();
  return { ...actual, ResponsiveContainer: () => <div data-testid="chart" /> };
});

const devConfig: RuntimeConfig = { authMode: "dev", clientId: "", authority: "", apiScope: "" };
const me = { onboarded: true, customerName: "Example Customer", timezone: "America/Chicago", userName: "Test User" };

function sseBody(result: unknown) {
  const data = JSON.stringify(result);
  const mid = Math.floor(data.length / 2);
  return [
    'event: status\ndata: {"stage":"thinking"}\n\n',
    'event: status\ndata: {"stage":"tool","tool":"get_usage"}\n\n',
    `event: result\ndata: ${data.slice(0, mid)}`,
    `${data.slice(mid)}\n\n`,
  ];
}

async function ask(question: string) {
  const box = await screen.findByRole("textbox", { name: /ask about your energy usage/i });
  await userEvent.type(box, `${question}{Enter}`);
}

describe("chat flow (dev auth, mocked fetch)", () => {
  beforeEach(() => {
    sessionStorage.setItem("eua.dev.token", "tok-a1");
    sessionStorage.setItem("eua.dev.label", "Tenant A · User 1");
  });

  it("streams an answer with table, chart and assumptions", async () => {
    const fetchMock = mockFetch({
      "GET /api/me": () => jsonResponse(me),
      "GET /api/conversations": () => jsonResponse([]),
      "POST /api/chat": () => sseResponse(sseBody(sampleResponse)),
    });
    render(<App config={devConfig} />);

    expect(await screen.findByText(/Example Customer/)).toBeInTheDocument();
    await ask("Show my usage this month.");

    expect(await screen.findByText(/You used 1,234.57 kWh so far this month/)).toBeInTheDocument();
    const table = screen.getByRole("table");
    expect(within(table).getByText("Period")).toBeInTheDocument();
    expect(within(table).getByText("834.45")).toBeInTheDocument();
    expect(screen.getByRole("list", { name: "Assumptions" })).toHaveTextContent("America/Chicago");
    expect(screen.getByTestId("chart")).toBeInTheDocument();
    expect(screen.getByText("Answered")).toBeInTheDocument();
    expect(screen.getByText("1.2 s")).toBeInTheDocument();
    expect(screen.queryByText("corr-123")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /How this was answered/ }));
    expect(screen.getByText("corr-123")).toBeInTheDocument();

    const chatCall = fetchMock.mock.calls.find(([url]) => url === "/api/chat")!;
    const init = chatCall[1] as RequestInit;
    const headers = new Headers(init.headers);
    expect(headers.get("Authorization")).toBe("Bearer tok-a1");
    expect(headers.get("Accept")).toBe("text/event-stream");
    expect(JSON.parse(init.body as string)).toEqual({ message: "Show my usage this month." });
    for (const [url] of fetchMock.mock.calls) expect(String(url)).toMatch(/^\/api\//);
  });

  it("sends the conversationId on follow-ups and falls back to JSON when the stream has no result", async () => {
    let call = 0;
    const fetchMock = mockFetch({
      "GET /api/me": () => jsonResponse(me),
      "GET /api/conversations": () => jsonResponse([]),
      "POST /api/chat": (_url, init) => {
        call += 1;
        const accept = new Headers(init.headers).get("Accept");
        if (call === 1) return sseResponse(sseBody(sampleResponse));
        if (accept === "text/event-stream") return sseResponse(['event: status\ndata: {"stage":"thinking"}\n\n']);
        return jsonResponse({ ...sampleResponse, answer: "Last month you used 999 kWh.", correlationId: "corr-456" });
      },
    });
    render(<App config={devConfig} />);
    await ask("Show my usage this month.");
    await screen.findByText(/You used 1,234.57 kWh/);
    await ask("and last month?");
    expect(await screen.findByText("Last month you used 999 kWh.")).toBeInTheDocument();

    const chatCalls = fetchMock.mock.calls.filter(([url]) => url === "/api/chat");
    expect(chatCalls).toHaveLength(3);
    expect(JSON.parse((chatCalls[2][1] as RequestInit).body as string)).toEqual({
      message: "and last month?",
      conversationId: "conv-1",
    });
  });

  it("shows a friendly error with correlation id and retries", async () => {
    let call = 0;
    mockFetch({
      "GET /api/me": () => jsonResponse(me),
      "GET /api/conversations": () => jsonResponse([]),
      "POST /api/chat": () => {
        call += 1;
        return call === 1 ? problemResponse(503, "upstream_unavailable") : sseResponse(sseBody(sampleResponse));
      },
    });
    render(<App config={devConfig} />);
    await ask("Show my usage this month.");
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("The usage service is temporarily unavailable");
    expect(alert).toHaveTextContent("corr-err");
    await userEvent.click(within(alert).getByRole("button", { name: "Retry" }));
    expect(await screen.findByText(/You used 1,234.57 kWh/)).toBeInTheDocument();
  });

  it("returns to dev sign-in on 401", async () => {
    mockFetch({
      "GET /api/me": () => problemResponse(401, "unauthorized"),
      "GET /api/dev/users": () => jsonResponse([{ id: "a1", label: "Tenant A · User 1" }]),
    });
    render(<App config={devConfig} />);
    expect(await screen.findByRole("heading", { name: "Dev sign-in" })).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: "Tenant A · User 1" })).toBeInTheDocument();
    await waitFor(() => expect(sessionStorage.getItem("eua.dev.token")).toBeNull());
  });
});

describe("dev sign-in", () => {
  it("exchanges the chosen user for a token", async () => {
    const fetchMock = mockFetch({
      "GET /api/dev/users": () => jsonResponse([{ id: "a1", label: "Tenant A · User 1" }]),
      "POST /api/dev/token": () => jsonResponse({ accessToken: "tok-new" }),
      "GET /api/me": () => jsonResponse(me),
      "GET /api/conversations": () => jsonResponse([]),
    });
    render(<App config={devConfig} />);
    await userEvent.click(await screen.findByRole("button", { name: "Tenant A · User 1" }));
    expect(await screen.findByRole("textbox", { name: /ask about your energy usage/i })).toBeInTheDocument();
    const tokenCall = fetchMock.mock.calls.find(([url]) => url === "/api/dev/token")!;
    expect(JSON.parse((tokenCall[1] as RequestInit).body as string)).toEqual({ user: "a1" });
    const meCall = fetchMock.mock.calls.find(([url]) => url === "/api/me")!;
    expect(new Headers((meCall[1] as RequestInit).headers).get("Authorization")).toBe("Bearer tok-new");

    await userEvent.click(screen.getByRole("button", { name: "Sign out" }));
    expect(await screen.findByRole("heading", { name: "Dev sign-in" })).toBeInTheDocument();
  });
});
