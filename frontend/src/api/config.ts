import type { RuntimeConfig } from "../types/config";

export async function loadConfig(): Promise<RuntimeConfig> {
  const response = await fetch("/config.json", { cache: "no-store" });
  if (!response.ok) throw new Error(`Could not load /config.json (${response.status})`);
  const raw = (await response.json()) as Partial<RuntimeConfig>;
  const authMode = raw.authMode === "entra" ? "entra" : raw.authMode === "dev" ? "dev" : undefined;
  if (!authMode) throw new Error('config.json: "authMode" must be "entra" or "dev"');
  const config: RuntimeConfig = {
    authMode,
    clientId: raw.clientId ?? "",
    authority: raw.authority ?? "",
    apiScope: raw.apiScope ?? "",
  };
  if (authMode === "entra" && (!config.clientId || !config.authority || !config.apiScope)) {
    throw new Error('config.json: "clientId", "authority" and "apiScope" are required when authMode is "entra"');
  }
  return config;
}
