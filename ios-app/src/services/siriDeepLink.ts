/**
 * siriDeepLink — handles the sara://ask?q=<prompt> URL produced by the
 * "Ask Sara" App Intent / Siri shortcut (P3).
 *
 * Routes the spoken prompt into the chat as a quick-reply (the same auto-send
 * path push notifications use). Handles both cold start (getInitialURL) and
 * warm delivery (url event).
 */
import * as Linking from 'expo-linking'
import { navigateToChat } from './navigation'

function handleUrl(url: string | null): void {
  if (!url) return
  try {
    const parsed = Linking.parse(url)
    const isAsk = parsed.hostname === 'ask' || parsed.path === 'ask'
    if (!isAsk) return
    const raw = parsed.queryParams?.q
    const q = Array.isArray(raw) ? raw[0] : raw
    if (q && typeof q === 'string' && q.trim()) {
      // Give navigation a tick to be ready on cold start.
      setTimeout(() => {
        navigateToChat({
          quickReply: { message: q.trim(), nudgeType: 'siri', title: 'Ask Sara' },
        })
      }, 350)
    }
  } catch (e) {
    console.warn('[siriDeepLink] parse failed:', e)
  }
}

/** Wire up Siri deep-link handling. Returns an unsubscribe fn. */
export function initSiriDeepLink(): () => void {
  Linking.getInitialURL().then(handleUrl).catch(() => {})
  const sub = Linking.addEventListener('url', (e) => handleUrl(e.url))
  return () => sub.remove()
}
