import { AppRoutes }    from './routes'
import { API_HEALTH, USER_DETAILS, TOGGLE_ROLE_RESPONSE }   from '@/types/os'

export const GetAPIStatus = async (accessToken?: string): Promise<API_HEALTH> => {
    const url = AppRoutes.GetHealth()
    try {
        const headers: HeadersInit = {}
        if (accessToken) {
            headers['Authorization'] = `Bearer ${accessToken}`
        }
        const response = await fetch(url, {
            method: 'GET',
            headers
        })
        if(!response.ok){
            console.log(`Failed to fetch server health status: ${response.statusText}`)
            return {status : "not okay"}
        }
        const data = await response.json()
        return data
    }catch{
        console.log("Error: Not Able to check server health")
        return {status : "not okay"}
    }
}

export const GetUserInfo = async (accessToken?: string): Promise<USER_DETAILS> => {
    const url = AppRoutes.GetUserDetails()
    try {
        const headers: HeadersInit = {}
        if (accessToken) {
            headers['Authorization'] = `Bearer ${accessToken}`
        }
        const response = await fetch(url, {
            method: 'GET',
            headers
        })
        if(!response.ok){
            console.log(`Failed to fetch user details: ${response.statusText}`)
            return {id: "", username: "no user information", email: "", role: "", auth_type: ""}
        }
        const data = await response.json()
        console.log(data)
        return data
    }catch{
        console.log("Error: Not Able to fetch user details")
        return {id: "", username: "no user information", email: "", role: "", auth_type: ""}
    }
}

export const ToggleUserRole = async (accessToken?: string): Promise<TOGGLE_ROLE_RESPONSE | null> => {
    const url = AppRoutes.ToggleRole()
    try {
        const headers: HeadersInit = {
            'Content-Type': 'application/json'
        }
        if (accessToken) {
            headers['Authorization'] = `Bearer ${accessToken}`
        }
        const response = await fetch(url, {
            method: 'PUT',
            headers
        })
        if(!response.ok){
            console.log(`Failed to toggle role: ${response.statusText}`)
            return null
        }
        const data = await response.json()
        return data
    }catch(error){
        console.log("Error: Not able to toggle role", error)
        return null
    }
}
