import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { App } from "../../src/App";
import type { RuntimeConfig } from "../../src/types/config";
import { jsonResponse, mockFetch, problemResponse } from "./helpers";

const devConfig: RuntimeConfig = { authMode: "dev", clientId: "", authority: "", apiScope: "" };

describe("not onboarded", () => {
  beforeEach(() => sessionStorage.setItem("eua.dev.token", "tok-c1"));

  it("shows the friendly screen when /api/me says onboarded=false", async () => {
    const fetchMock = mockFetch({
      "GET /api/me": () => jsonResponse({ onboarded: false, customerName: null, timezone: null, userName: null }),
    });
    render(<App config={devConfig} />);
    expect(await screen.findByRole("heading", { name: "Your account isn't set up yet" })).toBeInTheDocument();
    expect(screen.getByText(/Contact your administrator/)).toBeInTheDocument();
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([url]) => url === "/api/conversations")).toBe(false);
  });

  it("shows the same screen on a 403 not_onboarded problem", async () => {
    mockFetch({ "GET /api/me": () => problemResponse(403, "not_onboarded") });
    render(<App config={devConfig} />);
    expect(await screen.findByRole("heading", { name: "Your account isn't set up yet" })).toBeInTheDocument();
  });
});
