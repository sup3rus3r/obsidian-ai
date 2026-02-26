export interface API_HEALTH {
    status: string;
    authenticated_as?: string;
    auth_type?: string;
}

export interface USER_DETAILS {
    id: string;
    username: string;
    email: string;
    role: string;
    auth_type: string;
    permissions?: Record<string, boolean>;
}

export interface TOGGLE_ROLE_RESPONSE {
    access_token: string;
    token_type: string;
    expires_in: number;
    user: {
        id: string;
        username: string;
        email: string;
        role: string;
    };
    message: string;
}