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
 * TodayBrief — the Sara tab. Presence-first daily brief.
 *
 * A centered presence hero (orb + greeting + Sara's first-person thought) sits
 * above a prioritized stack: what's next (with countdown), an at-a-glance row,
 * and a "needs you" group (open threads, reviews due) that the old flat
 * card-stack buried. All from /api/sara/brief. Depth lives behind Chat / tabs.
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

function humanizeState(state?: string): string {
  if (!state || state === 'unknown') return ''
  return state.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
}

// A compact at-a-glance tile.
function GlanceTile({
  icon,
  label,
  value,
  sub,
  onPress,
}: {
  icon: keyof typeof Ionicons.glyphMap
  label: string
  value: string
  sub?: string
  onPress?: () => void
}) {
  return (
    <TouchableOpacity style={styles.tile} onPress={onPress} activeOpacity={0.8} disabled={!onPress}>
      <Ionicons name={icon} size={18} color={colors.primary} />
      <Text style={styles.tileValue} numberOfLines={1}>{value}</Text>
      <Text style={styles.tileLabel} numberOfLines={1}>{sub || label}</Text>
    </TouchableOpacity>
  )
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
  const calendar = sections.find((s) => s.type === 'calendar')?.data
  const events = calendar?.events || []
  const nextEvent = events[0]
  const moreEvents = Math.max(0, (calendar?.count || events.length) - 1)
  const fitness = sections.find((s) => s.type === 'fitness')?.data
  const threads = sections.find((s) => s.type === 'threads')?.data
  const learning = sections.find((s) => s.type === 'learning')?.data
  const status = brief?.sara_status
  const actions = brief?.suggested_actions || []
  const stateLabel = humanizeState(brief?.activity_state)
  const needsYou = Boolean(threads?.open || learning?.reviews_due)

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
        {/* Presence hero */}
        <View style={styles.hero}>
          <SaraOrb size={96} />
          <Text style={styles.greeting}>{brief?.greeting || 'Hello'}</Text>
          {(stateLabel || status?.emotional_state) ? (
            <Text style={styles.subline}>
              {[stateLabel, status?.emotional_state].filter(Boolean).join(' · ')}
            </Text>
          ) : null}
          {status?.latest_thought ? (
            <Text style={styles.thought}>“{status.latest_thought}”</Text>
          ) : null}
          <TouchableOpacity style={styles.talkBtn} onPress={() => navigateToChat()} activeOpacity={0.85}>
            <Ionicons name="chatbubble-ellipses-outline" size={17} color={colors.primary} />
            <Text style={styles.talkText}>Talk to Sara</Text>
          </TouchableOpacity>
        </View>

        {/* Next up — the day's most relevant moment */}
        {nextEvent ? (
          <TouchableOpacity style={styles.nextCard} onPress={() => navigation?.navigate('Calendar')} activeOpacity={0.85}>
            <View style={styles.nextIcon}>
              <Ionicons name="calendar-outline" size={20} color={colors.primary} />
            </View>
            <View style={styles.nextBody}>
              <Text style={styles.kicker}>
                NEXT UP{calendar?.next_in_minutes != null ? ` · ${formatMins(calendar.next_in_minutes).toUpperCase()}` : ''}
              </Text>
              <Text style={styles.nextTitle} numberOfLines={1}>{nextEvent.title || 'Event'}</Text>
              <Text style={styles.cardSub}>
                {nextEvent.all_day ? 'All day' : formatTime(nextEvent.start_time)}
                {nextEvent.calendar_label ? ` · ${nextEvent.calendar_label}` : ''}
              </Text>
            </View>
            {moreEvents > 0 ? (
              <Text style={styles.morePill}>+{moreEvents}</Text>
            ) : null}
          </TouchableOpacity>
        ) : null}

        {/* At a glance */}
        {(fitness || moreEvents > 0) ? (
          <View style={styles.glanceRow}>
            {fitness ? (
              <GlanceTile
                icon="flame-outline"
                label="Today"
                value={`${Math.round(fitness.calories_today || 0)} / ${fitness.goal || 0}`}
                sub={`${Math.round(fitness.protein_today || 0)}g protein`}
                onPress={() => navigation?.navigate('Fitness')}
              />
            ) : null}
            {fitness?.last_meal_ago_hours != null ? (
              <GlanceTile
                icon="restaurant-outline"
                label="Last meal"
                value={`${fitness.last_meal_ago_hours}h`}
                sub="since eating"
                onPress={() => navigation?.navigate('Fitness')}
              />
            ) : moreEvents > 0 ? (
              <GlanceTile
                icon="calendar-outline"
                label="Schedule"
                value={`${(calendar?.count || events.length)}`}
                sub="events today"
                onPress={() => navigation?.navigate('Calendar')}
              />
            ) : null}
          </View>
        ) : null}

        {/* Needs you */}
        {needsYou ? (
          <View style={styles.group}>
            <Text style={styles.groupLabel}>NEEDS YOU</Text>
            {threads?.open ? (
              <TouchableOpacity style={styles.needRow} onPress={() => navigation?.navigate('AssistantInboxTab')} activeOpacity={0.8}>
                <Ionicons name="chatbox-ellipses-outline" size={18} color={colors.primary} />
                <Text style={styles.needText} numberOfLines={1}>
                  {threads.open} open thread{threads.open === 1 ? '' : 's'}
                  {threads.topics?.length ? ` · ${threads.topics.slice(0, 2).join(', ')}` : ''}
                </Text>
                <Ionicons name="chevron-forward" size={16} color={colors.textMuted} />
              </TouchableOpacity>
            ) : null}
            {learning?.reviews_due ? (
              <TouchableOpacity
                style={styles.needRow}
                onPress={() => navigateToChat({ quickReply: { message: 'Quiz me on what I have due', title: 'Reviews' } })}
                activeOpacity={0.8}
              >
                <Ionicons name="school-outline" size={18} color={colors.primary} />
                <Text style={styles.needText} numberOfLines={1}>
                  {learning.reviews_due} review{learning.reviews_due === 1 ? '' : 's'} due
                </Text>
                <Ionicons name="chevron-forward" size={16} color={colors.textMuted} />
              </TouchableOpacity>
            ) : null}
          </View>
        ) : null}

        {/* Quick actions */}
        {actions.length > 0 ? (
          <View style={styles.chips}>
            {actions.map((a: any, i: number) => (
              <TouchableOpacity
                key={`${a.label}-${i}`}
                style={styles.chip}
                onPress={() => navigateToChat({ quickReply: { message: a.message, title: 'Today' } })}
                activeOpacity={0.8}
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
  content: { padding: 16, paddingBottom: 36 },

  // Presence hero
  hero: { alignItems: 'center', paddingTop: 12, paddingBottom: 8 },
  greeting: { color: colors.text, fontSize: 26, fontWeight: '700', marginTop: 14 },
  subline: { color: colors.textMuted, fontSize: 13, marginTop: 4, textTransform: 'capitalize' },
  thought: {
    color: colors.textSecondary,
    fontSize: 15,
    fontStyle: 'italic',
    textAlign: 'center',
    marginTop: 12,
    lineHeight: 22,
    paddingHorizontal: 8,
  },
  talkBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 7,
    marginTop: 16,
    paddingHorizontal: 18,
    paddingVertical: 10,
    borderRadius: 22,
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.border,
  },
  talkText: { color: colors.primary, fontSize: 15, fontWeight: '600' },

  // Next up
  nextCard: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: colors.surface,
    borderRadius: 16,
    padding: 14,
    marginTop: 22,
    borderWidth: 1,
    borderColor: colors.border,
  },
  nextIcon: {
    width: 40,
    height: 40,
    borderRadius: 12,
    backgroundColor: colors.background,
    alignItems: 'center',
    justifyContent: 'center',
    marginRight: 12,
  },
  nextBody: { flex: 1, minWidth: 0 },
  nextTitle: { color: colors.text, fontSize: 17, fontWeight: '600', marginTop: 2 },
  morePill: {
    color: colors.textMuted,
    fontSize: 13,
    fontWeight: '600',
    backgroundColor: colors.background,
    borderRadius: 12,
    paddingHorizontal: 9,
    paddingVertical: 3,
    overflow: 'hidden',
    marginLeft: 8,
  },

  // Glance row
  glanceRow: { flexDirection: 'row', gap: 10, marginTop: 10 },
  tile: {
    flex: 1,
    backgroundColor: colors.surface,
    borderRadius: 16,
    padding: 14,
    borderWidth: 1,
    borderColor: colors.border,
  },
  tileValue: { color: colors.text, fontSize: 18, fontWeight: '700', marginTop: 8 },
  tileLabel: { color: colors.textMuted, fontSize: 12, marginTop: 2 },

  // Needs you
  group: { marginTop: 22 },
  groupLabel: { color: colors.textMuted, fontSize: 11, fontWeight: '700', letterSpacing: 0.8, marginBottom: 8, marginLeft: 2 },
  needRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
    backgroundColor: colors.surface,
    borderRadius: 14,
    padding: 14,
    marginBottom: 8,
    borderWidth: 1,
    borderColor: colors.border,
  },
  needText: { flex: 1, color: colors.text, fontSize: 15 },

  // Shared
  kicker: { color: colors.textMuted, fontSize: 11, fontWeight: '700', letterSpacing: 0.8 },
  cardSub: { color: colors.textMuted, fontSize: 14, marginTop: 3 },

  // Quick actions
  chips: { flexDirection: 'row', flexWrap: 'wrap', marginTop: 22, gap: 8 },
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
