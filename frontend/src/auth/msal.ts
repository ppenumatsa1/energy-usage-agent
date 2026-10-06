import { BrowserCacheLocation, PublicClientApplication } from "@azure/msal-browser";
import type { RuntimeConfig } from "../types/config";

/** Creates and initializes the MSAL instance and processes any pending redirect response. */
export async function createMsalInstance(config: RuntimeConfig): Promise<PublicClientApplication> {
  const instance = new PublicClientApplication({
    auth: {
      clientId: config.clientId,
      authority: config.authority,
      redirectUri: window.location.origin,
      postLogoutRedirectUri: window.location.origin,
    },
    cache: { cacheLocation: BrowserCacheLocation.SessionStorage },
  });
  await instance.initialize();
  const result = await instance.handleRedirectPromise();
  if (result?.account) {
    instance.setActiveAccount(result.account);
  } else if (!instance.getActiveAccount()) {
    const [first] = instance.getAllAccounts();
    if (first) instance.setActiveAccount(first);
  }
  return instance;
}
