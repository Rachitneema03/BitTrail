import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'
import { api, getToken, post, setToken } from '../api/client'
import type { Me } from '../api/types'

interface AuthCtx { me: Me | null; loading: boolean; login: (email: string, password: string) => Promise<Me>; logout: () => void }
const Ctx = createContext<AuthCtx | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<Me | null>(null)
  const [loading, setLoading] = useState(!!getToken())

  useEffect(() => {
    if (!getToken()) return
    api<Me>('/auth/me').then(setMe).catch(() => setToken(null)).finally(() => setLoading(false))
  }, [])

  const login = async (email: string, password: string) => {
    const r = await post<{ token: string; user: Me }>('/auth/login', { email, password })
    setToken(r.token)
    setMe(r.user)
    return r.user
  }
  const logout = () => { setToken(null); setMe(null) }
  return <Ctx.Provider value={{ me, loading, login, logout }}>{children}</Ctx.Provider>
}

export function useAuth(): AuthCtx {
  const c = useContext(Ctx)
  if (!c) throw new Error('useAuth outside AuthProvider')
  return c
}
