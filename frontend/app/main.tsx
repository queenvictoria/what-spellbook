import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'

import { App } from './App'
import { SpellDrawerProvider } from './components/SpellDrawer'
import { SrdDrawerProvider } from './components/SrdDrawer'
import { SpellNamesProvider } from './lib/SpellNamesProvider'
import './index.css'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BrowserRouter>
      <SpellNamesProvider>
        {/* Inside the router so the drawer is above every screen and survives navigation;
            matching a spell to a drawer is not a per-screen concern. */}
        <SpellDrawerProvider>
          {/* A sibling of the spell drawer, not a child: a rule and a spell are two
              readings of two different things, and nesting them would make one panel
              depend on the other's state. */}
          <SrdDrawerProvider>
            <App />
          </SrdDrawerProvider>
        </SpellDrawerProvider>
      </SpellNamesProvider>
    </BrowserRouter>
  </StrictMode>,
)
