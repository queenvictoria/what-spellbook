import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'

import { App } from './App'
import { SpellDrawerProvider } from './components/SpellDrawer'
import { SpellNamesProvider } from './lib/SpellNamesProvider'
import './index.css'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BrowserRouter>
      <SpellNamesProvider>
        {/* Inside the router so the drawer is above every screen and survives navigation;
            matching a spell to a drawer is not a per-screen concern. */}
        <SpellDrawerProvider>
          <App />
        </SpellDrawerProvider>
      </SpellNamesProvider>
    </BrowserRouter>
  </StrictMode>,
)
