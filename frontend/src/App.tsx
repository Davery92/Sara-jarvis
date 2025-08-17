import { Routes, Route } from 'react-router-dom'
import Layout from './components/Layout'
import Home from './pages/Home'
import Chat from './pages/Chat'
import Notes from './pages/Notes'
import Documents from './pages/Documents'
import Reminders from './pages/Reminders'
import Calendar from './pages/Calendar'
import Settings from './pages/Settings'
import Login from './pages/Login'
import { useAuth } from './hooks/useAuth'

function App() {
  const { isAuthenticated } = useAuth()

  if (!isAuthenticated) {
    return <Login />
  }

  return (
    <Layout>
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/chat" element={<Chat />} />
        <Route path="/notes" element={<Notes />} />
        <Route path="/documents" element={<Documents />} />
        <Route path="/reminders" element={<Reminders />} />
        <Route path="/calendar" element={<Calendar />} />
        <Route path="/settings" element={<Settings />} />
      </Routes>
    </Layout>
  )
}

export default App