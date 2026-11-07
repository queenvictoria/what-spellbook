import { NavLink, Navigate, Route, Routes } from "react-router-dom"

import { CharacterScreen } from "@/screens/CharacterScreen"
import { ChatsScreen } from "@/screens/ChatsScreen"
import { HistoryScreen } from "@/screens/HistoryScreen"
import { RulesScreen } from "@/screens/RulesScreen"
import { ScenarioScreen } from "@/screens/ScenarioScreen"
import { SearchScreen } from "@/screens/SearchScreen"
import { cn } from "@/lib/utils"
import { GraphStar } from "lucide-react"

const NAV = [
  { to: "/scenario", label: "Scenario" },
  { to: "/rules", label: "Rules" },
  { to: "/character", label: "Character" },
  { to: "/history", label: "History" },
  { to: "/chats", label: "Chats" },
  // { to: '/search', label: 'Search' },
]

export function App() {
  return (
    <div className="min-h-screen">
      {/* Sticky rather than fixed: the header keeps its place in the flow, so the main
          content needs no compensating top padding. z-40 sits below the drawers (z-50). */}
      <header className="sticky top-0 z-40 border-b border-void-800 bg-void-900/70 backdrop-blur">
        <div className="mx-auto flex max-w-6xl items-center gap-6 px-6 py-3">
          <span className="font-semibold tracking-tight text-parchment whitespace-nowrap">
            What Spellbook
          </span>
          <nav className="flex gap-1 w-full">
            {NAV.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                className={({ isActive }) =>
                  cn(
                    "rounded-md px-3 py-1.5 text-sm transition-colors",
                    isActive
                      ? "bg-void-800 text-parchment"
                      : "text-parchment/60 hover:text-parchment",
                  )
                }
              >
                {item.label}
              </NavLink>
            ))}
            <NavLink
              key="search"
              to="/search"
              className={({ isActive }) =>
                cn(
                  "rounded-md px-3 py-1.5 text-sm transition-colors",
                  "ml-auto flex gap-1 items-center justify-center",
                  isActive
                    ? "bg-void-800 text-parchment"
                    : "text-parchment/60 hover:text-parchment",
                )
              }
            >
              <GraphStar className="ml-1 inline h-4 w-4 text-parchment/60 transition-colors group-hover:text-parchment" />
              Search
            </NavLink>
          </nav>
        </div>
      </header>

      <main className="mx-auto max-w-6xl px-6 py-8">
        <Routes>
          <Route path="/" element={<Navigate to="/scenario" replace />} />
          <Route path="/scenario" element={<ScenarioScreen />} />
          <Route path="/history" element={<HistoryScreen />} />
          <Route path="/chats" element={<ChatsScreen />} />
          <Route path="/character" element={<CharacterScreen />} />
          <Route path="/rules" element={<RulesScreen />} />
          <Route path="/search" element={<SearchScreen />} />
          <Route path="*" element={<Navigate to="/scenario" replace />} />
        </Routes>
      </main>
    </div>
  )
}
