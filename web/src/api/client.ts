import type { components } from "./schema";

export type Health = components["schemas"]["Health"];

const TOKEN_KEY = "mihenk.token";
let token: string | null = null;

export function readLaunchParams(
  location: Location,
  storage: Storage,
  history: History,
): { token: string | null; smoke: boolean } {
  const params = new URLSearchParams(location.hash.replace(/^#/, ""));
  const fromHash = params.get("token");
  if (fromHash !== null) {
    storage.setItem(TOKEN_KEY, fromHash);
    history.replaceState(null, "", location.pathname + location.search);
  }
  return { token: fromHash ?? storage.getItem(TOKEN_KEY), smoke: params.get("smoke") === "1" };
}

export function setToken(value: string): void {
  token = value;
}

export async function apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
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
