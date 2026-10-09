import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { apiFetch, getHealth, getSessionStorage, readLaunchParams, sendSmokeOk, setToken } from "./client";

function fakeLocation(hash: string, search = "", pathname = "/"): Location {
  return { hash, pathname, search } as Location;
}

// A history that records the address each replaceState call sets.
function recordingHistory(): { history: History; urls: string[] } {
  const urls: string[] = [];
  const history = { replaceState: (_d: unknown, _t: string, url: string) => urls.push(url) } as unknown as History;
  return { history, urls };
}

describe("readLaunchParams", () => {
  beforeEach(() => {
    sessionStorage.clear();
  });

  it("takes the token from the fragment, stores it and clears the fragment", () => {
    const calls: string[] = [];
    const history = { replaceState: (_d: unknown, _t: string, url: string) => calls.push(url) } as unknown as History;
    const result = readLaunchParams(fakeLocation("#token=abc&smoke=1"), sessionStorage, history);
    expect(result).toEqual({ token: "abc", smoke: true });
    expect(sessionStorage.getItem("mihenk.token")).toBe("abc");
    expect(calls).toEqual(["/"]);
  });

  it("falls back to the stored token after a reload", () => {
    sessionStorage.setItem("mihenk.token", "stored");
    const history = { replaceState: () => undefined } as unknown as History;
    expect(readLaunchParams(fakeLocation(""), sessionStorage, history)).toEqual({ token: "stored", smoke: false });
  });

  it("returns no token when the fragment has none and nothing is stored", () => {
    const { history, urls } = recordingHistory();
    expect(readLaunchParams(fakeLocation(""), sessionStorage, history)).toEqual({ token: null, smoke: false });
    expect(urls).toEqual([]);
  });

  it("counts an empty token in the fragment as no token", () => {
    const { history } = recordingHistory();
    expect(readLaunchParams(fakeLocation("#token="), sessionStorage, history)).toEqual({ token: null, smoke: false });
    expect(sessionStorage.getItem("mihenk.token")).toBeNull();
  });

  it("falls back to the stored token when the fragment token is empty", () => {
    sessionStorage.setItem("mihenk.token", "stored");
    const { history } = recordingHistory();
    expect(readLaunchParams(fakeLocation("#token=&smoke=1"), sessionStorage, history)).toEqual({
      token: "stored",
      smoke: true,
    });
    expect(sessionStorage.getItem("mihenk.token")).toBe("stored");
  });

  it("keeps the path and the query string when it clears the fragment", () => {
    const { history, urls } = recordingHistory();
    readLaunchParams(fakeLocation("#token=abc", "?lang=nl&x=1", "/app/"), sessionStorage, history);
    expect(urls).toEqual(["/app/?lang=nl&x=1"]);
  });

  it("leaves the stored token in place after reading it, so a second reload still works", () => {
    sessionStorage.setItem("mihenk.token", "stored");
    const { history } = recordingHistory();
    expect(readLaunchParams(fakeLocation(""), sessionStorage, history).token).toBe("stored");
    expect(sessionStorage.getItem("mihenk.token")).toBe("stored");
    expect(readLaunchParams(fakeLocation(""), sessionStorage, history).token).toBe("stored");
  });

  it("clears the fragment before it stores the token", () => {
    const order: string[] = [];
    const history = { replaceState: () => order.push("clear fragment") } as unknown as History;
    const storage = { setItem: () => order.push("store token"), getItem: () => null } as unknown as Storage;
    readLaunchParams(fakeLocation("#token=abc"), storage, history);
    expect(order).toEqual(["clear fragment", "store token"]);
  });

  it("still returns the token, with the fragment cleared, when storing it fails", () => {
    const { history, urls } = recordingHistory();
    const storage = {
      setItem: () => {
        throw new DOMException("full", "QuotaExceededError");
      },
      getItem: () => null,
    } as unknown as Storage;
    expect(readLaunchParams(fakeLocation("#token=abc"), storage, history)).toEqual({ token: "abc", smoke: false });
    expect(urls).toEqual(["/"]);
  });

  it("returns no token when reading storage fails", () => {
    const { history } = recordingHistory();
    const storage = {
      getItem: () => {
        throw new DOMException("denied", "SecurityError");
      },
    } as unknown as Storage;
    expect(readLaunchParams(fakeLocation(""), storage, history)).toEqual({ token: null, smoke: false });
  });

  it("works with no storage at all", () => {
    const { history, urls } = recordingHistory();
    expect(readLaunchParams(fakeLocation("#token=abc&smoke=1"), null, history)).toEqual({ token: "abc", smoke: true });
    expect(urls).toEqual(["/"]);
    expect(readLaunchParams(fakeLocation(""), null, history)).toEqual({ token: null, smoke: false });
  });
});

describe("getSessionStorage", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("returns the browser's session storage", () => {
    expect(getSessionStorage()).toBe(window.sessionStorage);
  });

  it("returns null when the browser refuses access to it", () => {
    vi.spyOn(window, "sessionStorage", "get").mockImplementation(() => {
      throw new DOMException("blocked", "SecurityError");
    });
    expect(getSessionStorage()).toBeNull();
  });
});

describe("apiFetch", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.resetModules();
  });

  it("refuses to call the server before a token is set", async () => {
    vi.resetModules();
    const fresh = await import("./client");
    const fetchMock = vi.fn<typeof fetch>();
    vi.stubGlobal("fetch", fetchMock);
    await expect(fresh.apiFetch("/api/health")).rejects.toThrow("No launch token");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it.each([
    ["an absolute http address", "http://evil.example/api/health"],
    ["an absolute https address", "https://evil.example/api/health"],
    ["a scheme without slashes", "mailto:someone@evil.example"],
    ["a script address", "javascript:alert(1)"],
    ["a protocol-relative address", "//evil.example/api/health"],
    ["a backslash that a browser reads as a slash", "/\\evil.example/api/health"],
    ["a tab that a browser drops from the address", "/\t/evil.example/api/health"],
    ["a path without a leading slash", "api/health"],
    ["an empty path", ""],
  ])("refuses %s and never sends the token", async (_name, path) => {
    const fetchMock = vi.fn<typeof fetch>();
    vi.stubGlobal("fetch", fetchMock);
    setToken("tok");
    await expect(apiFetch(path)).rejects.toThrow("only to paths on this server");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("allows a path with a query string", async () => {
    const fetchMock = vi.fn<typeof fetch>(() => Promise.resolve(Response.json({})));
    vi.stubGlobal("fetch", fetchMock);
    setToken("tok");
    await apiFetch("/api/things?limit=5&q=a%20b");
    expect(fetchMock.mock.calls[0]?.[0]).toBe("/api/things?limit=5&q=a%20b");
  });

  it("sends the token and turns a refusal into an error", async () => {
    const fetchMock = vi.fn<typeof fetch>(() => Promise.resolve(new Response("Refused: token", { status: 403 })));
    vi.stubGlobal("fetch", fetchMock);
    setToken("tok");
    await expect(apiFetch("/api/health")).rejects.toThrow("The mihenk server answered 403");
    const init = fetchMock.mock.calls[0]?.[1];
    expect(new Headers(init?.headers).get("X-Mihenk-Token")).toBe("tok");
  });

  it("rejects a health answer that does not match the API type", async () => {
    vi.stubGlobal("fetch", vi.fn<typeof fetch>(() => Promise.resolve(Response.json({ status: "down", version: "0.0.1" }))));
    setToken("tok");
    await expect(getHealth(new AbortController().signal)).rejects.toThrow("unexpected answer");
  });

  it("posts the smoke signal", async () => {
    const fetchMock = vi.fn<typeof fetch>(() => Promise.resolve(Response.json({ received: true })));
    vi.stubGlobal("fetch", fetchMock);
    setToken("tok");
    await sendSmokeOk(new AbortController().signal);
    expect(fetchMock.mock.calls[0]?.[0]).toBe("/api/smoke/ok");
    expect(fetchMock.mock.calls[0]?.[1]?.method).toBe("POST");
  });
});
