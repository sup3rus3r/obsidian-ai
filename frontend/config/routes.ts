
export type UserRole = 'admin' | 'user';

export interface RouteConfig {
  path        : string;
  label       : string;
  allowedRoles: UserRole[];
  description?: string;
}

export const Routes = {
  HOME        : '/',
  LOGIN       : '/login',
  REGISTER    : '/register',

  DASHBOARD   : '/home',
  ADMIN_PANEL : '/admin',
  GUEST_PAGE  : '/guest',
  PLAYGROUND  : '/playground',
  SESSIONS    : '/sessions',
  KNOWLEDGE   : '/knowledge',
  SETTINGS    : '/settings',
} as const;


export const ProtectedRoutes: RouteConfig[] = [
  {
    path: Routes.DASHBOARD,
    label: 'Dashboard',
    allowedRoles: ['admin', 'user'],
    description: 'Main dashboard - accessible to all authenticated users',
  },
  {
    path: Routes.ADMIN_PANEL,
    label: 'Admin Panel',
    allowedRoles: ['admin'],
    description: 'Admin only - manage users and settings',
  },
  {
    path: Routes.GUEST_PAGE,
    label: 'Guest Page',
    allowedRoles: ['user', 'admin'],
    description: 'Accessible to users and admins',
  },
  {
    path: Routes.PLAYGROUND,
    label: 'Playground',
    allowedRoles: ['admin', 'user'],
    description: 'Obsidian AI Playground - chat with AI agents',
  },
  {
    path: Routes.SESSIONS,
    label: 'Sessions',
    allowedRoles: ['admin', 'user'],
    description: 'View and manage all chat sessions',
  },
  {
    path: Routes.KNOWLEDGE,
    label: 'Knowledge',
    allowedRoles: ['admin', 'user'],
    description: 'Knowledge bases for agent RAG',
  },
  {
    path: Routes.SETTINGS,
    label: 'Settings',
    allowedRoles: ['admin', 'user'],
    description: 'Application settings and preferences',
  },
];


export function hasAccess(userRole: string | undefined, allowedRoles: UserRole[]): boolean {
  if (!userRole) return false;
  return allowedRoles.includes(userRole as UserRole);
}


export function getAccessibleRoutes(userRole: string | undefined): RouteConfig[] {
  if (!userRole) return [];
  return ProtectedRoutes.filter(route => hasAccess(userRole, route.allowedRoles));
}


export function canAccessPath(userRole: string | undefined, path: string): boolean {
  const route = ProtectedRoutes.find(r => r.path === path);
  if (!route) return true;
  return hasAccess(userRole, route.allowedRoles);
}
