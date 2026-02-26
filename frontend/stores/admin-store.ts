import { create } from "zustand"
import { apiClient } from "@/lib/api-client"
import type { AdminUser, CreateUserRequest, UpdateUserRequest } from "@/types/playground"

interface AdminState {
  users: AdminUser[]
  isLoading: boolean

  fetchUsers: () => Promise<void>
  createUser: (data: CreateUserRequest) => Promise<AdminUser>
  updateUser: (id: string, data: UpdateUserRequest) => Promise<void>
  deleteUser: (id: string) => Promise<void>
}

export const useAdminStore = create<AdminState>((set) => ({
  users: [],
  isLoading: false,

  fetchUsers: async () => {
    set({ isLoading: true })
    try {
      const users = await apiClient.listUsers()
      set({ users, isLoading: false })
    } catch (error) {
      console.error("Failed to fetch users:", error)
      set({ isLoading: false })
    }
  },

  createUser: async (data: CreateUserRequest) => {
    const newUser = await apiClient.createUser(data)
    set((s) => ({ users: [...s.users, newUser] }))
    return newUser
  },

  updateUser: async (id: string, data: UpdateUserRequest) => {
    const updated = await apiClient.updateUser(id, data)
    set((s) => ({
      users: s.users.map((u) => (u.id === id ? updated : u)),
    }))
  },

  deleteUser: async (id: string) => {
    await apiClient.deleteUser(id)
    set((s) => ({ users: s.users.filter((u) => u.id !== id) }))
  },
}))
