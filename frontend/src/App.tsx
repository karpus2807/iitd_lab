import { Navigate, Route, Routes } from 'react-router-dom'
import type { ReactNode } from 'react'
import { currentUser } from './api'
import Layout from './Layout'
import Account from './pages/Account'
import Admin from './pages/Admin'
import Alerts from './pages/Alerts'
import Dashboard from './pages/Dashboard'
import Login from './pages/Login'
import MachineDetail from './pages/MachineDetail'
import Machines from './pages/Machines'

function RequireAuth({ children }: { children: ReactNode }) {
  if (!currentUser() && !localStorage.getItem('lw_access')) return <Navigate to="/login" replace />
  return children
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route
        path="/"
        element={
          <RequireAuth>
            <Layout />
          </RequireAuth>
        }
      >
        <Route index element={<Dashboard />} />
        <Route path="machines" element={<Machines />} />
        <Route path="machines/:id" element={<MachineDetail />} />
        <Route path="labs" element={<Navigate to="/admin?tab=labs" replace />} />
        <Route path="infra" element={<Navigate to="/admin?tab=labs" replace />} />
        <Route path="updates" element={<Navigate to="/admin?tab=updates" replace />} />
        <Route path="alerts" element={<Alerts />} />
        <Route path="admin" element={<Admin />} />
        <Route path="admin/updates" element={<Navigate to="/admin?tab=updates" replace />} />
        <Route path="account" element={<Account />} />
      </Route>
    </Routes>
  )
}
