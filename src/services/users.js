// src/services/users.js
import { apiClient } from "./apiClient";

export const usersApi = {
  // GET /users/me
  getMe: async () => {
    const response = await apiClient.get("/users/me");
    return response.data;
  },

  // PATCH /users/me
  updateMe: async (payload) => {
    // payload should only contain { name } or { phone_number } or both
    const response = await apiClient.patch("/users/me", payload);
    return response.data;
  },
};
