// CONSOLE-FOUNDATION-A — adapter + normalized error tests.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { __resetControlPlaneConfig } from "@/lib/control-plane/config";
import { AtlasAdapter } from "@/lib/control-plane/adapters/atlas";

const ctx = { correlationId: "test-corr", operatorToken: null };

function mockFetch(impl: (url: string) => Promise<Response> | Response) {
  vi.stubGlobal("fetch", vi.fn((input: unknown) => Promise.resolve(impl(String(input)))));
}

beforeEach(() => {
  process.env.ATLAS_API_BASE_URL = "http://atlas.test:8085";
  process.env.ATLAS_INTERNAL_TOKEN = "SECRET-ATLAS-TOKEN";
  __resetControlPlaneConfig();
});

afterEach(() => {
  vi.unstubAllGlobals();
  delete process.env.ATLAS_API_BASE_URL;
  delete process.env.ATLAS_INTERNAL_TOKEN;
});

describe("adapter success + attribution", () => {
  it("returns typed health with an available source", async () => {
    mockFetch(() => new Response(JSON.stringify({ service: "atlas", status: "healthy" }), { status: 200 }));
    const res = await AtlasAdapter.readHealth(ctx);
    expect(res.ok).toBe(true);
    if (res.ok) {
      expect(res.value.health).toBe("healthy");
      expect(res.source.state).toBe("available");
      expect(res.source.service).toBe("atlas");
    }
  });

  it("forwards the internal token server-side but never returns it", async () => {
    let seenAuth = "";
    mockFetch((url) => {
      void url;
      return new Response(JSON.stringify({ status: "healthy" }), { status: 200 });
    });
    const fetchSpy = vi.mocked(fetch);
    await AtlasAdapter.readHealth(ctx);
    const init = fetchSpy.mock.calls[0]?.[1] as RequestInit | undefined;
    const headers = (init?.headers ?? {}) as Record<string, string>;
    seenAuth = headers["X-Internal-Token"] ?? "";
    expect(seenAuth).toBe("SECRET-ATLAS-TOKEN"); // sent upstream
    const res = await AtlasAdapter.readHealth(ctx);
    expect(JSON.stringify(res)).not.toContain("SECRET-ATLAS-TOKEN"); // never surfaced
  });
});

describe("adapter failure modes are normalized distinctly", () => {
  it("maps 503 → SERVICE_UNAVAILABLE (retryable, source unavailable)", async () => {
    mockFetch(() => new Response("nope", { status: 503 }));
    const res = await AtlasAdapter.readHealth(ctx);
    expect(res.ok).toBe(false);
    if (!res.ok) {
      expect(res.error.code).toBe("SERVICE_UNAVAILABLE");
      expect(res.error.retryable).toBe(true);
      expect(res.source.state).toBe("unavailable");
    }
  });

  it("maps 401 → UNAUTHORIZED (source unauthorized)", async () => {
    mockFetch(() => new Response("no", { status: 401 }));
    const res = await AtlasAdapter.readHealth(ctx);
    expect(res.ok).toBe(false);
    if (!res.ok) {
      expect(res.error.code).toBe("UNAUTHORIZED");
      expect(res.source.state).toBe("unauthorized");
    }
  });

  it("maps 500 → UPSTREAM_ERROR", async () => {
    mockFetch(() => new Response("boom", { status: 500 }));
    const res = await AtlasAdapter.readHealth(ctx);
    expect(res.ok === false && res.error.code).toBe("UPSTREAM_ERROR");
  });

  it("maps malformed JSON → INVALID_RESPONSE", async () => {
    mockFetch(() => new Response("<<not json>>", { status: 200 }));
    const res = await AtlasAdapter.readHealth(ctx);
    expect(res.ok === false && res.error.code).toBe("INVALID_RESPONSE");
  });

  it("maps AbortError → TIMEOUT", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.reject(new DOMException("aborted", "AbortError"))));
    const res = await AtlasAdapter.readHealth(ctx);
    expect(res.ok === false && res.error.code).toBe("TIMEOUT");
    if (!res.ok) expect(res.source.state).toBe("timeout");
  });

  it("maps connection failure → SERVICE_UNAVAILABLE and leaks no detail", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.reject(new Error("ECONNREFUSED 10.0.0.1:8085"))));
    const res = await AtlasAdapter.readHealth(ctx);
    expect(res.ok).toBe(false);
    if (!res.ok) {
      expect(res.error.code).toBe("SERVICE_UNAVAILABLE");
      expect(res.error.message).not.toContain("10.0.0.1");
    }
  });

  it("returns CONFIGURATION_ERROR when the upstream is not configured", async () => {
    delete process.env.ATLAS_API_BASE_URL;
    __resetControlPlaneConfig();
    const res = await AtlasAdapter.readHealth(ctx);
    expect(res.ok === false && res.error.code).toBe("CONFIGURATION_ERROR");
  });
});
