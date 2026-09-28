import { Navigate, Route, Routes } from 'react-router-dom'
import Layout from './app/Layout'
import { useAuth } from './app/auth'
import AnalysePage from './features/areas/AnalysePage'
import ReportPage from './features/areas/ReportPage'
import Home from './features/home/Home'
import JobPage from './features/jobs/JobPage'

function RequireUser({ children }) {
  const { user } = useAuth()
  return user ? children : <Navigate to="/" replace />
}

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Home />} />
        <Route path="areas/analyse" element={<RequireUser><AnalysePage /></RequireUser>} />
        <Route path="areas/reports/:id" element={<RequireUser><ReportPage /></RequireUser>} />
        <Route path="jobs/:id" element={<RequireUser><JobPage /></RequireUser>} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  )
}
