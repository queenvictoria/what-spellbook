import { NavLink, Navigate, Route, Routes } from "react-router-dom"

import { LicensingNotice } from "@/components/LicensingNotice"
import { CharacterScreen } from "@/screens/CharacterScreen"
import { HistoryScreen } from "@/screens/HistoryScreen"
import { RulesScreen } from "@/screens/RulesScreen"
import { ScenarioScreen } from "@/screens/ScenarioScreen"
import { SearchScreen } from "@/screens/SearchScreen"
import { SettingsScreen } from "@/screens/SettingsScreen"
import { cn } from "@/lib/utils"
import { BookOpen, Clock, GraphStarIcon, Settings, Waypoints, User } from "lucide-react"

const NAV = [
  { to: "/scenario", label: "Scenario", icon: Waypoints },
  { to: "/rules", label: "Rules", icon: BookOpen },
  { to: "/character", label: "Character", icon: User },
  { to: "/history", label: "History", icon: Clock },
  // { to: '/search', label: 'Search' },
]

export function App() {
  return (
    <div className="min-h-screen flex flex-col pb-10 sm:pb-0 sm:pt-10">
      {/* Sticky rather than fixed: the header keeps its place in the flow, so the main
          content needs no compensating top padding. z-40 sits below the drawers (z-50). */}
      <header className="fixed w-screen bottom-0 sm:bottom-auto sm:top-0 z-40 border-t sm:border-t-0 sm:border-b border-void-800 bg-void-900/70 backdrop-blur">
        <div className="mx-auto flex max-w-6xl items-center gap-6 px-6 py-3">
          <span className="font-semibold tracking-tight text-parchment whitespace-nowrap">
            What Loadout
          </span>
          <nav className="flex gap-1 w-full">
            {NAV.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                className={({ isActive }) =>
                  cn(
                    "rounded-md px-3 py-1.5 text-sm transition-colors flex gap-1 items-center justify-center",
                    isActive
                      ? "bg-void-800 text-parchment"
                      : "text-parchment/60 hover:text-parchment",
                  )
                }
              >
                <item.icon className="h-4 w-4" />
                <span className="hidden sm:inline ml-2">{item.label}</span>
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
              <GraphStarIcon className="ml-1 inline h-4 w-4 text-parchment/60 transition-colors group-hover:text-parchment" />
              <span className="hidden sm:inline">Search</span>
            </NavLink>
            {/* Settings sits after Search, which is pushed right by `ml-auto`, so the two
                group together at the end rather than splitting the main nav. */}
            <NavLink
              key="settings"
              to="/settings"
              className={({ isActive }) =>
                cn(
                  "rounded-md px-3 py-1.5 text-sm transition-colors",
                  "flex gap-1 items-center justify-center",
                  isActive
                    ? "bg-void-800 text-parchment"
                    : "text-parchment/60 hover:text-parchment",
                )
              }
            >
              <Settings className="h-4 w-4" />
              <span className="hidden sm:inline ml-2">Settings</span>
            </NavLink>
          </nav>
        </div>
      </header>

      <main className="mx-auto max-w-6xl px-6 py-8 grow">
        <Routes>
          <Route path="/" element={<Navigate to="/scenario" replace />} />
          <Route path="/scenario" element={<ScenarioScreen />} />
          <Route path="/history" element={<HistoryScreen />} />
          {/* The Chats tab was folded into History as a subtab; keep old links working. */}
          <Route
            path="/chats"
            element={<Navigate to="/history?tab=conversations" replace />}
          />
          <Route path="/character" element={<CharacterScreen />} />
          <Route path="/rules" element={<RulesScreen />} />
          <Route path="/search" element={<SearchScreen />} />
          <Route path="/settings" element={<SettingsScreen />} />
          <Route path="*" element={<Navigate to="/scenario" replace />} />
        </Routes>
      </main>

      {/* The third-party attributions, below the routed screen. CC-BY-4.0 requires the
          notice to travel with the work, and the work is the app — the SRD text is quoted
          all over the Rules tab. It renders nothing when the API cannot be reached. */}
      <LicensingNotice />
    </div>
  )
}
