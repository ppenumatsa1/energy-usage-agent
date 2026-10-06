import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "../../src/App";
import type { ConversationDetail, ConversationSummary } from "../../src/types/api";
import type { RuntimeConfig } from "../../src/types/config";
import { jsonResponse, mockFetch, problemResponse, sampleResponse, sampleStatus } from "./helpers";

vi.mock("recharts", async (importOriginal) => {
  const actual = await importOriginal<typeof import("recharts")>();
  return { ...actual, ResponsiveContainer: () => <div data-testid="chart" /> };
});

const devConfig: RuntimeConfig = { authMode: "dev", clientId: "", authority: "", apiScope: "" };
const me = { onboarded: true, customerName: "Example Customer", timezone: "America/Chicago", userName: "Test User" };

const summary: ConversationSummary = {
  conversationId: "conv-1",
  title: "Show my usage this month.",
  createdAt: new Date(Date.now() - 3 * 3600_000).toISOString(),
  updatedAt: new Date(Date.now() - 2 * 3600_000).toISOString(),
  turnCount: 2,
};

const detail: ConversationDetail = {
  conversationId: "conv-1",
  title: summary.title,
  createdAt: summary.createdAt,
  updatedAt: summary.updatedAt,
  turns: [
    { question: "Show my usage this month.", response: sampleResponse },
    {
      question: "What does my bill cost?",
      response: {
        ...sampleResponse,
        status: "refused",
        answer: "I can only answer questions about energy usage.",
        table: null,
        chart: null,
        assumptions: [],
        correlationId: "corr-2",
        trace: {
          ...sampleResponse.trace,
          steps: [],
          checks: [{ name: "Energy topics only", detail: "Billing is out of scope.", outcome: "blocked" }],
        },
      },
    },
  ],
};

describe("conversation history", () => {
  beforeEach(() => {
    sessionStorage.setItem("eua.dev.token", "tok-a1");
    sessionStorage.setItem("eua.dev.label", "Tenant A · User 1");
  });

  it("loads a conversation's earlier turns and appends follow-ups", async () => {
    const fetchMock = mockFetch({
      "GET /api/me": () => jsonResponse(me),
      "GET /api/status": () => jsonResponse(sampleStatus),
      "GET /api/conversations": () => jsonResponse([summary]),
      "GET /api/conversations/conv-1": () => jsonResponse(detail),
      "POST /api/chat": () => jsonResponse({ ...sampleResponse, answer: "Last month you used 999 kWh." }),
    });
    render(<App config={devConfig} />);

    const nav = await screen.findByRole("navigation", { name: "Conversations" });
    const item = await within(nav).findByRole("button", { name: /^Show my usage this month/ });
    expect(item).toHaveTextContent("2h ago");
    expect(item).toHaveTextContent("2 questions");
    expect(within(nav).getByText("History kept 30 days")).toBeInTheDocument();

    await userEvent.click(item);
    expect(await screen.findByText(/You used 1,234.57 kWh/)).toBeInTheDocument();
    expect(screen.getByText("I can only answer questions about energy usage.")).toBeInTheDocument();
    expect(screen.getByText("Out of scope")).toBeInTheDocument();
    expect(screen.getAllByText("You asked")).toHaveLength(2);
    expect(screen.getByRole("table")).toBeInTheDocument();
    expect(screen.queryByText(/Earlier messages/)).not.toBeInTheDocument();
    expect(item).toHaveAttribute("aria-current", "page");

    const box = screen.getByRole("textbox", { name: /ask about your energy usage/i });
    await userEvent.type(box, "and last month?{Enter}");
    expect(await screen.findByText("Last month you used 999 kWh.")).toBeInTheDocument();
    expect(screen.getAllByText("You asked")).toHaveLength(3);
    const chatCall = fetchMock.mock.calls.find(([url]) => url === "/api/chat")!;
    expect(JSON.parse((chatCall[1] as RequestInit).body as string)).toEqual({
      message: "and last month?",
      conversationId: "conv-1",
    });
  });

  it("shows a friendly message and drops the conversation on 404", async () => {
    mockFetch({
      "GET /api/me": () => jsonResponse(me),
      "GET /api/conversations": () => jsonResponse([summary]),
      "GET /api/conversations/conv-1": () => problemResponse(404, "conversation_not_found"),
    });
    render(<App config={devConfig} />);
    const nav = await screen.findByRole("navigation", { name: "Conversations" });
    await userEvent.click(await within(nav).findByRole("button", { name: /^Show my usage this month/ }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Conversation not found");
    expect(alert).toHaveTextContent(/no longer available/);
    await waitFor(() => expect(within(nav).queryByRole("button", { name: /^Show my usage this month/ })).toBeNull());
    await userEvent.click(within(alert).getByRole("button", { name: "Start a new conversation" }));
    expect(await screen.findByRole("heading", { name: /What would you like to know/ })).toBeInTheDocument();
  });

  it("explains when an older conversation has no saved turns", async () => {
    mockFetch({
      "GET /api/me": () => jsonResponse(me),
      "GET /api/conversations": () => jsonResponse([{ ...summary, turnCount: 0 }]),
      "GET /api/conversations/conv-1": () => jsonResponse({ ...detail, turns: [] }),
    });
    render(<App config={devConfig} />);
    const nav = await screen.findByRole("navigation", { name: "Conversations" });
    await userEvent.click(await within(nav).findByRole("button", { name: /^Show my usage this month/ }));
    expect(await screen.findByText(/Earlier messages from this conversation weren't saved/)).toBeInTheDocument();
  });

  it("deletes a conversation after confirmation", async () => {
    const fetchMock = mockFetch({
      "GET /api/me": () => jsonResponse(me),
      "GET /api/conversations": () => jsonResponse([summary]),
      "DELETE /api/conversations/conv-1": () => new Response(null, { status: 204 }),
    });
    render(<App config={devConfig} />);
    const nav = await screen.findByRole("navigation", { name: "Conversations" });
    await userEvent.click(await within(nav).findByRole("button", { name: /Delete conversation/ }));
    expect(fetchMock.mock.calls.some(([, init]) => (init as RequestInit)?.method === "DELETE")).toBe(false);
    await userEvent.click(within(nav).getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(within(nav).queryByRole("button", { name: /^Show my usage this month/ })).toBeNull());
    expect(fetchMock.mock.calls.some(([, init]) => (init as RequestInit)?.method === "DELETE")).toBe(true);
  });
});

describe("trace and status", () => {
  beforeEach(() => sessionStorage.setItem("eua.dev.token", "tok-a1"));

  it("expands 'How this was answered' with tool steps and guardrail checks", async () => {
    mockFetch({
      "GET /api/me": () => jsonResponse(me),
      "GET /api/conversations": () => jsonResponse([summary]),
      "GET /api/conversations/conv-1": () => jsonResponse(detail),
    });
    render(<App config={devConfig} />);
    const nav = await screen.findByRole("navigation", { name: "Conversations" });
    await userEvent.click(await within(nav).findByRole("button", { name: /^Show my usage this month/ }));
    await screen.findByText(/You used 1,234.57 kWh/);

    const [toggle] = screen.getAllByRole("button", { name: /How this was answered/ });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText("get_usage")).not.toBeInTheDocument();
    await userEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");

    const body = document.getElementById(toggle.getAttribute("aria-controls")!)!;
    expect(within(body).getByText("Understood question")).toBeInTheDocument();
    expect(within(body).getByText("get_usage")).toBeInTheDocument();
    expect(within(body).getByText("start:").parentElement).toHaveTextContent("start: this_month");
    expect(within(body).getByText("57 ms")).toBeInTheDocument();
    expect(within(body).getByText("completed")).toBeInTheDocument();
    expect(within(body).getByText("Composed answer")).toBeInTheDocument();
    expect(within(body).getByText("Signed-in scope")).toBeInTheDocument();
    expect(within(body).getByText("Numbers from tools")).toBeInTheDocument();
    expect(within(body).getByText("corr-123")).toBeInTheDocument();

    // The global "Show details" switch opens every answer's panel.
    await userEvent.click(screen.getByRole("switch", { name: "Show details" }));
    for (const t of screen.getAllByRole("button", { name: /How this was answered/ })) {
      expect(t).toHaveAttribute("aria-expanded", "true");
    }
    expect(screen.getByText("Billing is out of scope.")).toBeInTheDocument();
  });

  it("renders status pills from /api/status", async () => {
    mockFetch({
      "GET /api/me": () => jsonResponse(me),
      "GET /api/status": () => jsonResponse(sampleStatus),
      "GET /api/conversations": () => jsonResponse([]),
    });
    render(<App config={devConfig} />);
    const pills = await screen.findByRole("list", { name: "Service status" });
    const items = within(pills).getAllByRole("listitem");
    expect(items.map((i) => i.textContent)).toEqual([
      "API operational",
      "Energy data operational",
      "History down",
      "Agent operational",
    ]);
    expect(items[2]).toHaveClass("pill--down");
    expect(items[2]).toHaveAttribute("title", "History: Database unreachable");
  });
});
