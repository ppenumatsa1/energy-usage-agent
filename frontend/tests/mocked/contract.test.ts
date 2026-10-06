import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const SRC = join(__dirname, "..", "..", "src");

function files(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    return statSync(path).isDirectory() ? files(path) : [path];
  });
}

describe("frontend contract", () => {
  it("never hardcodes absolute http(s) URLs in src", () => {
    const offenders = files(SRC).filter((f) => /https?:\/\//.test(readFileSync(f, "utf8")));
    expect(offenders).toEqual([]);
  });
});
