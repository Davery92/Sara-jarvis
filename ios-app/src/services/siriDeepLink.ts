/**
 * siriDeepLink — delivers the "Ask Sara" Siri prompt into the chat (P3).
 *
 * The App Intent (see plugins/withSaraAppIntents.js) can't open a URL on iOS 16
 * (OpenURLIntent needs iOS 18), so instead it stashes the prompt in the App Group
 * and foregrounds the app via openAppWhenRun. We read & clear that prompt here and
 * route it into chat as a quick-reply (the same auto-send path push notifications use).
 *
 * Call `consumeSiriPrompt()` on launch and whenever the app becomes active.
 */
import { consumePendingSiriPrompt } from '../../modules/sara-native'
import { navigateToChat } from './navigation'

export function consumeSiriPrompt(): void {
  let prompt: string | null = null
  try {
    prompt = consumePendingSiriPrompt()
  } catch {
    return
  }
  if (prompt && prompt.trim()) {
    const message = prompt.trim()
    // Give navigation a tick to be ready (esp. on cold launch).
    setTimeout(() => {
      navigateToChat({
        quickReply: { message, nudgeType: 'siri', title: 'Ask Sara' },
      })
    }, 350)
  }
}
