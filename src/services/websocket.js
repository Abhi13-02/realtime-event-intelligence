// src/services/websocket.js
import { apiClient } from "./apiClient";

export const wsApi = {
  getTicket: async () => {
    // Hits POST /ws/ticket to get the one-time use UUID
    const response = await apiClient.post("/ws/ticket");
    return response.data.ticket;
  },
};
