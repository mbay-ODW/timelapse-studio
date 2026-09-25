import { NavLink, Navigate, Route, Routes } from 'react-router-dom'
import { ThemeToggle } from './components/ThemeToggle'
import { Toasts } from './components/Toast'
import { SourcesPage } from './pages/SourcesPage'

export default function App() {
  return (
    <div className="app">
      <header className="header">
        <NavLink to="/" className="brand"><img src="/favicon.svg" alt="" /><span>Timelapse Studio</span></NavLink>
        <nav className="nav">
          <NavLink to="/sources">Quellen</NavLink>
        </nav>
        <div className="spacer" />
        <ThemeToggle />
      </header>
      <main className="main">
        <Routes>
          <Route path="/" element={<Navigate to="/sources" replace />} />
          <Route path="/sources" element={<SourcesPage />} />
          <Route path="*" element={<div className="empty">Seite nicht gefunden</div>} />
        </Routes>
      </main>
      <Toasts />
    </div>
  )
}
