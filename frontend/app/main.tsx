import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'

import { App } from './App'
import { SpellDrawerProvider } from './components/SpellDrawer'
import { RuleDrawerProvider } from './components/RuleDrawer'
import { ClassNamesProvider } from './lib/ClassNamesProvider'
import { SpellNamesProvider } from './lib/SpellNamesProvider'
import './index.css'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BrowserRouter>
      <SpellNamesProvider>
        {/* The class context names are a second list of linkable names, and a separate
            provider because they link somewhere else: a spell opens the spell drawer, a
            class file opens the rule drawer. */}
        <ClassNamesProvider>
          {/* Inside the router so the drawer is above every screen and survives navigation;
              matching a spell to a drawer is not a per-screen concern. */}
          <SpellDrawerProvider>
            {/* A sibling of the spell drawer, not a child: a rule and a spell are two
                readings of two different things, and nesting them would make one panel
                depend on the other's state. */}
            <RuleDrawerProvider>
              <App />
            </RuleDrawerProvider>
          </SpellDrawerProvider>
        </ClassNamesProvider>
      </SpellNamesProvider>
    </BrowserRouter>
  </StrictMode>,
)
