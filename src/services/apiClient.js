// src/services/apiClient.js
import axios from "axios";

// Create a central axios instance
export const apiClient = axios.create({
  // Point this to wherever your FastAPI backend is running
  baseURL: "http://localhost:8000/v1",
  headers: {
    "Content-Type": "application/json",
  },
});

// We can add interceptors here later if we need to attach auth tokens
// from NextAuth before every request!
