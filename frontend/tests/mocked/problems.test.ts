import { describe, expect, it } from "vitest";
import { ApiError, NetworkError, errorMessage, problemMessage, toApiError } from "../../src/api/problems";
import { problemResponse } from "./helpers";

describe("problem code → message", () => {
  it.each([
    ["not_onboarded", 403, "Your account isn't set up yet. Contact your administrator."],
    ["rate_limited", 429, "You're asking quickly — try again in a few seconds."],
    ["invalid_request", 422, "I couldn't process that question. Please rephrase it and try again."],
    ["upstream_unavailable", 503, "The usage service is temporarily unavailable. Please try again in a moment."],
    ["conversation_not_found", 404, "This conversation is no longer available. Start a new chat to continue."],
    ["unauthorized", 401, "Your session has expired. Signing you in again…"],
  ])("maps %s", (code, status, message) => {
    expect(problemMessage({ code, status })).toBe(message);
  });

  it("includes Retry-After seconds for rate limiting", async () => {
    const response = problemResponse(429, "rate_limited");
    response.headers.set("Retry-After", "12");
    const error = await toApiError(response);
    expect(error.retryAfterSeconds).toBe(12);
    expect(errorMessage(error)).toBe("You're asking quickly — try again in 12 seconds.");
  });

  it("falls back on status for unknown codes", () => {
    expect(problemMessage({ status: 403 })).toBe("You don't have access to this data.");
    expect(problemMessage({ status: 500 })).toBe("Something went wrong. Please try again.");
  });

  it("parses problem+json into ApiError with correlation id", async () => {
    const error = await toApiError(problemResponse(503, "upstream_unavailable"));
    expect(error).toBeInstanceOf(ApiError);
    expect(error.code).toBe("upstream_unavailable");
    expect(error.correlationId).toBe("corr-err");
  });

  it("handles network errors", () => {
    expect(errorMessage(new NetworkError())).toMatch(/couldn't reach the server/);
  });
});
