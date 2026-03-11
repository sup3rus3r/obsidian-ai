import { getToken } from "next-auth/jwt"
import type { NextRequest } from "next/server"

const BACKEND_URL = process.env.BACKEND_URL || "http://localhost:8001"

export async function GET(
  req: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params
  const token = await getToken({ req, secret: process.env.AUTH_SECRET })
  if (!token) {
    return new Response("Unauthorized", { status: 401 })
  }

  const accessToken = (token as any).accessToken as string
  const backendUrl = `${BACKEND_URL}/wa/channels/${id}/qr?token=${encodeURIComponent(accessToken)}`

  const backendResp = await fetch(backendUrl, {
    headers: { Accept: "text/event-stream" },
    // @ts-ignore — Node 18 fetch supports this
    cache: "no-store",
  })

  if (!backendResp.ok || !backendResp.body) {
    return new Response("Failed to connect to backend", { status: 502 })
  }

  return new Response(backendResp.body, {
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache",
      "X-Accel-Buffering": "no",
      Connection: "keep-alive",
    },
  })
}
