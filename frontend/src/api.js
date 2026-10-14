export class ApiError extends Error {
  constructor(message, status = 0) {
    super(message);
    this.status = status;
  }
}

export function csrfToken() {
  return document.querySelector('meta[name="csrf-token"]')?.content || "";
}

export async function api(
  path,
  { method = "GET", body, signal, timeout = 20000 } = {},
) {
  const controller = new AbortController();
  const abort = () => controller.abort();
  if (signal?.aborted) abort();
  signal?.addEventListener("abort", abort, { once: true });
  const timer = setTimeout(abort, timeout);
  try {
    const response = await fetch(path, {
      method,
      credentials: "same-origin",
      cache: "no-store",
      signal: controller.signal,
      headers: {
        Accept: "application/json",
        ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
        ...(method !== "GET" ? { "X-CSRF-Token": csrfToken() } : {}),
      },
      ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
    });
    if (
      response.status === 401 ||
      (response.redirected &&
        new URL(response.url).pathname.startsWith("/login"))
    ) {
      throw new ApiError("Your session has expired. Sign in again.", 401);
    }
    if (
      !(response.headers.get("content-type") || "").includes("application/json")
    ) {
      throw new ApiError(
        "The server returned an unexpected response. Please try again.",
        response.status,
      );
    }
    const data = await response.json();
    if (!response.ok || data?.success === false || data?.error)
      throw new ApiError(
        data.error || data.message || "Request failed",
        response.status,
      );
    return data;
  } catch (error) {
    if (error.name === "AbortError" && !signal?.aborted)
      throw new ApiError(
        "The request timed out. Check the connection before retrying.",
      );
    throw error;
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener("abort", abort);
  }
}

export function uploadBackup(file, onProgress, signal) {
  if (!/\.tar\.gz(\.enc)?$/i.test(file.name))
    return Promise.reject(new Error("Choose a .tar.gz or .tar.gz.enc backup."));
  if (!file.size || file.size > 128 * 1024 * 1024)
    return Promise.reject(
      new Error("Choose a non-empty backup smaller than 128 MiB."),
    );
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    const abort = () => xhr.abort();
    const finish = (fn, value) => {
      signal?.removeEventListener("abort", abort);
      fn(value);
    };
    xhr.open("POST", "/api/system/backups/upload");
    xhr.timeout = 180000;
    xhr.setRequestHeader("X-CSRF-Token", csrfToken());
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable)
        onProgress(Math.round((e.loaded / e.total) * 100));
    };
    xhr.onload = () => {
      try {
        const data = JSON.parse(xhr.responseText);
        if (xhr.status >= 200 && xhr.status < 300) finish(resolve, data);
        else
          finish(
            reject,
            new ApiError(data.error || "Upload failed", xhr.status),
          );
      } catch {
        finish(
          reject,
          new Error("Upload failed. Check your session and connection."),
        );
      }
    };
    xhr.onerror = () =>
      finish(reject, new Error("Connection lost during upload."));
    xhr.ontimeout = () => finish(reject, new Error("Upload timed out."));
    xhr.onabort = () => finish(reject, new Error("Upload cancelled."));
    signal?.addEventListener("abort", abort, { once: true });
    if (signal?.aborted) {
      finish(reject, new Error("Upload cancelled."));
      return;
    }
    const data = new FormData();
    data.append("file", file);
    xhr.send(data);
  });
}
