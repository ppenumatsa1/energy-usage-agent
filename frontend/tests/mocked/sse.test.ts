import { describe, expect, it } from "vitest";
import { createSseParser, readSseStream, type SseEvent } from "../../src/api/sse";
import { sseResponse } from "./helpers";

describe("SSE parser", () => {
  it("assembles events split across chunks", () => {
    const events: SseEvent[] = [];
    const parser = createSseParser((e) => events.push(e));
    parser.push("event: sta");
    parser.push('tus\ndata: {"stage":"thi');
    parser.push('nking"}\n');
    expect(events).toHaveLength(0);
    parser.push("\nevent: result\r\n");
    parser.push('data: {"answer":"hi"}\r');
    parser.push("\n\r\n");
    expect(events).toEqual([
      { event: "status", data: '{"stage":"thinking"}', id: undefined },
      { event: "result", data: '{"answer":"hi"}', id: undefined },
    ]);
  });

  it("joins multi-line data, ignores comments and flushes the last event", () => {
    const events: SseEvent[] = [];
    const parser = createSseParser((e) => events.push(e));
    parser.push(": keep-alive\n\ndata: line1\ndata: line2\n\nevent: error\ndata: {}");
    parser.flush();
    expect(events).toEqual([
      { event: "message", data: "line1\nline2", id: undefined },
      { event: "error", data: "{}", id: undefined },
    ]);
  });

  it("reads a byte stream split mid-character", async () => {
    const events: SseEvent[] = [];
    const bytes = new TextEncoder().encode('event: result\ndata: {"answer":"5 kWh – ok"}\n\n');
    const split = bytes.indexOf(0xe2) + 1; // split inside the multi-byte en dash
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(bytes.slice(0, split));
        controller.enqueue(bytes.slice(split));
        controller.close();
      },
    });
    await readSseStream(stream, (e) => events.push(e));
    expect(events).toEqual([{ event: "result", data: '{"answer":"5 kWh – ok"}', id: undefined }]);
  });

  it("works with a fetch Response body", async () => {
    const events: SseEvent[] = [];
    await readSseStream(sseResponse(["event: status\nda", 'ta: {"stage":"tool"}\n\n']).body!, (e) => events.push(e));
    expect(events.map((e) => e.event)).toEqual(["status"]);
  });
});
