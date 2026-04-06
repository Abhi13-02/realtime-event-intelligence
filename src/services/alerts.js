// src/services/alerts.js
import { apiClient } from "./apiClient";

export const alertsApi = {
  // Fetch alerts with optional pagination and topic filtering
  getAlerts: async (page = 1, limit = 20, topicId = null) => {
    const params = { page, limit };
    if (topicId) params.topic_id = topicId;

    const response = await apiClient.get("/alerts", { params });
    return response.data;
  },

  // Delete a specific alert
  deleteAlert: async (alertId) => {
    const response = await apiClient.delete(`/alerts/${alertId}`);
    return response.data;
  },
};
