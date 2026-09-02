import * as Notifications from 'expo-notifications'
import * as TaskManager from 'expo-task-manager'
import { refreshWidgetData } from './widgetBridge'

export const PRESENCE_BACKGROUND_TASK = 'sara-world-presence-refresh'

// Must be defined at module scope so iOS can launch it without mounting React.
if (!TaskManager.isTaskDefined(PRESENCE_BACKGROUND_TASK)) {
  TaskManager.defineTask(PRESENCE_BACKGROUND_TASK, async ({ data, error }) => {
    if (error) return
    const payload: any = data || {}
    const notificationData =
      payload?.notification?.request?.content?.data ||
      payload?.data ||
      payload
    if (notificationData?.type === 'world_presence_update') {
      await refreshWidgetData()
    }
  })
}

export async function registerPresenceBackgroundTask(): Promise<void> {
  try {
    const registered = await TaskManager.isTaskRegisteredAsync(PRESENCE_BACKGROUND_TASK)
    if (!registered) await Notifications.registerTaskAsync(PRESENCE_BACKGROUND_TASK)
  } catch (error) {
    console.warn('[PresenceBackgroundTask] registration failed:', error)
  }
}
