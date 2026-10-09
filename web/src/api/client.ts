import type { components } from "./schema";

export type Health = components["schemas"]["Health"];

const TOKEN_KEY = "mihenk.token";
let token: string | null = null;

// Some browsers refuse access to session storage (blocked site data); the token then lives in
// memory only and the screens ask to be opened again after a reload.
export function getSessionStorage(): Storage | null {
  try {
    return window.sessionStorage;
  } catch {
    return null;
  }
}

function storeToken(storage: Storage | null, value: string): void {
  try {
    storage?.setItem(TOKEN_KEY, value);
  } catch {
    // Quota or access error: carry on with the token in memory.
  }
}

function readStoredToken(storage: Storage | null): string | null {
  try {
    return storage?.getItem(TOKEN_KEY) ?? null;
  } catch {
    return null;
  }
}

export function readLaunchParams(
  location: Location,
  storage: Storage | null,
  history: History,
): { token: string | null; smoke: boolean } {
  const params = new URLSearchParams(location.hash.replace(/^#/, ""));
  const smoke = params.get("smoke") === "1";
  const fromHash = params.get("token");
  if (fromHash !== null) {
    // Out of the address bar first: whatever happens to storage afterwards, the token must not
    // stay in the address (or in the history entry).
    history.replaceState(null, "", location.pathname + location.search);
  }
  // "#token=" with nothing after it is no token.
  if (fromHash !== null && fromHash !== "") {
    storeToken(storage, fromHash);
    return { token: fromHash, smoke };
  }
  return { token: readStoredToken(storage), smoke };
}

export function setToken(value: string): void {
  token = value;
}

// Only "/something" on this server. A scheme ("https://..."), "//host" and "/\host" would send the
// token to another host; a browser reads a backslash as a slash and drops tabs and newlines, so
// the check also asks the URL parser where the path really goes.
function isPathOnThisServer(path: string): boolean {
  if (!path.startsWith("/") || path.startsWith("//")) return false;
  const probe = "http://probe.invalid";
  try {
    return new URL(path, probe).origin === probe;
  } catch {
    return false;
  }
}

export async function apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
  if (!isPathOnThisServer(path)) {
    throw new Error("mihenk sends requests only to paths on this server, starting with a single /");
  }
  if (token === null) throw new Error("No launch token. Open mihenk from its app window.");
  const headers = new Headers(init.headers);
  headers.set("X-Mihenk-Token", token);
  const response = await fetch(path, { ...init, headers });
  if (!response.ok) throw new Error(`The mihenk server answered ${String(response.status)}`);
  return response;
}

function isHealth(value: unknown): value is Health {
  if (typeof value !== "object" || value === null) return false;
  const v = value as Record<string, unknown>;
  return v.status === "ok" && typeof v.version === "string";
}

export async function getHealth(signal: AbortSignal): Promise<Health> {
  const body: unknown = await (await apiFetch("/api/health", { signal })).json();
  if (!isHealth(body)) throw new Error("The mihenk server sent an unexpected answer");
  return body;
}

export async function sendSmokeOk(signal: AbortSignal): Promise<void> {
  await apiFetch("/api/smoke/ok", { method: "POST", signal });
}
