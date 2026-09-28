import { NavLink, Outlet } from 'react-router-dom'
import RoleSwitcher from './RoleSwitcher'
import { useAuth } from './auth'

const NAV = {
  bd_manager: [
    { to: '/areas/analyse', label: 'Analyse area' },
    { to: '/areas/reports', label: 'Reports' },
    { to: '/pipeline', label: 'Pipeline' },
  ],
  bd_executive: [
    { to: '/', label: 'My tasks' },
    { to: '/properties', label: 'My properties' },
  ],
  survey_manager: [{ to: '/', label: 'Studies' }],
  survey_executive: [],
}

export default function Layout() {
  const { user } = useAuth()
  return (
    <div className="flex h-dvh flex-col bg-brand-light text-ink">
      <header className="bg-brand text-white shadow">
        {/* Phones: brand + role switcher on one row, nav on its own row below. */}
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 px-4 py-2.5">
          <NavLink to="/" className="text-lg font-semibold whitespace-nowrap">
            Savo <span className="text-accent">SiteScout</span>
          </NavLink>
          <nav className="order-3 -mx-3 flex w-full gap-1 overflow-x-auto md:order-none md:mx-0 md:w-auto">
            {(NAV[user?.role] ?? []).map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.to === '/'}
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
      <main className="min-h-0 flex-1 overflow-y-auto">
        <Outlet />
      </main>
    </div>
  )
}
