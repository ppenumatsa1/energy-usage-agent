import {
  InteractionRequiredAuthError,
  InteractionStatus,
  type IPublicClientApplication,
} from "@azure/msal-browser";
import { MsalProvider, useIsAuthenticated, useMsal } from "@azure/msal-react";
import { useCallback, useMemo, type ReactNode } from "react";
import type { RuntimeConfig } from "../types/config";
import { AuthContext, type AuthState } from "./context";

interface Props {
  instance: IPublicClientApplication;
  config: RuntimeConfig;
  children: ReactNode;
}

export function EntraAuthProvider({ instance, config, children }: Props) {
  return (
    <MsalProvider instance={instance}>
      <EntraAuthBridge config={config}>{children}</EntraAuthBridge>
    </MsalProvider>
  );
}

function EntraAuthBridge({ config, children }: { config: RuntimeConfig; children: ReactNode }) {
  const { instance, inProgress, accounts } = useMsal();
  const isAuthenticated = useIsAuthenticated();
  const scopes = useMemo(() => [config.apiScope], [config.apiScope]);

  const account = instance.getActiveAccount() ?? accounts[0] ?? null;

  const signIn = useCallback(async () => {
    await instance.loginRedirect({ scopes, prompt: "select_account" });
  }, [instance, scopes]);

  const getToken = useCallback(async () => {
    const active = instance.getActiveAccount() ?? instance.getAllAccounts()[0];
    if (!active) {
      await instance.loginRedirect({ scopes });
      throw new Error("Redirecting to sign-in");
    }
    try {
      const result = await instance.acquireTokenSilent({ scopes, account: active });
      return result.accessToken;
    } catch (error) {
      if (error instanceof InteractionRequiredAuthError) {
        await instance.acquireTokenRedirect({ scopes, account: active });
        throw new Error("Redirecting to sign-in", { cause: error });
      }
      throw error;
    }
  }, [instance, scopes]);

  const reauthenticate = useCallback(() => {
    const active = instance.getActiveAccount() ?? undefined;
    void instance
      .acquireTokenSilent({ scopes, account: active, forceRefresh: true })
      .catch(() => instance.acquireTokenRedirect({ scopes, account: active }));
  }, [instance, scopes]);

  const signOut = useCallback(() => {
    void instance.logoutRedirect({ account: instance.getActiveAccount() ?? undefined });
  }, [instance]);

  const value = useMemo<AuthState>(
    () => ({
      mode: "entra",
      isAuthenticated,
      isBusy: inProgress !== InteractionStatus.None,
      userLabel: account?.name ?? account?.username ?? null,
      signIn,
      signOut,
      getToken,
      reauthenticate,
    }),
    [isAuthenticated, inProgress, account, signIn, signOut, getToken, reauthenticate],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
