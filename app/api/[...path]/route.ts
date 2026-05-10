import { NextRequest } from "next/server";
import { mapApiPath, proxyToBackend } from "../../../lib/backendProxy";

type ApiRouteContext = {
  params: Promise<{ path?: string[] }>;
};

async function handleApiRequest(request: NextRequest, context: ApiRouteContext) {
  const { path = [] } = await context.params;
  return proxyToBackend(request, mapApiPath(path));
}

export const GET = handleApiRequest;
export const POST = handleApiRequest;
export const PUT = handleApiRequest;
export const PATCH = handleApiRequest;
export const DELETE = handleApiRequest;
