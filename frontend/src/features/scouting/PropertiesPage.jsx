// Properties list: an executive's own, or (BD Manager) everyone's. The manager's pipeline board is 7b.
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { api } from '../../api/client'
import { useAuth } from '../../app/auth'
import { OUTCOME_STYLE, STAGE_LABEL } from './PropertyPage'

export default function PropertiesPage() {
  const { user } = useAuth()
  const list = useQuery({ queryKey: ['properties'], queryFn: () => api('/properties') })
  return (
    <div className="mx-auto max-w-xl p-4">
      <h1 className="text-xl font-bold">{user.role === 'bd_manager' ? 'All properties' : 'My properties'}</h1>
      {list.data?.length === 0 && <p className="mt-3 text-sm">None yet. <Link to="/properties/new" className="text-brand underline">Add one</Link>.</p>}
      <ul className="mt-3 space-y-2">
        {list.data?.map((p) => (
          <li key={p.id}>
            <Link to={`/properties/${p.id}`} className="block rounded-lg border border-brand/15 bg-white p-3">
              <div className="flex items-center gap-2">
                <span className="font-semibold">{p.label}</span>
                {p.outcome
                  ? <span className={`ml-auto rounded-full px-2 py-0.5 text-xs ${OUTCOME_STYLE[p.outcome]}`}>{p.outcome}</span>
                  : <span className="ml-auto text-xs opacity-60">{p.evaluation_status === 'pending' ? 'evaluating…' : ''}</span>}
              </div>
              <div className="text-xs opacity-70">
                {STAGE_LABEL(p.stage)} · {p.locality ?? p.pincode}
                {p.status === 'possible_duplicate' && <span className="ml-1 text-amber-700">· possible duplicate</span>}
                {p.missing_fields.includes('photos') && <span className="ml-1">· no photos</span>}
              </div>
            </Link>
          </li>
        ))}
      </ul>
    </div>
  )
}
