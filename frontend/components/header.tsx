"use client";
import { useScroll } from "@/hooks/use-scroll";
import Image from "next/image";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { MobileNav } from "@/components/mobile-nav";
import { useRouter } from "next/navigation";
import { useSession, signOut } from "next-auth/react";
import { LogOut, SettingsIcon } from "lucide-react";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";

export const navLinks = [];

export function Header() {
	const router 	= useRouter()
	const { data: session } = useSession()
	const scrolled = useScroll(10);

	const handleLogout = () => {
		signOut({ callbackUrl: "/login" })
	}

	return (
		<header
			className={cn("sticky top-0 z-50 w-full border-transparent border-b", {
				"border-border bg-background/95 backdrop-blur-sm supports-backdrop-filter:bg-background/50":
					scrolled,
			})}
		>
			<nav className="flex h-14  items-center justify-between px-4">
				<div className="rounded-md p-2">
					<div className="relative w-25 md:w-35 lg:w-40  aspect-video cursor-pointer">
						<Image src={'/ackermans_logo.svg'} alt="logo" fill/>
					</div>
				</div>
				<div className="hidden items-center gap-3 md:flex">
					{session ? (
						<DropdownMenu>
							<DropdownMenuTrigger asChild>
								<Button variant="ghost" size="icon" className="rounded-full">
									<Avatar className="h-8 w-8">
										<AvatarFallback className="bg-primary/10 text-primary font-semibold">
											{session.user?.email?.[0].toUpperCase() || "U"}
										</AvatarFallback>
									</Avatar>
								</Button>
							</DropdownMenuTrigger>
							<DropdownMenuContent align="end" className="w-56">
								<div className="flex flex-col gap-2 px-2 py-1.5">
									<p className="text-xs font-medium text-muted-foreground">Signed in as</p>
									<p className="text-sm font-medium truncate">{session.user?.email}</p>
								</div>
								<DropdownMenuSeparator />
								<DropdownMenuItem asChild>
									<button className="w-full flex items-center gap-2 cursor-pointer" onClick={() => router.push("/playground")}>
										<SettingsIcon className="h-4 w-4" />
										<span>Go to Playground</span>
									</button>
								</DropdownMenuItem>
								<DropdownMenuSeparator />
								<DropdownMenuItem asChild>
									<button className="w-full flex items-center gap-2 cursor-pointer text-destructive" onClick={handleLogout}>
										<LogOut className="h-4 w-4" />
										<span>Sign Out</span>
									</button>
								</DropdownMenuItem>
							</DropdownMenuContent>
						</DropdownMenu>
					) : (
						<>
							<Button variant={'outline'} className="cursor-pointer text-primary font-semibold px-12 rounded-sm" onClick={()=>{
								router.push('/login')
							}}>Sign In</Button>
							<Button variant={'ghost'} className="cursor-pointer text-primary font-semibold px-12 rounded-sm"onClick={()=>{
								router.push('/register')
							}}>Get Started</Button>
						</>
					)}
				</div>
				<MobileNav />
			</nav>
		</header>
	);
}
