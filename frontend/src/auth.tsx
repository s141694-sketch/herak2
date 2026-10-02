import { createContext, type ReactNode, useCallback, useContext, useEffect, useMemo, useState } from 'react'

import { api, ApiError, type SessionPayload } from './api'

interface AuthState {
  /** undefined while the first /me call is in flight, null when signed out. */
  session: SessionPayload | null | undefined
  login: (email: string, password: string) => Promise<SessionPayload>
  logout: () => Promise<void>
  switchOrganization: (organizationId: number) => Promise<void>
}

const AuthContext = createContext<AuthState | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<SessionPayload | null | undefined>(undefined)

  useEffect(() => {
    api.me().then(setSession, (error: unknown) => {
      if (error instanceof ApiError && (error.status === 401 || error.status === 403)) setSession(null)
      else setSession(null)
    })
  }, [])

  const login = useCallback(async (email: string, password: string) => {
    const payload = await api.login(email, password)
    setSession(payload)
    return payload
  }, [])

  const logout = useCallback(async () => {
    await api.logout()
    setSession(null)
  }, [])

  const switchOrganization = useCallback(async (organizationId: number) => {
    setSession(await api.switchOrganization(organizationId))
  }, [])

  const value = useMemo(() => ({ session, login, logout, switchOrganization }), [session, login, logout, switchOrganization])
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthState {
  const context = useContext(AuthContext)
  if (!context) throw new Error('useAuth must be used inside AuthProvider')
  return context
}
