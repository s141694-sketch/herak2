import { createContext, type ReactNode, useCallback, useContext, useEffect, useMemo, useState } from 'react'

import { api, ApiError, type MfaPending, type SessionPayload } from './api'

interface AuthState {
  /** undefined while the first /me call is in flight, null when signed out. */
  session: SessionPayload | null | undefined
  /** Signs in with a password; 'mfa' when the second factor is still to be given (verifyMfa). */
  login: (email: string, password: string) => Promise<SessionPayload | 'mfa'>
  verifyMfa: (code: string) => Promise<SessionPayload>
  /** Takes the session as the server now has it (after setting up a second factor, for instance). */
  setSession: (session: SessionPayload) => void
  /** Reads the session again from the server: after a change that may have altered or ended it. */
  refresh: () => Promise<void>
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
    if ((payload as MfaPending).mfa_required === true) return 'mfa' as const
    setSession(payload as SessionPayload)
    return payload as SessionPayload
  }, [])

  const verifyMfa = useCallback(async (code: string) => {
    const payload = await api.verifyMfa(code)
    setSession(payload)
    return payload
  }, [])

  const refresh = useCallback(async () => {
    try {
      setSession(await api.me())
    } catch {
      setSession(null)
    }
  }, [])

  const logout = useCallback(async () => {
    try {
      await api.logout()
    } catch (error) {
      // A session the server already ended (a new password does that) still ends here (phase 8 review).
      if (!(error instanceof ApiError && (error.status === 401 || error.status === 403))) throw error
    } finally {
      setSession(null)
    }
  }, [])

  const switchOrganization = useCallback(async (organizationId: number) => {
    setSession(await api.switchOrganization(organizationId))
  }, [])

  const value = useMemo(
    () => ({ session, login, verifyMfa, setSession, refresh, logout, switchOrganization }),
    [session, login, verifyMfa, refresh, logout, switchOrganization],
  )
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthState {
  const context = useContext(AuthContext)
  if (!context) throw new Error('useAuth must be used inside AuthProvider')
  return context
}
