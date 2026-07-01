import React, { useEffect, useState } from 'react';
import { View, Text, StyleSheet, ActivityIndicator } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { colors, spacing, borderRadius, fontSizes } from '../../styles/theme';
import { fitnessService, NutritionGuideData } from '../../services/fitness';

/**
 * The Forge — Recomp Nutrition Guide (iOS port of the web NutritionGuide).
 * Data-driven: fetches the structured guide stored on the active program
 * (set by the Plan Importer). Falls back to the built-in default below when
 * no guide has been imported yet.
 */

const DEFAULT_GUIDE: NutritionGuideData = {
  goal: 'recomp at a flat ~240 lbs — grow the chest, lean out elsewhere, hold strength.',
  how_it_works:
    'eat at maintenance on average (not a deficit), keep protein high, cycle carbs around training. Bodyweight stays steady while composition shifts.',
  weekly_average: '~2,630 cal/day — right around maintenance, so the scale holds flat.',
  macros: [
    { label: 'Calories', training: '~2,800', rest: '~2,400' },
    { label: 'Protein', training: '~240g', rest: '~240g' },
    { label: 'Carbs', training: '~280–300g', rest: '~150g' },
    { label: 'Fat', training: '~70g', rest: '~95g' },
  ],
  rules: [
    { title: 'Protein is the anchor — 240g every single day.', body: 'Training or rest, no exceptions. This is what lets you build chest tissue without gaining fat. (~960 cal/day from protein.)' },
    { title: 'Carbs cycle, fat fills the gap.', body: 'Training days go carb-heavy to fuel pressing volume; rest days drop carbs and let fat take over.' },
    { title: 'Eat at maintenance, not under.', body: 'A deficit would blunt the chest growth you are chasing. Hold the line at ~240 and let composition do the work.' },
  ],
  carb_timing: {
    days: 'Mon/Thu',
    pre: 'Oats or rice',
    post: 'A rice-heavy meal',
    note: 'Glycogen going in, a recovery window coming out — exactly when the pre-exhaust pec volume creates the most growth stimulus.',
  },
  staples: {
    carbs: 'jasmine rice, golf-ball potatoes, oats',
    protein: 'rotisserie chicken, chuck roast, 83% ground beef',
    watch_out: '83% beef runs fat-heavy — drain it well, keep portions ~5 oz so the rest-day fat budget does not blow out. On training days the extra fat matters less; on rest days, lean harder on chicken.',
  },
  self_check: [
    'Did I hit ~240g protein? (the one that matters most)',
    'Training day → more rice, less fat. Rest day → less rice, more fat.',
    'Are most of my carbs landing around the training sessions?',
    'Is the scale roughly flat week to week? (That means it is working — composition is moving underneath.)',
  ],
};

// Map a macro label to its themed icon (mirrors the web macroIcon helper).
const macroIcon = (label: string): { name: keyof typeof Ionicons.glyphMap; color: string } => {
  const l = label.toLowerCase();
  if (l.includes('cal')) return { name: 'flame', color: colors.fitness.calories };
  if (l.includes('protein')) return { name: 'nutrition', color: colors.hues.rose };
  if (l.includes('carb')) return { name: 'leaf', color: colors.accent };
  if (l.includes('fat')) return { name: 'water', color: colors.hues.cyan };
  return { name: 'ellipse', color: colors.textSecondary };
};

const Eyebrow: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <Text style={styles.eyebrow}>{children}</Text>
);

const NutritionGuide: React.FC = () => {
  const [guide, setGuide] = useState<NutritionGuideData>(DEFAULT_GUIDE);
  const [loading, setLoading] = useState(true);
  const [imported, setImported] = useState(false);

  useEffect(() => {
    let active = true;
    (async () => {
      try {
        const data = await fitnessService.getNutritionGuide();
        if (active && data?.guide) {
          setGuide({ ...DEFAULT_GUIDE, ...data.guide });
          setImported(true);
        }
      } catch {
        /* keep default */
      } finally {
        if (active) setLoading(false);
      }
    })();
    return () => { active = false; };
  }, []);

  if (loading) {
    return (
      <View style={styles.loading}>
        <ActivityIndicator size="large" color={colors.accent} />
      </View>
    );
  }

  const g = guide;
  const macros = g.macros?.length ? g.macros : DEFAULT_GUIDE.macros!;
  const rules = g.rules?.length ? g.rules : [];
  const checks = g.self_check?.length ? g.self_check : [];

  return (
    <View style={styles.wrap}>
      {/* Header */}
      <View>
        <Text style={styles.title}>Recomp Nutrition Guide</Text>
        {g.goal ? (
          <Text style={styles.subtitle}>
            <Text style={styles.subtitleStrong}>Goal: </Text>{g.goal}
          </Text>
        ) : null}
        {g.how_it_works ? (
          <Text style={styles.subtitle}>
            <Text style={styles.subtitleStrong}>How it works: </Text>{g.how_it_works}
          </Text>
        ) : null}
        {!imported ? (
          <Text style={styles.builtInNote}>
            Showing the built-in guide. Import a plan on the web app to replace this from a document.
          </Text>
        ) : null}
      </View>

      {/* Daily Targets */}
      <View style={styles.panel}>
        <Eyebrow>Daily Targets</Eyebrow>
        <View style={styles.table}>
          <View style={[styles.tableRow, styles.tableHead]}>
            <Text style={[styles.cell, styles.cellLabel]} />
            <Text style={[styles.cell, styles.cellTraining, styles.headText]}>Training</Text>
            <Text style={[styles.cell, styles.cellRest, styles.headText]}>Rest</Text>
          </View>
          {macros.map((m, i) => {
            const icon = macroIcon(m.label);
            return (
              <View key={m.label} style={[styles.tableRow, i % 2 === 1 && styles.tableRowAlt]}>
                <View style={[styles.cell, styles.cellLabel, styles.labelCell]}>
                  <Ionicons name={icon.name} size={14} color={icon.color} />
                  <Text style={styles.labelText}>{m.label}</Text>
                </View>
                <Text style={[styles.cell, styles.cellTraining, styles.valTraining]}>{m.training}</Text>
                <Text style={[styles.cell, styles.cellRest, styles.valRest]}>{m.rest}</Text>
              </View>
            );
          })}
        </View>
        {g.weekly_average ? (
          <Text style={styles.footnote}>
            <Text style={styles.footnoteStrong}>Weekly average: </Text>{g.weekly_average}
          </Text>
        ) : null}
      </View>

      {/* The Rules */}
      {rules.length > 0 ? (
        <View style={styles.panel}>
          <Eyebrow>The Rules</Eyebrow>
          <View style={{ marginTop: spacing.sm, gap: spacing.md }}>
            {rules.map((r, i) => (
              <View key={i} style={styles.ruleRow}>
                <View style={styles.ruleNum}>
                  <Text style={styles.ruleNumText}>{i + 1}</Text>
                </View>
                <View style={{ flex: 1 }}>
                  <Text style={styles.ruleTitle}>{r.title}</Text>
                  {r.body ? <Text style={styles.ruleBody}>{r.body}</Text> : null}
                </View>
              </View>
            ))}
          </View>
        </View>
      ) : null}

      {/* Carb Timing */}
      {g.carb_timing && (g.carb_timing.pre || g.carb_timing.post) ? (
        <View style={styles.panel}>
          <View style={styles.eyebrowRow}>
            <Ionicons name="time-outline" size={15} color={colors.accent} />
            <Eyebrow>Carb Timing</Eyebrow>
          </View>
          {g.carb_timing.days ? (
            <Text style={styles.bodyText}>
              On training days <Text style={styles.subtitleStrong}>({g.carb_timing.days})</Text>, put the bulk of carbs around the session:
            </Text>
          ) : null}
          <View style={styles.timingGrid}>
            {g.carb_timing.pre ? (
              <View style={styles.timingCard}>
                <Text style={styles.timingLabel}>Pre-workout</Text>
                <Text style={styles.timingValue}>{g.carb_timing.pre}</Text>
              </View>
            ) : null}
            {g.carb_timing.post ? (
              <View style={styles.timingCard}>
                <Text style={styles.timingLabel}>Post-workout</Text>
                <Text style={styles.timingValue}>{g.carb_timing.post}</Text>
              </View>
            ) : null}
          </View>
          {g.carb_timing.note ? <Text style={styles.note}>{g.carb_timing.note}</Text> : null}
        </View>
      ) : null}

      {/* Staples → Macros */}
      {g.staples && (g.staples.carbs || g.staples.protein || g.staples.watch_out) ? (
        <View style={styles.panel}>
          <Eyebrow>Staples → Macros</Eyebrow>
          <View style={{ marginTop: spacing.sm, gap: spacing.sm }}>
            {g.staples.carbs ? (
              <View style={styles.stapleRow}>
                <Ionicons name="leaf" size={14} color={colors.accent} style={styles.stapleIcon} />
                <Text style={styles.stapleText}>
                  <Text style={styles.subtitleStrong}>Carbs: </Text>
                  <Text style={styles.stapleMuted}>{g.staples.carbs}</Text>
                </Text>
              </View>
            ) : null}
            {g.staples.protein ? (
              <View style={styles.stapleRow}>
                <Ionicons name="nutrition" size={14} color={colors.hues.rose} style={styles.stapleIcon} />
                <Text style={styles.stapleText}>
                  <Text style={styles.subtitleStrong}>Protein: </Text>
                  <Text style={styles.stapleMuted}>{g.staples.protein}</Text>
                </Text>
              </View>
            ) : null}
            {g.staples.watch_out ? (
              <View style={[styles.stapleRow, styles.watchOut]}>
                <Ionicons name="warning" size={14} color={colors.warning} style={styles.stapleIcon} />
                <Text style={styles.stapleText}>
                  <Text style={styles.watchOutLabel}>Watch-out: </Text>
                  <Text style={styles.stapleMuted}>{g.staples.watch_out}</Text>
                </Text>
              </View>
            ) : null}
          </View>
        </View>
      ) : null}

      {/* Quick Self-Check */}
      {checks.length > 0 ? (
        <View style={styles.panel}>
          <View style={styles.eyebrowRow}>
            <Ionicons name="checkmark-circle-outline" size={15} color={colors.accent} />
            <Eyebrow>Quick Self-Check</Eyebrow>
          </View>
          <View style={{ marginTop: spacing.sm, gap: spacing.sm }}>
            {checks.map((c, i) => (
              <View key={i} style={styles.checkRow}>
                <Ionicons name="checkmark-circle" size={15} color={colors.accent} style={styles.checkIcon} />
                <Text style={styles.checkText}>{c}</Text>
              </View>
            ))}
          </View>
        </View>
      ) : null}
    </View>
  );
};

const styles = StyleSheet.create({
  loading: {
    paddingVertical: spacing.xxl,
    alignItems: 'center',
    justifyContent: 'center',
  },
  wrap: {
    paddingHorizontal: spacing.md,
    paddingBottom: spacing.xxl,
    gap: spacing.md,
  },
  title: {
    color: colors.text,
    fontSize: fontSizes.xxl,
    fontWeight: '700',
  },
  subtitle: {
    color: colors.textSecondary,
    fontSize: fontSizes.sm,
    marginTop: spacing.xs,
    lineHeight: 20,
  },
  subtitleStrong: {
    color: colors.text,
    fontWeight: '600',
  },
  builtInNote: {
    color: colors.textMuted,
    fontSize: fontSizes.xs,
    fontStyle: 'italic',
    marginTop: spacing.sm,
  },
  panel: {
    backgroundColor: colors.surface,
    borderRadius: borderRadius.lg,
    borderWidth: 1,
    borderColor: colors.border,
    padding: spacing.md,
  },
  eyebrow: {
    color: colors.accent,
    fontSize: fontSizes.xs,
    fontWeight: '700',
    textTransform: 'uppercase',
    letterSpacing: 0.5,
  },
  eyebrowRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.xs,
  },
  // Daily targets table
  table: {
    marginTop: spacing.sm,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: borderRadius.md,
    overflow: 'hidden',
  },
  tableRow: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: spacing.sm,
    paddingHorizontal: spacing.sm,
  },
  tableRowAlt: {
    backgroundColor: 'rgba(255,255,255,0.02)',
  },
  tableHead: {
    backgroundColor: 'rgba(255,255,255,0.05)',
  },
  cell: {
    fontSize: fontSizes.sm,
  },
  cellLabel: {
    flex: 1.4,
  },
  cellTraining: {
    flex: 1,
    textAlign: 'right',
  },
  cellRest: {
    flex: 1,
    textAlign: 'right',
  },
  headText: {
    fontWeight: '600',
  },
  labelCell: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.xs,
  },
  labelText: {
    color: colors.text,
    fontSize: fontSizes.sm,
    fontWeight: '600',
  },
  valTraining: {
    color: colors.text,
    fontWeight: '600',
  },
  valRest: {
    color: colors.textSecondary,
  },
  footnote: {
    color: colors.textSecondary,
    fontSize: fontSizes.xs,
    marginTop: spacing.sm,
    lineHeight: 18,
  },
  footnoteStrong: {
    color: colors.text,
    fontWeight: '600',
  },
  // Rules
  ruleRow: {
    flexDirection: 'row',
    gap: spacing.sm,
  },
  ruleNum: {
    width: 26,
    height: 26,
    borderRadius: borderRadius.full,
    backgroundColor: 'rgba(20, 184, 166, 0.15)',
    borderWidth: 1,
    borderColor: 'rgba(94, 234, 212, 0.3)',
    alignItems: 'center',
    justifyContent: 'center',
  },
  ruleNumText: {
    color: colors.accent,
    fontSize: fontSizes.sm,
    fontWeight: '700',
  },
  ruleTitle: {
    color: colors.text,
    fontSize: fontSizes.sm,
    fontWeight: '600',
  },
  ruleBody: {
    color: colors.textSecondary,
    fontSize: fontSizes.sm,
    marginTop: 2,
    lineHeight: 19,
  },
  // Carb timing
  bodyText: {
    color: colors.textSecondary,
    fontSize: fontSizes.sm,
    marginTop: spacing.sm,
    lineHeight: 20,
  },
  timingGrid: {
    flexDirection: 'row',
    gap: spacing.sm,
    marginTop: spacing.sm,
  },
  timingCard: {
    flex: 1,
    backgroundColor: 'rgba(255,255,255,0.05)',
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: borderRadius.md,
    padding: spacing.md,
  },
  timingLabel: {
    color: colors.accent,
    fontSize: fontSizes.xs,
    fontWeight: '700',
    textTransform: 'uppercase',
    letterSpacing: 0.5,
  },
  timingValue: {
    color: colors.text,
    fontSize: fontSizes.sm,
    marginTop: spacing.xs,
  },
  note: {
    color: colors.textMuted,
    fontSize: fontSizes.xs,
    marginTop: spacing.sm,
    lineHeight: 18,
  },
  // Staples
  stapleRow: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: spacing.xs,
  },
  stapleIcon: {
    marginTop: 2,
  },
  stapleText: {
    flex: 1,
    fontSize: fontSizes.sm,
    lineHeight: 19,
  },
  stapleMuted: {
    color: colors.textSecondary,
  },
  watchOut: {
    backgroundColor: 'rgba(251, 191, 36, 0.06)',
    borderWidth: 1,
    borderColor: 'rgba(251, 191, 36, 0.2)',
    borderRadius: borderRadius.md,
    padding: spacing.sm,
  },
  watchOutLabel: {
    color: colors.warning,
    fontWeight: '600',
  },
  // Self-check
  checkRow: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: spacing.xs,
  },
  checkIcon: {
    marginTop: 2,
  },
  checkText: {
    flex: 1,
    color: colors.text,
    fontSize: fontSizes.sm,
    lineHeight: 19,
  },
});

export default NutritionGuide;
