import React, { useState, useEffect, useCallback } from 'react'
import {
  View,
  Text,
  ScrollView,
  TouchableOpacity,
  StyleSheet,
  RefreshControl,
  ActivityIndicator,
} from 'react-native'
import { SafeAreaView } from 'react-native-safe-area-context'
import { Ionicons } from '@expo/vector-icons'
import { apiClient } from '../../services/api'
import { navigateToChat } from '../../services/navigation'
import SaraOrb from './SaraOrb'
import { colors } from '../../styles/theme'

/**
 * TodayBrief — the clean, focused iOS home (replaces the cluttered dashboard).
 *
 * A personal-assistant home: Sara's presence + greeting, what's next, a quick
 * fitness glance, and time-aware quick actions. All from the existing
 * /api/sara/brief endpoint. Everything deeper lives behind Chat / More.
 */

interface BriefSection {
  type: string
  data: any
}

function formatTime(iso?: string): string {
  if (!iso) return ''
  try {
    return new Date(iso).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })
  } catch {
    return ''
  }
}

function formatMins(mins?: number | null): string {
  if (mins == null) return ''
  if (mins < 60) return `in ${mins}m`
  const h = Math.floor(mins / 60)
  const m = mins % 60
  return m ? `in ${h}h ${m}m` : `in ${h}h`
}

export default function TodayBrief({ navigation }: { navigation?: any }) {
  const [brief, setBrief] = useState<any | null>(null)
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)

  const load = useCallback(async () => {
    try {
      const data = await apiClient.get<any>('/api/sara/brief')
      setBrief(data)
    } catch {
      /* keep last */
    } finally {
      setLoading(false)
      setRefreshing(false)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const sections: BriefSection[] = brief?.brief_sections || []
  const calendar = sections.find((s) => s.type === 'calendar')
  const nextEvent = calendar?.data?.events?.[0]
  const fitness = sections.find((s) => s.type === 'fitness')?.data
  const threads = sections.find((s) => s.type === 'threads')?.data
  const status = brief?.sara_status
  const actions = brief?.suggested_actions || []

  return (
    <SafeAreaView style={styles.container} edges={['top']}>
      <ScrollView
        contentContainerStyle={styles.content}
        refreshControl={
          <RefreshControl
            refreshing={refreshing}
            onRefresh={() => {
              setRefreshing(true)
              load()
            }}
            tintColor={colors.textMuted}
          />
        }
      >
        {/* Presence + greeting */}
        <View style={styles.header}>
          <SaraOrb size={52} />
          <View style={styles.headerText}>
            <Text style={styles.greeting}>{brief?.greeting || 'Hello'}</Text>
            {status?.emotional_state ? (
              <Text style={styles.mood}>{status.emotional_state}</Text>
            ) : null}
          </View>
          <TouchableOpacity onPress={() => navigateToChat()} style={styles.chatBtn}>
            <Ionicons name="chatbubble-ellipses-outline" size={22} color={colors.primary} />
          </TouchableOpacity>
        </View>

        {status?.latest_thought ? (
          <Text style={styles.thought}>“{status.latest_thought}”</Text>
        ) : null}

        {/* Next up */}
        {nextEvent ? (
          <TouchableOpacity style={styles.card} onPress={() => navigation?.navigate('Calendar')}>
            <Text style={styles.kicker}>NEXT UP</Text>
            <Text style={styles.cardTitle}>{nextEvent.title || 'Event'}</Text>
            <Text style={styles.cardSub}>
              {formatTime(nextEvent.start_time)}
              {calendar?.data?.next_in_minutes != null ? ` · ${formatMins(calendar.data.next_in_minutes)}` : ''}
            </Text>
          </TouchableOpacity>
        ) : null}

        {/* Fitness glance */}
        {fitness ? (
          <TouchableOpacity style={styles.card} onPress={() => navigation?.navigate('Fitness')}>
            <Text style={styles.kicker}>TODAY</Text>
            <Text style={styles.cardSub}>
              {Math.round(fitness.calories_today || 0)} / {fitness.goal || 0} cal · {Math.round(fitness.protein_today || 0)}g protein
            </Text>
          </TouchableOpacity>
        ) : null}

        {/* Open threads */}
        {threads?.open ? (
          <TouchableOpacity style={styles.card} onPress={() => navigation?.navigate('AssistantInboxTab')}>
            <Text style={styles.kicker}>OPEN WITH SARA</Text>
            <Text style={styles.cardSub}>
              {threads.open} thread{threads.open === 1 ? '' : 's'}
              {threads.topics?.length ? ` · ${threads.topics.slice(0, 2).join(', ')}` : ''}
            </Text>
          </TouchableOpacity>
        ) : null}

        {/* Quick actions */}
        {actions.length > 0 ? (
          <View style={styles.chips}>
            {actions.map((a: any, i: number) => (
              <TouchableOpacity
                key={`${a.label}-${i}`}
                style={styles.chip}
                onPress={() => navigateToChat({ quickReply: { message: a.message, title: 'Today' } })}
              >
                <Text style={styles.chipText}>{a.label}</Text>
              </TouchableOpacity>
            ))}
          </View>
        ) : null}

        {loading && !brief ? (
          <ActivityIndicator color={colors.primary} style={{ marginTop: 48 }} />
        ) : null}
      </ScrollView>
    </SafeAreaView>
  )
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.background },
  content: { padding: 16, paddingBottom: 32 },
  header: { flexDirection: 'row', alignItems: 'center', marginBottom: 8 },
  headerText: { flex: 1, marginLeft: 14 },
  greeting: { color: colors.text, fontSize: 22, fontWeight: '700' },
  mood: { color: colors.textMuted, fontSize: 13, marginTop: 2, textTransform: 'capitalize' },
  chatBtn: {
    width: 40,
    height: 40,
    borderRadius: 20,
    backgroundColor: colors.surface,
    justifyContent: 'center',
    alignItems: 'center',
  },
  thought: { color: colors.textMuted, fontSize: 14, fontStyle: 'italic', marginTop: 4, marginBottom: 8, lineHeight: 20 },
  card: {
    backgroundColor: colors.surface,
    borderRadius: 16,
    padding: 14,
    marginTop: 10,
  },
  kicker: { color: colors.textMuted, fontSize: 11, fontWeight: '700', letterSpacing: 0.8, marginBottom: 4 },
  cardTitle: { color: colors.text, fontSize: 17, fontWeight: '600' },
  cardSub: { color: colors.textMuted, fontSize: 14, marginTop: 2 },
  chips: { flexDirection: 'row', flexWrap: 'wrap', marginTop: 16, gap: 8 },
  chip: {
    backgroundColor: colors.surface,
    borderRadius: 20,
    paddingHorizontal: 14,
    paddingVertical: 9,
    borderWidth: 1,
    borderColor: colors.border,
  },
  chipText: { color: colors.text, fontSize: 14 },
})
