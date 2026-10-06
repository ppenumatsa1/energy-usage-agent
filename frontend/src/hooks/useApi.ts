import { useMemo } from "react";
import { createApiClient, type ApiClient } from "../api/client";
import { useAuth } from "../auth/context";

export function useApi(): ApiClient {
  const { getToken, reauthenticate } = useAuth();
  return useMemo(
    () => createApiClient({ getToken, onUnauthorized: reauthenticate }),
    [getToken, reauthenticate],
  );
}
