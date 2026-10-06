import { useCallback, useMemo, useState, type ReactNode } from "react";
import { getDevToken } from "../api/client";
import { AuthContext, type AuthState } from "./context";

const TOKEN_KEY = "eua.dev.token";
const LABEL_KEY = "eua.dev.label";

function readSession(key: string): string | null {
  try {
    return sessionStorage.getItem(key);
  } catch {
    return null;
  }
}

function writeSession(key: string, value: string | null) {
  try {
    if (value === null) sessionStorage.removeItem(key);
    else sessionStorage.setItem(key, value);
  } catch {
    // Storage may be unavailable (private mode); the token then lives in memory only.
  }
}

export function DevAuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(() => readSession(TOKEN_KEY));
  const [label, setLabel] = useState<string | null>(() => readSession(LABEL_KEY));
  const [isBusy, setBusy] = useState(false);

  const clear = useCallback(() => {
    writeSession(TOKEN_KEY, null);
    writeSession(LABEL_KEY, null);
    setToken(null);
    setLabel(null);
  }, []);

  const signIn = useCallback(async (userId?: string, userLabel?: string) => {
    if (!userId) throw new Error("Choose a dev user to sign in");
    setBusy(true);
    try {
      const accessToken = await getDevToken(userId);
      const display = userLabel ?? userId;
      writeSession(TOKEN_KEY, accessToken);
      writeSession(LABEL_KEY, display);
      setToken(accessToken);
      setLabel(display);
    } finally {
      setBusy(false);
    }
  }, []);

  const getToken = useCallback(async () => {
    if (!token) throw new Error("Not signed in");
    return token;
  }, [token]);

  const value = useMemo<AuthState>(
    () => ({
      mode: "dev",
      isAuthenticated: Boolean(token),
      isBusy,
      userLabel: label,
      signIn,
      signOut: clear,
      getToken,
      reauthenticate: clear,
    }),
    [token, isBusy, label, signIn, clear, getToken],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
