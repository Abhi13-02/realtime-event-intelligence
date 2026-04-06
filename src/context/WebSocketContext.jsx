// src/context/WebSocketContext.jsx
import { createContext, useContext, useEffect, useState, useRef } from 'react';
import { wsApi } from '../services/websocket';

const WebSocketContext = createContext(null);

export function WebSocketProvider({ children }) {
  const [latestAlert, setLatestAlert] = useState(null);
  const [isConnected, setIsConnected] = useState(false);
  const wsRef = useRef(null);

  useEffect(() => {
    let isMounted = true;

    const connectWebSocket = async () => {
      try {
        // 1. Get the ticket
        const ticket = await wsApi.getTicket();
        
        // 2. Connect to the WebSocket using the ticket
        // Note: Change localhost:8000 to your actual backend URL when deploying
        const wsUrl = `ws://localhost:8000/v1/ws?ticket=${ticket}`;
        const ws = new WebSocket(wsUrl);
        wsRef.current = ws;

        ws.onopen = () => {
          if (isMounted) setIsConnected(true);
          console.log("🟢 WebSocket Connected");
        };

        ws.onmessage = (event) => {
          const data = JSON.parse(event.data);
          console.log("📥 New Live Alert Received:", data);
          if (isMounted) setLatestAlert(data);
        };

        ws.onclose = () => {
          if (isMounted) setIsConnected(false);
          console.log("🔴 WebSocket Disconnected");
          // Optional: You could add a setTimeout here to attempt auto-reconnect
        };

      } catch (error) {
        console.error("Failed to connect to WebSocket:", error);
      }
    };

    connectWebSocket();

    // Cleanup when the app unmounts
    return () => {
      isMounted = false;
      if (wsRef.current) {
        wsRef.current.close();
      }
    };
  }, []);

  return (
    <WebSocketContext.Provider value={{ latestAlert, isConnected }}>
      {children}
    </WebSocketContext.Provider>
  );
}

// Custom hook to make it easy to use in any component
export const useWebSocket = () => useContext(WebSocketContext);