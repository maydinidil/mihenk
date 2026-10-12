import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import { getSessionStorage, readLaunchParams, setToken } from "./api/client";

const container = document.getElementById("root");
if (container === null) throw new Error("index.html has no #root element");
const root = createRoot(container);

const { token, smoke } = readLaunchParams(window.location, getSessionStorage(), window.history);
if (token === null) {
  root.render(<p role="alert">Open mihenk from its app window.</p>);
} else {
  setToken(token);
  root.render(
    <StrictMode>
      <App smoke={smoke} />
    </StrictMode>,
  );
}
