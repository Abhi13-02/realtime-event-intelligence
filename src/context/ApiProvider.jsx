import { useEffect, useState } from "react"; // 1. Add useState
import { useAuth } from "@clerk/clerk-react";
import { apiClient } from "../services/apiClient";

export default function ApiProvider({ children }) {
  const { getToken } = useAuth();
  // 2. Add a 'ready' state
  const [isReady, setIsReady] = useState(false);

  useEffect(() => {
    const requestInterceptor = apiClient.interceptors.request.use(
      async (config) => {
        const token = await getToken();
        console.log("Attaching token to request:", token);
        if (token) {
          config.headers.Authorization = `Bearer ${token}`;
        }
        return config;
      },
      (error) => Promise.reject(error),
    );

    // 3. Interceptor is now registered
    setIsReady(true);

    return () => {
      apiClient.interceptors.request.eject(requestInterceptor);
    };
  }, [getToken]);

  // 4. If not ready, return null (or a Loading spinner)
  // This prevents HomeFeed from calling the API too early
  if (!isReady) {
    return null;
  }

  return children;
}
