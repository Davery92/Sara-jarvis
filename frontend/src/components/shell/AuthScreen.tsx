import React from 'react'

interface AuthScreenProps {
  assistantName: string
  subtitle: string
  email: string
  password: string
  isLogin: boolean
  loading: boolean
  message: string
  onEmailChange: (value: string) => void
  onPasswordChange: (value: string) => void
  onToggleMode: () => void
  onSubmit: (event: React.FormEvent<HTMLFormElement>) => void
}

const AuthScreen: React.FC<AuthScreenProps> = ({
  assistantName,
  subtitle,
  email,
  password,
  isLogin,
  loading,
  message,
  onEmailChange,
  onPasswordChange,
  onToggleMode,
  onSubmit,
}) => {
  return (
    <div className="relative min-h-screen overflow-hidden px-4 py-6 text-slate-100 md:px-8 md:py-10">
      <div className="pointer-events-none absolute inset-0 overflow-hidden">
        <div className="absolute left-[-8rem] top-[-10rem] h-72 w-72 rounded-full bg-teal-400/12 blur-3xl" />
        <div className="absolute bottom-[-8rem] right-[-6rem] h-80 w-80 rounded-full bg-sky-400/12 blur-3xl" />
        <div className="absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-white/10 to-transparent" />
      </div>

      <div className="relative mx-auto flex min-h-[calc(100vh-3rem)] max-w-6xl items-center">
        <div className="grid w-full gap-6 lg:grid-cols-[1.08fr_0.92fr]">
          <section className="assistant-panel relative hidden overflow-hidden rounded-md p-8 lg:flex lg:flex-col lg:justify-between xl:p-10">
            <div className="absolute inset-0 bg-[radial-gradient(circle_at_top_left,rgba(94,234,212,0.12),transparent_32%),radial-gradient(circle_at_bottom_right,rgba(125,211,252,0.14),transparent_28%)]" />
            <div className="relative">
              <div className="assistant-kicker mb-4">Assistant Workspace</div>
              <div className="mb-6 flex items-center gap-4">
                <div className="flex h-16 w-16 items-center justify-center rounded-md border border-white/10 bg-white text-2xl font-bold text-slate-950 shadow-lg shadow-cyan-950/30">
                  S
                </div>
                <div>
                  <h1 className="font-display text-4xl font-semibold text-white xl:text-5xl">
                    {assistantName}
                  </h1>
                  <p className="mt-2 max-w-lg text-base leading-relaxed text-slate-300">
                    {subtitle}
                  </p>
                </div>
              </div>

              <div className="grid gap-3 sm:grid-cols-3">
                {[
                  {
                    title: 'Today first',
                    body: 'Open to your brief, priorities, and what needs action right now.',
                  },
                  {
                    title: 'Chat with context',
                    body: 'Move from inbox items, notes, and documents into one assistant conversation.',
                  },
                  {
                    title: 'Autonomy visible',
                    body: 'See what Sara is already running before you start issuing commands.',
                  },
                ].map((feature) => (
                  <div key={feature.title} className="assistant-panel-soft rounded-md p-4">
                    <p className="font-display text-sm font-semibold text-white">{feature.title}</p>
                    <p className="mt-2 text-sm leading-relaxed text-slate-400">{feature.body}</p>
                  </div>
                ))}
              </div>
            </div>

            <div className="relative mt-8 grid gap-3 xl:grid-cols-[1.25fr_0.75fr]">
              <div className="assistant-panel-soft rounded-md p-5">
                <div className="assistant-kicker mb-3">What This Rebuild Does</div>
                <p className="font-display text-xl text-white">One assistant home, not twenty scattered tools.</p>
                <p className="mt-3 text-sm leading-relaxed text-slate-400">
                  The web app now centers on dashboard, chat, inbox, calendar, and email, with the rest tucked behind a calmer secondary shell.
                </p>
              </div>
              <div className="assistant-panel-soft rounded-md p-5">
                <div className="assistant-kicker mb-3">Ready State</div>
                <div className="space-y-3 text-sm text-slate-300">
                  <div className="flex items-center justify-between">
                    <span>Chat + Inbox</span>
                    <span className="rounded-full bg-emerald-400/12 px-2 py-1 text-xs text-emerald-300">Live</span>
                  </div>
                  <div className="flex items-center justify-between">
                    <span>Morning Brief</span>
                    <span className="rounded-full bg-sky-400/12 px-2 py-1 text-xs text-sky-300">Linked</span>
                  </div>
                  <div className="flex items-center justify-between">
                    <span>Autonomy</span>
                    <span className="rounded-full bg-amber-400/12 px-2 py-1 text-xs text-amber-300">Visible</span>
                  </div>
                </div>
              </div>
            </div>
          </section>

          <section className="assistant-panel relative overflow-hidden rounded-md p-6 sm:p-8">
            <div className="absolute inset-0 bg-[radial-gradient(circle_at_top,rgba(94,234,212,0.08),transparent_30%)]" />
            <div className="relative">
              <div className="mb-8 flex items-start justify-between gap-4">
                <div>
                  <div className="assistant-kicker mb-3">{isLogin ? 'Sign in' : 'Create account'}</div>
                  <h2 className="font-display text-3xl font-semibold text-white">
                    {isLogin ? `Welcome back to ${assistantName}` : `Start using ${assistantName}`}
                  </h2>
                  <p className="mt-3 max-w-md text-sm leading-relaxed text-slate-400">
                    {isLogin
                      ? 'Open the assistant workspace, review what changed, and pick up where you left off.'
                      : 'Create your account to use the redesigned assistant dashboard, inbox, and chat workspace.'}
                  </p>
                </div>
                <div className="flex h-12 w-12 items-center justify-center rounded-md border border-white/10 bg-white/95 text-lg font-bold text-slate-950 shadow-lg shadow-cyan-950/25 lg:hidden">
                  S
                </div>
              </div>

              <form onSubmit={onSubmit} className="space-y-4">
                <div>
                  <label className="mb-2 block text-sm font-medium text-slate-300">Email</label>
                  <input
                    type="email"
                    value={email}
                    onChange={(event) => onEmailChange(event.target.value)}
                    className="w-full rounded-md border border-white/10 bg-slate-950/60 px-4 py-3 text-white outline-none transition focus:border-teal-400/60 focus:ring-2 focus:ring-teal-400/20"
                    placeholder="you@example.com"
                    required
                  />
                </div>

                <div>
                  <label className="mb-2 block text-sm font-medium text-slate-300">Password</label>
                  <input
                    type="password"
                    value={password}
                    onChange={(event) => onPasswordChange(event.target.value)}
                    className="w-full rounded-md border border-white/10 bg-slate-950/60 px-4 py-3 text-white outline-none transition focus:border-teal-400/60 focus:ring-2 focus:ring-teal-400/20"
                    placeholder={isLogin ? 'Enter your password' : 'Create a secure password'}
                    required
                  />
                </div>

                {message && (
                  <div className="rounded-md border border-rose-500/20 bg-rose-500/10 px-4 py-3 text-sm text-rose-200">
                    {message}
                  </div>
                )}

                <button
                  type="submit"
                  disabled={loading}
                  className="flex w-full items-center justify-center gap-2 rounded-md bg-gradient-to-r from-teal-400 via-cyan-400 to-sky-400 px-4 py-3 font-medium text-slate-950 transition hover:brightness-105 disabled:cursor-not-allowed disabled:opacity-70"
                >
                  <span className="material-icons text-base">{loading ? 'hourglass_top' : isLogin ? 'arrow_forward' : 'sparkles'}</span>
                  <span>{loading ? 'Please wait…' : isLogin ? 'Enter Workspace' : 'Create Account'}</span>
                </button>

                <div className="flex flex-col gap-3 border-t border-white/8 pt-4 text-sm text-slate-400 sm:flex-row sm:items-center sm:justify-between">
                  <p>Use the same account to keep your dashboard, inbox, and chat context together.</p>
                  <button
                    type="button"
                    onClick={onToggleMode}
                    className="text-left font-medium text-teal-300 transition hover:text-teal-200 sm:text-right"
                  >
                    {isLogin ? "Don't have an account? Sign up" : 'Already have an account? Sign in'}
                  </button>
                </div>
              </form>
            </div>
          </section>
        </div>
      </div>
    </div>
  )
}

export default AuthScreen
