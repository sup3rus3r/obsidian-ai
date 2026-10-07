'use client'
import { useLayoutEffect } from "react";
import { useSession } from "next-auth/react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import Link from "next/link";
import { Routes, hasAccess } from "@/config/routes";

export default function GuestPage() {
  const { data: session, status } = useSession();
  const router = useRouter();
  const userRole = session?.user?.role ?? 'guest';

  useLayoutEffect(() => {
    if (status === "unauthenticated") {
      router.push(Routes.LOGIN);
    }

    if (status === "authenticated" && !hasAccess(userRole, ['guest', 'admin'])) {
      router.push(Routes.DASHBOARD);
    }
  }, [status, router, userRole]);

  if (status === "loading") {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background">
        <p className="text-sm text-muted-foreground">Loading...</p>
      </div>
    );
  }

  if (status === "unauthenticated" || !hasAccess(userRole, ['guest', 'admin'])) {
    return null;
  }

  return (
    <div className="h-full overflow-y-auto p-8 w-full flex items-center justify-center">
      <main className="flex w-full max-w-3xl flex-col items-center gap-8 py-32 px-16">
        <div className="text-center">
          <h1 className="text-2xl font-medium tracking-[-0.016em]">Guest Page</h1>
          <p className="mt-2 text-sm text-muted-foreground">
            Welcome, {session?.user?.name ?? 'Guest'}!
          </p>
          <p className="mt-1 text-sm text-muted-foreground">
            Role: <span className="font-medium text-foreground">{userRole}</span>
          </p>
        </div>

        <div className="w-full rounded-lg border text-center p-6">
          <p className="text-sm text-muted-foreground">
            This page is accessible to users with guest or admin roles.
          </p>
        </div>

        <Link href={Routes.DASHBOARD}>
          <Button variant="outline" className="cursor-pointer">
            Back to Dashboard
          </Button>
        </Link>
      </main>
    </div>
  );
}
