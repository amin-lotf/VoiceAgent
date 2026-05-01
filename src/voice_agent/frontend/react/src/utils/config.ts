export const appConfig = {
  apiBaseUrl: (import.meta.env.VITE_API_BASE_URL || "http://localhost:8000/api/v1").replace(/\/$/, ""),
  wsBaseUrl: (import.meta.env.VITE_WS_URL || "ws://localhost:8000/api/v1/live/ws").replace(/\/$/, ""),
};
