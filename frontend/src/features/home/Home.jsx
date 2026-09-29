import { Link } from 'react-router-dom'
import RoleSwitcher from '../../app/RoleSwitcher'
import { ROLE_LABELS, useAuth } from '../../app/auth'
import ExecHome from '../scouting/ExecHome'
import InboxPage from '../studies/InboxPage'
import MyUnitsPage from '../units/MyUnitsPage'

// What each persona will land on (docs/DESIGN.md §4). Every role has its own home.
const HOMES = {
  bd_manager: {
    title: 'Where should we open next?',
    body: 'Pick an area of Chennai — by pincode, locality or cells on the map — and get an Area Fitness Report with hotspots to scout.',
    cta: { to: '/areas/analyse', label: 'Analyse an area' },
    secondary: { to: '/pipeline', label: 'Review the pipeline' },
  },
}

export default function Home() {
  const { user } = useAuth()
  if (!user) {
    return (
      <div className="mx-auto max-w-2xl px-4 py-10">
        <h1 className="text-2xl font-bold text-brand">Choose who you are</h1>
        <p className="mt-1 mb-6 text-sm">Demo sign-in: four seeded users, one per role. Access rules are enforced by the API.</p>
        <RoleSwitcher variant="cards" />
      </div>
    )
  }
  if (user.role === 'bd_executive') return <ExecHome />
  if (user.role === 'survey_manager') return <InboxPage />
  if (user.role === 'survey_executive') return <MyUnitsPage />
  const home = HOMES[user.role]
  return (
    <div className="mx-auto max-w-2xl px-4 py-10">
      <p className="text-sm text-brand">{ROLE_LABELS[user.role]}</p>
      <h1 className="text-2xl font-bold">{home.title}</h1>
      <p className="mt-2">{home.body}</p>
      {home.cta && (
        <Link
          to={home.cta.to}
          className="mt-6 inline-block rounded-md bg-accent px-4 py-2 font-semibold text-ink shadow hover:brightness-95"
        >
          {home.cta.label}
        </Link>
      )}
      {home.secondary && (
        <Link to={home.secondary.to} className="mt-6 ml-3 inline-block rounded-md px-4 py-2 font-semibold text-brand ring-1 ring-brand/40 hover:bg-white">
          {home.secondary.label}
        </Link>
      )}
    </div>
  )
}
