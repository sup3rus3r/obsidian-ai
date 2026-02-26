import { NextResponse } from "next/server"
import type { NextRequest } from "next/server"
import { getToken } from "next-auth/jwt"

export async function proxy(req: NextRequest) {
  const token = await getToken({ req, secret: process.env.AUTH_SECRET })
  const isLoggedIn = !!token
  const { pathname } = req.nextUrl

  const isAuthPage = pathname === "/login" || pathname === "/register"
  const isLandingPage = pathname === "/"
  const isPublicRoute = isAuthPage || isLandingPage

  // Authenticated users visiting / or auth pages → redirect to /home
  if (isLoggedIn && (isLandingPage || isAuthPage)) {
    return NextResponse.redirect(new URL("/home", req.url))
  }

  // Unauthenticated users visiting protected routes → redirect to /login
  if (!isLoggedIn && !isPublicRoute) {
    return NextResponse.redirect(new URL("/login", req.url))
  }

  return NextResponse.next()
}

export const config = {
  matcher: [
    "/((?!api|_next/static|_next/image|favicon\\.ico|.*\\.(?:svg|png|jpg|jpeg|gif|webp)$).*)",
  ],
}
