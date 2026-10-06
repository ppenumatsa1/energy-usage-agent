export interface SseEvent {
  event: string;
  data: string;
  id?: string;
}

export interface SseParser {
  /** Feed a decoded text chunk; complete events are dispatched synchronously. */
  push(chunk: string): void;
  /** Dispatch any event left in the buffer when the stream ends without a trailing blank line. */
  flush(): void;
}

/**
 * Incremental parser for the text/event-stream format.
 * Handles events split across chunks, CRLF/CR/LF line endings, comments and multi-line data.
 */
export function createSseParser(onEvent: (event: SseEvent) => void): SseParser {
  let buffer = "";
  let eventName = "";
  let dataLines: string[] = [];
  let lastId: string | undefined;
  let pendingCR = false;

  const dispatch = () => {
    if (dataLines.length > 0) {
      onEvent({ event: eventName || "message", data: dataLines.join("\n"), id: lastId });
    }
    eventName = "";
    dataLines = [];
  };

  const processLine = (line: string) => {
    if (line === "") {
      dispatch();
      return;
    }
    if (line.startsWith(":")) return;
    const colon = line.indexOf(":");
    const field = colon === -1 ? line : line.slice(0, colon);
    let value = colon === -1 ? "" : line.slice(colon + 1);
    if (value.startsWith(" ")) value = value.slice(1);
    switch (field) {
      case "event":
        eventName = value;
        break;
      case "data":
        dataLines.push(value);
        break;
      case "id":
        lastId = value;
        break;
      default:
        break;
    }
  };

  return {
    push(chunk: string) {
      let text = chunk;
      // A CR at the end of the previous chunk may be the first half of a CRLF pair.
      if (pendingCR && text.startsWith("\n")) text = text.slice(1);
      pendingCR = false;
      buffer += text;
      let start = 0;
      for (let i = 0; i < buffer.length; i++) {
        const ch = buffer[i];
        if (ch === "\n" || ch === "\r") {
          processLine(buffer.slice(start, i));
          if (ch === "\r") {
            if (i + 1 < buffer.length) {
              if (buffer[i + 1] === "\n") i++;
            } else {
              pendingCR = true;
            }
          }
          start = i + 1;
        }
      }
      buffer = buffer.slice(start);
    },
    flush() {
      if (buffer !== "") {
        processLine(buffer);
        buffer = "";
      }
      dispatch();
    },
  };
}

/** Reads a fetch body stream and dispatches SSE events until the stream ends. */
export async function readSseStream(
  body: ReadableStream<Uint8Array>,
  onEvent: (event: SseEvent) => void,
): Promise<void> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  const parser = createSseParser(onEvent);
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      parser.push(decoder.decode(value, { stream: true }));
    }
    parser.push(decoder.decode());
    parser.flush();
  } finally {
    reader.releaseLock();
  }
}
