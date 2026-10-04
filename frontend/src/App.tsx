import { useTranslation } from 'react-i18next'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router'

import { AuthProvider, useAuth } from './auth'
import { AppShell } from './components/AppShell'
import { ChooseOrganizationPage } from './pages/ChooseOrganizationPage'
import { FrameworkListPage } from './pages/competencies/FrameworkListPage'
import { FrameworkPage } from './pages/competencies/FrameworkPage'
import { HomePage } from './pages/HomePage'
import { LoginPage } from './pages/LoginPage'
import { DiffPage } from './pages/programs/DiffPage'
import { ProgramListPage } from './pages/programs/ProgramListPage'
import { ProgramPage } from './pages/programs/ProgramPage'
import { VersionPage } from './pages/programs/VersionPage'
import { TemplateListPage } from './pages/templates/TemplateListPage'
import { TemplatePage } from './pages/templates/TemplatePage'
import { TasksPage } from './pages/workflows/TasksPage'
import { WorkflowsPage } from './pages/workflows/WorkflowsPage'

function Loading() {
  const { t } = useTranslation()
  return <p className="loading">{t('app.loading')}</p>
}

function OrganizationRoutes() {
  return (
    <Routes>
      <Route path="/" element={<HomePage />} />
      <Route path="/programs" element={<ProgramListPage />} />
      <Route path="/programs/:id" element={<ProgramPage />} />
      <Route path="/programs/:id/diff/:from/:to" element={<DiffPage />} />
      <Route path="/program-versions/:id" element={<VersionPage />} />
      <Route path="/competencies" element={<FrameworkListPage />} />
      <Route path="/competencies/:id" element={<FrameworkPage />} />
      <Route path="/templates" element={<TemplateListPage />} />
      <Route path="/templates/:id" element={<TemplatePage />} />
      <Route path="/tasks" element={<TasksPage />} />
      <Route path="/workflows" element={<WorkflowsPage />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}

function SignedIn() {
  const { session } = useAuth()
  if (session === undefined) return <Loading />
  if (session === null) return <Navigate to="/login" replace />
  const organization = session.organization
  const active = organization && organization.role !== 'pending'
  return (
    <AppShell>
      {/* Keyed by organization so every page reloads its data after a switch. */}
      {active ? <OrganizationRoutes key={organization.id} /> : organization ? <HomePage /> : <ChooseOrganizationPage />}
    </AppShell>
  )
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
