import { NavLink, Navigate, Route, Routes } from 'react-router-dom'

import { CharacterScreen } from '@/screens/CharacterScreen'
import { HistoryScreen } from '@/screens/HistoryScreen'
import { RulesScreen } from '@/screens/RulesScreen'
import { ScenarioScreen } from '@/screens/ScenarioScreen'
import { cn } from '@/lib/utils'

const NAV = [
  { to: '/scenario', label: 'Scenario' },
  { to: '/history', label: 'History' },
  { to: '/character', label: 'Character' },
  { to: '/rules', label: 'Rules' },
]

export function App() {
  return (
    <div className="min-h-screen">
      <header className="border-b border-void-800 bg-void-900/70 backdrop-blur">
        <div className="mx-auto flex max-w-6xl items-center gap-6 px-6 py-3">
          <span className="font-semibold tracking-tight text-parchment">
            What Spellbook
          </span>
          <nav className="flex gap-1">
            {NAV.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                className={({ isActive }) =>
                  cn(
                    'rounded-md px-3 py-1.5 text-sm transition-colors',
                    isActive
                      ? 'bg-void-800 text-parchment'
                      : 'text-parchment/60 hover:text-parchment',
                  )
                }
              >
                {item.label}
              </NavLink>
            ))}
          </nav>
        </div>
      </header>

      <main className="mx-auto max-w-6xl px-6 py-8">
        <Routes>
          <Route path="/" element={<Navigate to="/scenario" replace />} />
          <Route path="/scenario" element={<ScenarioScreen />} />
          <Route path="/history" element={<HistoryScreen />} />
          <Route path="/character" element={<CharacterScreen />} />
          <Route path="/rules" element={<RulesScreen />} />
          <Route path="*" element={<Navigate to="/scenario" replace />} />
        </Routes>
      </main>
    </div>
  )
}
