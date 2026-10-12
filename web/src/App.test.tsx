import "@testing-library/jest-dom/vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import { setToken } from "./api/client";

const TOKEN = "test-token-0123456789abcdef0123456789";

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
}

// The client always passes a plain path string to fetch.
function pathOf(input: Parameters<typeof fetch>[0]): string {
  if (typeof input !== "string") throw new Error("fetch was not called with a path string");
  return input;
}

// Replaces fetch and returns what each call asked for, so a test can check path, method and token.
function stubFetch(answer: (path: string) => Promise<Response>) {
  const mock = vi.fn<typeof fetch>((input) => answer(pathOf(input)));
  vi.stubGlobal("fetch", mock);
  return () =>
    mock.mock.calls.map(([input, init]) => ({
      path: pathOf(input),
      method: init?.method ?? "GET",
      token: new Headers(init?.headers).get("X-Mihenk-Token"),
    }));
}

describe("App", () => {
  beforeEach(() => {
    setToken(TOKEN);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("shows the server version once the health check answers", async () => {
    const calls = stubFetch(() => Promise.resolve(jsonResponse({ status: "ok", version: "0.0.1" })));
    render(<App smoke={false} />);
    expect(await screen.findByText("Connected to mihenk 0.0.1")).toBeInTheDocument();
    expect(calls()).toEqual([{ path: "/api/health", method: "GET", token: TOKEN }]);
  });

  it("shows an alert when the server cannot be reached", async () => {
    stubFetch(() => Promise.reject(new Error("offline")));
    render(<App smoke={false} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Cannot reach the mihenk server");
  });

  it("tells the server it loaded when started in smoke mode", async () => {
    const calls = stubFetch((path) =>
      Promise.resolve(jsonResponse(path === "/api/smoke/ok" ? { received: true } : { status: "ok", version: "0.0.1" })),
    );
    render(<App smoke={true} />);
    await waitFor(() => {
      expect(calls()).toHaveLength(2);
    });
    expect(calls()).toEqual([
      { path: "/api/health", method: "GET", token: TOKEN },
      { path: "/api/smoke/ok", method: "POST", token: TOKEN },
    ]);
  });
});
