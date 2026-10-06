export type AuthMode = "entra" | "dev";

export interface RuntimeConfig {
  authMode: AuthMode;
  clientId: string;
  authority: string;
  apiScope: string;
}
