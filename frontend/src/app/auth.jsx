// Demo auth: pick one of the four seeded users; the API issues their bearer token. Role checks
// happen server-side — this context only decides what to show.
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { api, loadSession, saveSession, setUnauthorizedHandler } from '../api/client'

const AuthContext = createContext(null)

export const ROLE_LABELS = {
  bd_manager: 'BD Manager',
  bd_executive: 'BD Executive',
  survey_manager: 'Survey Manager',
  survey_executive: 'Survey Executive',
}

export function AuthProvider({ children }) {
  const [session, setSession] = useState(loadSession)
  const queryClient = useQueryClient()

  const signOut = useCallback(() => {
    saveSession(null)
    setSession(null)
    queryClient.clear()
  }, [queryClient])

  useEffect(() => setUnauthorizedHandler(signOut), [signOut])

  const switchUser = useCallback(
    async (userId) => {
      const { token, user } = await api('/auth/demo-login', { method: 'POST', body: { user_id: userId }, token: '' })
      const next = { token, user }
      saveSession(next)
      setSession(next)
      queryClient.clear() // nothing cached for one role may leak into another's screens
    },
    [queryClient],
  )

  const value = useMemo(() => ({ user: session?.user ?? null, switchUser, signOut }), [session, switchUser, signOut])
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  return useContext(AuthContext)
}
