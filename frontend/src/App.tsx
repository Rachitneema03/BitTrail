import type { ReactNode } from 'react'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import Layout from './components/Layout'
import Alerts from './pages/Alerts'
import CaseDetail from './pages/CaseDetail'
import Cases from './pages/Cases'
import Dashboard from './pages/Dashboard'
import Login from './pages/Login'
import NewCase from './pages/NewCase'
import Requests from './pages/Requests'
import VaspInbox from './pages/VaspInbox'
import { AuthProvider, useAuth } from './store/auth'

function Guard({ children, vasp = false }: { children: ReactNode; vasp?: boolean }) {
  const { me, loading } = useAuth()
  if (loading) return <div className="p-10 text-muted">Loading…</div>
  if (!me) return <Navigate to="/login" replace />
  if (vasp !== (me.role === 'vasp')) return <Navigate to={me.role === 'vasp' ? '/vasp' : '/'} replace />
  return <>{children}</>
}

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route element={<Layout />}>
            <Route path="/" element={<Guard><Dashboard /></Guard>} />
            <Route path="/cases" element={<Guard><Cases /></Guard>} />
            <Route path="/cases/new" element={<Guard><NewCase /></Guard>} />
            <Route path="/cases/:id" element={<Guard><CaseDetail /></Guard>} />
            <Route path="/requests" element={<Guard><Requests /></Guard>} />
            <Route path="/alerts" element={<Guard><Alerts /></Guard>} />
            <Route path="/vasp" element={<Guard vasp><VaspInbox /></Guard>} />
          </Route>
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  )
}
