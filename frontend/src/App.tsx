import { useTranslation } from 'react-i18next'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router'

import { AuthProvider, useAuth } from './auth'
import { AppShell } from './components/AppShell'
import { ChooseOrganizationPage } from './pages/ChooseOrganizationPage'
import { HomePage } from './pages/HomePage'
import { LoginPage } from './pages/LoginPage'

function Loading() {
  const { t } = useTranslation()
  return <p className="loading">{t('app.loading')}</p>
}

function SignedIn() {
  const { session } = useAuth()
  if (session === undefined) return <Loading />
  if (session === null) return <Navigate to="/login" replace />
  return <AppShell>{session.organization ? <HomePage /> : <ChooseOrganizationPage />}</AppShell>
}

function SignedOut() {
  const { session } = useAuth()
  if (session === undefined) return <Loading />
  if (session) return <Navigate to="/" replace />
  return <LoginPage />
}

export function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<SignedOut />} />
          <Route path="*" element={<SignedIn />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  )
}
