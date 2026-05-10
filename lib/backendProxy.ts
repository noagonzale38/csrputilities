import { NextRequest, NextResponse } from "next/server";

const DEFAULT_BACKEND_ORIGIN = "http://127.0.0.1:4000";
const DEFAULT_DASHBOARD_ORIGIN = "http://127.0.0.1:3000";
const STRIPPED_REQUEST_HEADERS = ["accept-encoding", "connection", "content-length", "host"];

function backendOrigin() {
  return (process.env.NEXT_PUBLIC_BACKEND_ORIGIN || DEFAULT_BACKEND_ORIGIN).replace(/\/+$/, "");
}

function dashboardOrigin() {
  return (process.env.DASHBOARD_PUBLIC_ORIGIN || DEFAULT_DASHBOARD_ORIGIN).replace(/\/+$/, "");
}

function joinPath(prefix: string, segments: string[]) {
  const suffix = segments.map((segment) => encodeURIComponent(segment)).join("/");
  return suffix ? `${prefix}/${suffix}` : prefix;
}

export function mapApiPath(path: string[]) {
  const [section, ...rest] = path;

  if (section === "login" && rest.length === 0) return "/login";
  if (section === "logout" && rest.length === 0) return "/logout";
  if (section === "auth") return joinPath("/auth", rest);
  if (section === "actions") return joinPath("/actions", rest);

  return joinPath("/api", path);
}

function requestHeaders(request: NextRequest, target: URL) {
  const headers = new Headers(request.headers);
  STRIPPED_REQUEST_HEADERS.forEach((header) => headers.delete(header));
  headers.set("x-forwarded-host", request.headers.get("host") || request.nextUrl.host);
  headers.set("x-forwarded-proto", request.nextUrl.protocol.replace(":", ""));
  headers.set("x-forwarded-port", request.nextUrl.port || (request.nextUrl.protocol === "https:" ? "443" : "80"));
  headers.set("x-forwarded-server", target.host);
  return headers;
}

function normalizeLocation(location: string | null, requestOrigin: string) {
  if (!location) return location;
  if (location.startsWith("/")) return `${requestOrigin}${location}`;

  try {
    const locationUrl = new URL(location);
    const sameAppOrigins = [backendOrigin(), dashboardOrigin()].map((origin) => new URL(origin).origin);
    if (sameAppOrigins.includes(locationUrl.origin)) {
      return `${requestOrigin}${locationUrl.pathname}${locationUrl.search}${locationUrl.hash}`;
    }
  } catch {
    return location;
  }

  return location;
}

export async function proxyToBackend(request: NextRequest, backendPath: string) {
  const target = new URL(backendPath, backendOrigin());
  target.search = request.nextUrl.search;

  try {
    const hasBody = request.method !== "GET" && request.method !== "HEAD";
    const response = await fetch(target, {
      method: request.method,
      headers: requestHeaders(request, target),
      body: hasBody ? await request.arrayBuffer() : undefined,
      redirect: "manual",
      cache: "no-store"
    });
    const headers = new Headers(response.headers);
    const location = normalizeLocation(headers.get("location"), request.nextUrl.origin);

    if (location) headers.set("location", location);

    return new NextResponse(response.status === 204 || response.status === 304 ? null : response.body, {
      status: response.status,
      headers
    });
  } catch {
    return NextResponse.json({ error: "Dashboard backend is unavailable." }, { status: 503 });
  }
}
