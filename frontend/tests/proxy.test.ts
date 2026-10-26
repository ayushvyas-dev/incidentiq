import assert from "node:assert/strict";
import test from "node:test";
import { NextRequest } from "next/server.js";
import { proxy } from "../src/app/api/backend/[...path]/route.ts";

test("proxy restricts paths and methods before contacting backend", async () => {
  const originalFetch = globalThis.fetch;
  let calls = 0;
  globalThis.fetch = async () => { calls++; return new Response("{}", { status: 200 }); };
  process.env.INCIDENTIQ_API_URL = "http://api.internal";
  process.env.INCIDENTIQ_READONLY_API_KEY = "test-read";
  try {
    const denied = await proxy(new NextRequest("http://localhost/api/backend/api/v1/admin"), ["api", "v1", "admin"]);
    assert.equal(denied.status, 404);
    const health = await proxy(new NextRequest("http://localhost/api/backend/health/live"), ["health", "live"]);
    assert.equal(health.status, 200);
    assert.equal(calls, 1);
  } finally { globalThis.fetch = originalFetch; }
});

test("proxy does not expose upstream validation input/context", async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => Response.json({ detail: [{ loc: ["body", "title"], msg: "Too short", input: "sensitive", ctx: { secret: "hidden" } }] }, { status: 422 });
  process.env.INCIDENTIQ_API_URL = "http://api.internal";
  process.env.INCIDENTIQ_API_KEY = "test-write";
  try {
    const response = await proxy(new NextRequest("http://localhost/api/backend/api/v1/incidents/analyze", { method: "POST", body: "{}" }), ["api", "v1", "incidents", "analyze"]);
    const body = await response.json();
    assert.deepEqual(body, { error: "Request validation failed", fields: { title: "Too short" } });
    assert.equal(response.status, 422);
  } finally { globalThis.fetch = originalFetch; }
});

test("proxy selects read-only credentials for GET and preserves multipart uploads", async () => {
  const originalFetch = globalThis.fetch;
  const previous = { read: process.env.INCIDENTIQ_READONLY_API_KEY, write: process.env.INCIDENTIQ_API_KEY };
  process.env.INCIDENTIQ_API_URL = "http://api.internal";
  process.env.INCIDENTIQ_READONLY_API_KEY = "read-key";
  process.env.INCIDENTIQ_API_KEY = "write-key";
  try {
    globalThis.fetch = async (_url, init) => { assert.equal(new Headers(init?.headers).get("authorization"), "Bearer read-key"); return Response.json({ items: [] }); };
    const list = await proxy(new NextRequest("http://localhost/api/backend/api/v1/documents"), ["api", "v1", "documents"]);
    assert.equal(list.status, 200);
    const form = new FormData(); form.set("file", new Blob(["log"]), "app.log"); form.set("source_type", "log");
    globalThis.fetch = async (_url, init) => { assert.equal(new Headers(init?.headers).get("authorization"), "Bearer write-key"); assert.ok(init?.body instanceof FormData); return Response.json({ status: "queued" }, { status: 202 }); };
    const upload = await proxy(new NextRequest("http://localhost/api/backend/api/v1/documents", { method: "POST", body: form }), ["api", "v1", "documents"]);
    assert.equal(upload.status, 202);
  } finally {
    globalThis.fetch = originalFetch;
    if (previous.read === undefined) delete process.env.INCIDENTIQ_READONLY_API_KEY; else process.env.INCIDENTIQ_READONLY_API_KEY = previous.read;
    if (previous.write === undefined) delete process.env.INCIDENTIQ_API_KEY; else process.env.INCIDENTIQ_API_KEY = previous.write;
  }
});

test("proxy never substitutes the write key when the read-only key is missing", async () => {
  const previous = { read: process.env.INCIDENTIQ_READONLY_API_KEY, write: process.env.INCIDENTIQ_API_KEY };
  process.env.INCIDENTIQ_API_URL = "http://api.internal";
  delete process.env.INCIDENTIQ_READONLY_API_KEY;
  process.env.INCIDENTIQ_API_KEY = "write-only-test-key";
  try {
    const response = await proxy(new NextRequest("http://localhost/api/backend/api/v1/documents"), ["api", "v1", "documents"]);
    assert.equal(response.status, 503);
  } finally {
    if (previous.read === undefined) delete process.env.INCIDENTIQ_READONLY_API_KEY; else process.env.INCIDENTIQ_READONLY_API_KEY = previous.read;
    if (previous.write === undefined) delete process.env.INCIDENTIQ_API_KEY; else process.env.INCIDENTIQ_API_KEY = previous.write;
  }
});
