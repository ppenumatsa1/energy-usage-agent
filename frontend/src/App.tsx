import type { IPublicClientApplication } from "@azure/msal-browser";
import { DevAuthProvider } from "./auth/DevAuthProvider";
import { DevSignIn } from "./auth/DevSignIn";
import { EntraAuthProvider } from "./auth/EntraAuthProvider";
import { SignInScreen } from "./auth/SignInScreen";
import { useAuth } from "./auth/context";
import { AppHeader } from "./components/AppHeader";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { Workspace } from "./components/Workspace";
import type { RuntimeConfig } from "./types/config";

export function Shell() {
  const auth = useAuth();
  if (!auth.isAuthenticated) {
    return (
      <>
        <AppHeader />
        {auth.mode === "entra" ? <SignInScreen /> : <DevSignIn />}
      </>
    );
  }
  return <Workspace />;
}

interface AppProps {
  config: RuntimeConfig;
  msalInstance?: IPublicClientApplication;
}

export function App({ config, msalInstance }: AppProps) {
  return (
    <ErrorBoundary>
      {config.authMode === "entra" && msalInstance ? (
        <EntraAuthProvider instance={msalInstance} config={config}>
          <Shell />
        </EntraAuthProvider>
      ) : (
        <DevAuthProvider>
          <Shell />
        </DevAuthProvider>
      )}
    </ErrorBoundary>
  );
}

export default App;
