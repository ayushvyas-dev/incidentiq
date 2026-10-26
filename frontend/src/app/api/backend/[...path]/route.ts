import { NextRequest, NextResponse } from "next/server.js";

const UUID = "[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}";
const routes: Array<[RegExp, string[]]> = [
  [/^health\/(live|ready)$/, ["GET"]],
  [/^api\/v1\/(documents|incidents|evaluations)$/, ["GET"]],
  [/^api\/v1\/documents$/, ["POST"]],
  [new RegExp(`^api/v1/documents/${UUID}$`), ["GET", "DELETE"]],
  [new RegExp(`^api/v1/jobs/${UUID}$`), ["GET"]],
  [/^api\/v1\/incidents\/analyze$/, ["POST"]],
  [new RegExp(`^api/v1/incidents/${UUID}$`), ["GET"]],
  [new RegExp(`^api/v1/incidents/${UUID}/runs$`), ["GET"]],
  [/^api\/v1\/search$/, ["POST"]],
  [/^api\/v1\/routing\/policies$/, ["GET"]],
  [new RegExp(`^api/v1/routing/decisions/${UUID}$`), ["GET"]],
  [/^api\/v1\/routing\/simulate$/, ["POST"]],
  [/^api\/v1\/evaluations$/, ["GET", "POST"]],
  [new RegExp(`^api/v1/evaluations/${UUID}$`), ["GET"]],
  [new RegExp(`^api/v1/evaluations/${UUID}/cases$`), ["GET"]],
  [/^api\/v1\/metrics\/summary$/, ["GET"]],
];

function allowed(path: string, method: string): boolean {
  return routes.some(([pattern, methods]) => pattern.test(path) && methods.includes(method));
}

function jsonResponse(body: unknown, status: number): NextResponse {
  return NextResponse.json(body, { status, headers: { "cache-control": "no-store" } });
}

function sanitizedValidation(body: unknown) {
  const detail = (body as { detail?: unknown } | null)?.detail;
  if (!Array.isArray(detail)) return { error: "Request validation failed" };
  const fields: Record<string, string> = {};
  for (const issue of detail) {
    if (issue && typeof issue === "object") {
      const item = issue as { loc?: unknown[]; msg?: unknown };
      const key = Array.isArray(item.loc) ? item.loc.filter((part) => part !== "body").join(".") : "request";
      if (key) fields[key] = typeof item.msg === "string" ? item.msg : "Invalid value";
    }
  }
  return { error: "Request validation failed", fields };
}

export async function proxy(request: NextRequest, segments: string[]): Promise<NextResponse> {
  const path = segments.join("/");
  const method = request.method.toUpperCase();
  if (!allowed(path, method)) return jsonResponse({ error: "Route not available" }, 404);
  const base = process.env.INCIDENTIQ_API_URL?.replace(/\/$/, "");
  const isHealth = path.startsWith("health/");
  const key = isHealth ? undefined : method === "GET" ? process.env.INCIDENTIQ_READONLY_API_KEY : process.env.INCIDENTIQ_API_KEY;
  if (!base || (!isHealth && !key)) return jsonResponse({ error: "Backend connection is not configured" }, 503);

  let body: BodyInit | undefined;
  const headers = new Headers();
  if (key) headers.set("authorization", `Bearer ${key}`);
  if (method !== "GET" && method !== "HEAD") {
    if (path === "api/v1/documents") {
      const maxMb = Number(process.env.FRONTEND_MAX_UPLOAD_MB || 4);
      const length = Number(request.headers.get("content-length") || 0);
      if (!Number.isFinite(maxMb) || maxMb <= 0) return jsonResponse({ error: "Upload limit is not configured correctly" }, 503);
      if (length > maxMb * 1024 * 1024 + 64 * 1024) return jsonResponse({ error: `Upload exceeds ${maxMb} MB` }, 413);
      body = await request.formData();
    } else {
      body = await request.text();
      headers.set("content-type", request.headers.get("content-type") || "application/json");
    }
  }
  const upstreamUrl = `${base}/${path}${request.nextUrl.search}`;
  try {
    const upstream = await fetch(upstreamUrl, { method, headers, body, cache: "no-store", signal: AbortSignal.timeout(30_000) });
    const text = await upstream.text();
    let payload: unknown;
    try { payload = text ? JSON.parse(text) : null; } catch { payload = { error: "Backend returned an invalid response" }; }
    if (upstream.status === 204) return new NextResponse(null, { status: 204, headers: { "cache-control": "no-store" } });
    if (upstream.status === 422) return jsonResponse(sanitizedValidation(payload), 422);
    if (upstream.status >= 500) return jsonResponse({ error: "Backend request failed" }, upstream.status);
    return jsonResponse(payload, upstream.status);
  } catch {
    return jsonResponse({ error: "Backend is unavailable" }, 502);
  }
}

export const GET = (request: NextRequest, context: { params: Promise<{ path: string[] }> }) => context.params.then(({ path }) => proxy(request, path));
export const POST = (request: NextRequest, context: { params: Promise<{ path: string[] }> }) => context.params.then(({ path }) => proxy(request, path));
export const DELETE = (request: NextRequest, context: { params: Promise<{ path: string[] }> }) => context.params.then(({ path }) => proxy(request, path));
