import '@fontsource/noto-naskh-arabic/400.css'
import '@fontsource/noto-naskh-arabic/700.css'
import './styles.css'

import { createRoot } from 'react-dom/client'

import { App } from './App'

// StrictMode is intentionally off: its double mount destroys the single provider.
createRoot(document.getElementById('root')!).render(<App />)
