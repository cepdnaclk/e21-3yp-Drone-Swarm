const configuredBaseUrl = import.meta.env.VITE_API_BASE_URL?.trim();

// Packaged builds use Flask's origin. Developers can either use Vite's proxy
// (the default) or set VITE_API_BASE_URL when the API runs somewhere else.
export const API_BASE_URL = (
  configuredBaseUrl || window.location.origin
).replace(/\/+$/, "");

export const backendUrl = (path: string) =>
  `${API_BASE_URL}${path.startsWith("/") ? path : `/${path}`}`;
