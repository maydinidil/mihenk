import { afterEach, describe, expect, it, vi } from "vitest";
import { apiFetch, getHealth, readLaunchParams, sendSmokeOk, setToken } from "./client";

function fakeLocation(hash: string): Location {
  return { hash, pathname: "/", search: "" } as Location;
}

describe("readLaunchParams", () => {
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
