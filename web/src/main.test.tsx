import "@testing-library/jest-dom/vitest";
import { screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// main.tsx runs when it is imported, so each test loads a fresh copy of it and of the client.
async function startMain(): Promise<void> {
  vi.resetModules();
  await import("./main");
}

function healthyServer() {
  const mock = vi.fn<typeof fetch>(() => Promise.resolve(Response.json({ status: "ok", version: "0.0.1" })));
  vi.stubGlobal("fetch", mock);
  return mock;
}

describe("main", () => {
  beforeEach(() => {
    const root = document.createElement("div");
    root.id = "root";
    document.body.replaceChildren(root);
    sessionStorage.clear();
    window.history.replaceState(null, "", "/");
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    document.body.replaceChildren();
  });

  it("asks to open mihenk from its app window when there is no token", async () => {
    const fetchMock = healthyServer();
    await startMain();
    expect(await screen.findByRole("alert")).toHaveTextContent("Open mihenk from its app window.");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("starts the app with the launch token and clears it from the address", async () => {
    window.history.replaceState(null, "", "/#token=launch-token");
    const fetchMock = healthyServer();
    await startMain();
    expect(await screen.findByText("Connected to mihenk 0.0.1")).toBeInTheDocument();
    expect(new Headers(fetchMock.mock.calls[0]?.[1]?.headers).get("X-Mihenk-Token")).toBe("launch-token");
    expect(window.location.hash).toBe("");
    expect(sessionStorage.getItem("mihenk.token")).toBe("launch-token");
  });

  it("clears the token from the address and still starts when session storage is blocked", async () => {
    window.history.replaceState(null, "", "/#token=launch-token");
    healthyServer();
    vi.spyOn(window, "sessionStorage", "get").mockImplementation(() => {
      throw new DOMException("blocked", "SecurityError");
    });
    await startMain();
    expect(await screen.findByText("Connected to mihenk 0.0.1")).toBeInTheDocument();
    expect(window.location.hash).toBe("");
  });

  it("treats an empty token in the address as no token", async () => {
    window.history.replaceState(null, "", "/#token=");
    const fetchMock = healthyServer();
    await startMain();
    expect(await screen.findByRole("alert")).toHaveTextContent("Open mihenk from its app window.");
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
