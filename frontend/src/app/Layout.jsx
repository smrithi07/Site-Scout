import { NavLink, Outlet } from 'react-router-dom'
import RoleSwitcher from './RoleSwitcher'
import { useAuth } from './auth'

const NAV = {
  bd_manager: [
    { to: '/areas/analyse', label: 'Analyse area' },
    { to: '/areas/reports', label: 'Reports' },
  ],
  bd_executive: [],
  survey_manager: [],
  survey_executive: [],
}

export default function Layout() {
  const { user } = useAuth()
  return (
    <div className="flex h-dvh flex-col bg-brand-light text-ink">
      <header className="bg-brand text-white shadow">
        <div className="flex items-center gap-4 px-4 py-2.5">
          <NavLink to="/" className="text-lg font-semibold whitespace-nowrap">
            Savo <span className="text-accent">SiteScout</span>
          </NavLink>
          <nav className="flex gap-1 overflow-x-auto">
            {(NAV[user?.role] ?? []).map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                className={({ isActive }) =>
                  `rounded-md px-3 py-1.5 text-sm whitespace-nowrap ${isActive ? 'bg-white/20' : 'hover:bg-white/10'}`
                }
              >
                {item.label}
              </NavLink>
            ))}
          </nav>
          <div className="ml-auto">{user && <RoleSwitcher />}</div>
        </div>
      </header>
      <main className="min-h-0 flex-1">
        <Outlet />
      </main>
    </div>
  )
}
