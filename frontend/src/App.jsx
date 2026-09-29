import { Navigate, Route, Routes } from 'react-router-dom'
import Layout from './app/Layout'
import { useAuth } from './app/auth'
import AnalysePage from './features/areas/AnalysePage'
import ComparePage from './features/areas/ComparePage'
import ReportPage from './features/areas/ReportPage'
import ReportsPage from './features/areas/ReportsPage'
import Home from './features/home/Home'
import JobPage from './features/jobs/JobPage'
import OpportunitiesPage from './features/opportunities/OpportunitiesPage'
import BoardPage from './features/pipeline/BoardPage'
import PropertiesPage from './features/scouting/PropertiesPage'
import PropertyForm from './features/scouting/PropertyForm'
import PropertyPage from './features/scouting/PropertyPage'
import TaskPage from './features/scouting/TaskPage'
import StudyPage from './features/studies/StudyPage'
import { CaptureRoute } from './features/units/CaptureForm'
import UnitPage from './features/units/UnitPage'

function RequireUser({ children }) {
  const { user } = useAuth()
  return user ? children : <Navigate to="/" replace />
}

const guarded = (el) => <RequireUser>{el}</RequireUser>

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Home />} />
        <Route path="areas/analyse" element={guarded(<AnalysePage />)} />
        <Route path="areas/reports" element={guarded(<ReportsPage />)} />
        <Route path="areas/reports/:id" element={guarded(<ReportPage />)} />
        <Route path="areas/compare/:a/:b" element={guarded(<ComparePage />)} />
        <Route path="opportunities" element={guarded(<OpportunitiesPage />)} />
        <Route path="jobs/:id" element={guarded(<JobPage />)} />
        <Route path="tasks/:id" element={guarded(<TaskPage />)} />
        <Route path="pipeline" element={guarded(<BoardPage />)} />
        <Route path="studies/:id" element={guarded(<StudyPage />)} />
        <Route path="units/:id" element={guarded(<UnitPage />)} />
        <Route path="units/:id/lanes/:segmentId" element={guarded(<CaptureRoute />)} />
        <Route path="properties" element={guarded(<PropertiesPage />)} />
        <Route path="properties/new" element={guarded(<PropertyForm />)} />
        <Route path="properties/:id" element={guarded(<PropertyPage />)} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  )
}
