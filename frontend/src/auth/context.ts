import { createContext, useContext } from "react";
import type { AuthMode } from "../types/config";

export interface AuthState {
  mode: AuthMode;
  isAuthenticated: boolean;
  /** True while a sign-in, redirect or token exchange is in progress. */
  isBusy: boolean;
  userLabel: string | null;
  /** Entra: starts the redirect sign-in. Dev: exchanges the synthetic user id for a token. */
  signIn(userId?: string, userLabel?: string): Promise<void>;
  signOut(): void;
  getToken(): Promise<string>;
  /** Called on 401: silently refresh if possible, otherwise sign in again. */
  reauthenticate(): void;
}

export const AuthContext = createContext<AuthState | null>(null);

export function useAuth(): AuthState {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth must be used inside an auth provider");
  return value;
}
