"use client";

// WebSocket context — fetches a one-time ticket via the backend proxy, then
// opens the socket straight to FastAPI (the ticket is the auth).

import {
  createContext,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { api } from "./api";
import type { Alert } from "./types";

interface WsContextValue {
  latestAlert: Alert | null;
  isConnected: boolean;
}

const WsContext = createContext<WsContextValue>({
  latestAlert: null,
  isConnected: false,
});

export function WebSocketProvider({ children }: { children: ReactNode }) {
  const [latestAlert, setLatestAlert] = useState<Alert | null>(null);
  const [isConnected, setIsConnected] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    let mounted = true;

    const connect = async () => {
      try {
        const { ticket } = await api.getWsTicket();
        if (!mounted) return;
        // Explicit NEXT_PUBLIC_WS_URL wins (local dev hits FastAPI directly);
        // otherwise derive from the page origin so the same build works
        // behind any reverse proxy / tunnel that forwards /v1/ws.
        const base =
          process.env.NEXT_PUBLIC_WS_URL ??
          `${window.location.protocol === "https:" ? "wss" : "ws"}://${window.location.host}/v1`;
        const ws = new WebSocket(`${base}/ws?ticket=${ticket}`);
        wsRef.current = ws;

        ws.onopen = () => mounted && setIsConnected(true);
        ws.onmessage = (event) => {
          try {
            const payload = JSON.parse(event.data);
            if (payload.event === "new_alert" && mounted) {
              setLatestAlert(payload.data);
            }
          } catch {
            // ignore malformed frames
          }
        };
        ws.onclose = () => mounted && setIsConnected(false);
      } catch {
        if (mounted) setIsConnected(false);
      }
    };

    connect();
    return () => {
      mounted = false;
      wsRef.current?.close();
    };
  }, []);

  return (
    <WsContext.Provider value={{ latestAlert, isConnected }}>
      {children}
    </WsContext.Provider>
  );
}

export const useWebSocket = () => useContext(WsContext);
