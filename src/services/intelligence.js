// src/services/intelligence.js
import { apiClient } from "./apiClient";

export const intelligenceApi = {
  // GET /topics/{topic_id}/intelligence
  // Fetches the current sub-theme clusters, volume, and sentiment
  getTopicIntelligence: async (topicId) => {
    const response = await apiClient.get(`/topics/${topicId}/intelligence`);
    return response.data;
  },

  // GET /topics/{topic_id}/intelligence/timeline
  // Fetches the historical snapshot data for a specific sub-theme (for charts)
  getTimeline: async (topicId, subThemeId, limit = 20) => {
    const response = await apiClient.get(
      `/topics/${topicId}/intelligence/timeline`,
      {
        params: { sub_theme_id: subThemeId, limit },
      },
    );
    return response.data;
  },

  // GET /intelligence-alerts
  // Fetches the specialized intelligence alerts (emerging trends, anomalies)
  getIntelligenceAlerts: async (
    page = 1,
    limit = 20,
    topicId = null,
    alertType = null,
  ) => {
    const params = { page, limit };
    if (topicId) params.topic_id = topicId;
    if (alertType) params.alert_type = alertType;

    const response = await apiClient.get("/intelligence-alerts", { params });
    return response.data;
  },

  // GET /topics/{topic_id}/intelligence/sub-themes/{sub_theme_id}/articles
  // Fetches the articles that belong to a specific sub-theme
  getSubThemeArticles: async (topicId, subThemeId, page = 1, limit = 20) => {
    const response = await apiClient.get(
      `/topics/${topicId}/intelligence/sub-themes/${subThemeId}/articles`,
      { params: { page, limit } }
    );
    return response.data;
  },
};
