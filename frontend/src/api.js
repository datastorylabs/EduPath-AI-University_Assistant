const rawApiBase = import.meta.env.VITE_API_BASE_URL || "/api";

function normalizeApiBase(value) {
  const base = String(value).trim();
  if (!base || base.startsWith("//")) {
    throw new Error("VITE_API_BASE_URL must be a same-origin path or an explicit HTTP(S) URL.");
  }

  if (base.startsWith("/")) {
    return base.replace(/\/+$/, "");
  }

  let url;
  try {
    url = new URL(base);
  } catch {
    throw new Error("VITE_API_BASE_URL is not a valid URL.");
  }

  if (url.protocol !== "https:" && url.protocol !== "http:") {
    throw new Error("The API URL must use HTTP or HTTPS.");
  }

  const localHost = url.hostname === "localhost" || url.hostname === "127.0.0.1";
  if (import.meta.env.PROD && url.protocol !== "https:" && !localHost) {
    throw new Error("A production API URL must use HTTPS.");
  }

  return url.href.replace(/\/+$/, "");
}

const API_BASE = normalizeApiBase(rawApiBase);

export class ApiError extends Error {
  constructor(message, status = 0) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

let csrfBootstrapPromise = null;

// StrictMode can mount the bootstrap effect twice in development. Share a
// single CSRF request so concurrent responses cannot overwrite each other's cookie.
export function bootstrapCsrf() {
  if (!csrfBootstrapPromise) {
    csrfBootstrapPromise = apiRequest("/auth/csrf").finally(() => {
      csrfBootstrapPromise = null;
    });
  }
  return csrfBootstrapPromise;
}

function safeErrorMessage(payload, status) {
  if (payload && typeof payload.detail === "string" && payload.detail.length < 260) {
    return payload.detail;
  }
  if (status === 401) return "Your session has expired. Please sign in again.";
  if (status === 403) return "The request could not be verified. Refresh the page and try again.";
  if (status === 404) return "That record was not found or is not available to this account.";
  if (status === 422) return "Please check the submitted fields and try again.";
  if (status >= 500) return "EduPath encountered a server issue. Please try again.";
  return "The request could not be completed.";
}

export async function apiRequest(path, options = {}) {
  const method = (options.method || "GET").toUpperCase();
  const headers = new Headers(options.headers || {});
  const hasBody = options.body !== undefined && options.body !== null;

  if (hasBody) headers.set("Content-Type", "application/json");
  if (options.csrfToken && !["GET", "HEAD", "OPTIONS"].includes(method)) {
    headers.set("X-CSRF-Token", options.csrfToken);
  }

  let response;
  try {
    response = await fetch(API_BASE + path, {
      method,
      headers,
      body: hasBody ? JSON.stringify(options.body) : undefined,
      credentials: "include",
      cache: "no-store",
      redirect: "error",
      signal: options.signal,
    });
  } catch {
    throw new ApiError("EduPath could not reach the API. Start the backend and refresh this page.", 0);
  }

  if (response.status === 204) {
    if (!response.ok) throw new ApiError("The request could not be completed.", response.status);
    return null;
  }

  let payload = null;
  const responseText = await response.text();
  if (responseText) {
    try {
      payload = JSON.parse(responseText);
    } catch {
      payload = null;
    }
  }

  if (!response.ok) {
    throw new ApiError(safeErrorMessage(payload, response.status), response.status);
  }

  return payload;
}

export function safeHttpUrl(value) {
  if (typeof value !== "string" || value.length > 2048) return null;
  try {
    const url = new URL(value);
    if (url.protocol !== "https:" && url.protocol !== "http:") return null;
    return url.href;
  } catch {
    return null;
  }
}
