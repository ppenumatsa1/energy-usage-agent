import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { loadConfig } from "./api/config";
import { createMsalInstance } from "./auth/msal";
import "./index.css";
import "./thread.css";

const root = createRoot(document.getElementById("root")!);

async function start() {
  try {
    const config = await loadConfig();
    const msalInstance = config.authMode === "entra" ? await createMsalInstance(config) : undefined;
    root.render(
      <StrictMode>
        <App config={config} msalInstance={msalInstance} />
      </StrictMode>,
    );
  } catch (error) {
    console.error(error);
    root.render(
      <main className="center-screen">
        <section className="panel" role="alert">
          <h1>Energy Usage Assistant is unavailable</h1>
          <p>The app couldn't start because its configuration could not be loaded. Please try again later.</p>
        </section>
      </main>,
    );
  }
}

void start();
