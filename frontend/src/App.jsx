import { useEffect, useState } from 'react'

const API_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'

export default function App() {
  const [health, setHealth] = useState(null)

  useEffect(() => {
    fetch(`${API_URL}/health`)
      .then((r) => r.json())
      .then(setHealth)
      .catch(() => setHealth({ status: 'unreachable' }))
  }, [])

  return (
    <div className="min-h-screen bg-brand-light text-ink">
      <header className="bg-brand text-white">
        <div className="mx-auto flex max-w-5xl items-center justify-between px-4 py-3">
          <h1 className="text-lg font-semibold">
            Savo <span className="text-accent">SiteScout</span>
          </h1>
          <span className="text-sm opacity-80">Expansion intelligence · Chennai</span>
        </div>
      </header>

      <main className="mx-auto max-w-5xl px-4 py-10">
        <h2 className="text-2xl font-bold text-brand">Scaffold is up</h2>
        <p className="mt-2 text-sm">
          API health:{' '}
          <code className="rounded bg-white px-1.5 py-0.5">
            {health ? JSON.stringify(health) : 'checking…'}
          </code>
        </p>
        <button className="mt-6 rounded-md bg-accent px-4 py-2 font-semibold text-ink shadow hover:brightness-95">
          Run area report
        </button>
      </main>
    </div>
  )
}
