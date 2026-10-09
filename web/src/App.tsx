import { useEffect, useState } from "react";
import { getHealth, sendSmokeOk, type Health } from "./api/client";

type Status =
  | { kind: "loading" }
  | { kind: "ok"; health: Health }
  | { kind: "error"; message: string };

export default function App({ smoke }: { smoke: boolean }) {
  const [status, setStatus] = useState<Status>({ kind: "loading" });

  useEffect(() => {
    const controller = new AbortController();
    async function check(): Promise<void> {
      try {
        const health = await getHealth(controller.signal);
        setStatus({ kind: "ok", health });
        if (smoke) await sendSmokeOk(controller.signal);
      } catch (error: unknown) {
        // An aborted request means the screen went away; there is nothing left to tell.
        if (controller.signal.aborted) return;
        setStatus({ kind: "error", message: error instanceof Error ? error.message : String(error) });
      }
    }
    void check();
    return () => {
      controller.abort();
    };
  }, [smoke]);

  return (
    <main>
      <h1>mihenk</h1>
      {status.kind === "loading" && <p>Checking the connection…</p>}
      {status.kind === "ok" && <p>Connected to mihenk {status.health.version}</p>}
      {status.kind === "error" && <p role="alert">Cannot reach the mihenk server: {status.message}</p>}
    </main>
  );
}
