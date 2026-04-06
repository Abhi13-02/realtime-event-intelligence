// src/services/topics.js
import { apiClient } from './apiClient';

export const topicsApi = {
  // GET /topics
  getTopics: async (page = 1, limit = 20) => {
    const response = await apiClient.get('/topics', { params: { page, limit } });
    return response.data;
  },

  // POST /topics
  createTopic: async (payload) => {
    const response = await apiClient.post('/topics', payload);
    return response.data;
  },

  // GET /topics/{topic_id}
  getTopic: async (id) => {
    const response = await apiClient.get(`/topics/${id}`);
    return response.data;
  },

  // PATCH /topics/{topic_id}
  updateTopic: async (id, payload) => {
    const response = await apiClient.patch(`/topics/${id}`, payload);
    return response.data;
  },

  // DELETE /topics/{topic_id}
  deleteTopic: async (id) => {
    const response = await apiClient.delete(`/topics/${id}`);
    return response.data;
  },

  // PUT /topics/{topic_id}/channels
  updateChannels: async (id, channels) => {
    const response = await apiClient.put(`/topics/${id}/channels`, { root: channels });
    return response.data;
  }
};