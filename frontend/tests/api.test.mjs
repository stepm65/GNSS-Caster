import { test, afterEach } from "node:test";
import assert from "node:assert/strict";
import { api, uploadBackup } from "../src/api.js";
const originalFetch = globalThis.fetch;
globalThis.document = { querySelector: () => ({ content: "csrf-test" }) };
afterEach(() => {
  globalThis.fetch = originalFetch;
});

test("mutations carry CSRF and serialize booleans without losing them", async () => {
  let captured;
  globalThis.fetch = async (path, options) => {
    captured = { path, ...options };
    return Response.json({ message: "saved" });
  };
  await api("/api/rtcm/settings/update", {
    method: "POST",
    body: { enabled: false },
  });
  assert.equal(captured.headers["X-CSRF-Token"], "csrf-test");
  assert.equal(captured.credentials, "same-origin");
  assert.equal(captured.body, '{"enabled":false}');
});
test("HTTP and logical failures preserve actionable server messages", async () => {
  globalThis.fetch = async () =>
    Response.json({ error: "Has mountpoints" }, { status: 409 });
  await assert.rejects(
    api("/api/base_stations/1/delete", { method: "POST" }),
    (e) => e.message === "Has mountpoints" && e.status === 409,
  );
  globalThis.fetch = async () =>
    Response.json({ success: false, message: "Receiver unreachable" });
  await assert.rejects(
    api("/api/bluetooth/connect", { method: "POST" }),
    /Receiver unreachable/,
  );
});
test("expired sessions and HTML errors are not parsed as valid data", async () => {
  globalThis.fetch = async () => Response.json({}, { status: 401 });
  await assert.rejects(api("/api/status"), (e) => e.status === 401);
  globalThis.fetch = async () =>
    new Response("<html>Bad gateway</html>", {
      status: 502,
      headers: { "content-type": "text/html" },
    });
  await assert.rejects(api("/api/status"), /unexpected response/);
});
test("caller cancellation is distinguishable from a timeout", async () => {
  globalThis.fetch = (_, { signal }) =>
    new Promise((_, reject) => {
      const fail = () => reject(new DOMException("Aborted", "AbortError"));
      if (signal.aborted) fail();
      else signal.addEventListener("abort", fail, { once: true });
    });
  const controller = new AbortController();
  controller.abort();
  await assert.rejects(
    api("/api/status", { signal: controller.signal }),
    (e) => e.name === "AbortError",
  );
  await assert.rejects(api("/api/status", { timeout: 5 }), /timed out/);
});
test("unsupported, empty and oversized backups never create an upload request", async () => {
  await assert.rejects(
    uploadBackup({ name: "file.zip", size: 100 }, () => {}),
    /Choose a/,
  );
  await assert.rejects(
    uploadBackup({ name: "file.tar.gz", size: 0 }, () => {}),
    /non-empty/,
  );
  await assert.rejects(
    uploadBackup(
      { name: "file.tar.gz.enc", size: 128 * 1024 * 1024 + 1 },
      () => {},
    ),
    /128 MiB/,
  );
});
