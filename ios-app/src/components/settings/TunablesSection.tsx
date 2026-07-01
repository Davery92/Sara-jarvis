import React, { useState, useEffect, useMemo, useCallback } from 'react';
import {
  View,
  Text,
  StyleSheet,
  TouchableOpacity,
  TextInput,
  ActivityIndicator,
  Alert,
} from 'react-native';
import { apiClient, TunableSetting } from '../../services/api';
import { colors, spacing, fontSizes, borderRadius } from '../../styles/theme';

const CATEGORY_LABELS: Record<string, string> = {
  notifications: 'Notifications & Quiet Hours',
  acs: 'Autonomous Cognition Thresholds',
  morning_brief: 'Morning Brief',
};

interface RowProps {
  tunable: TunableSetting;
  onSave: (value: any) => Promise<void>;
  onReset: () => Promise<void>;
}

function TunableRow({ tunable, onSave, onReset }: RowProps) {
  const [draft, setDraft] = useState<string>(String(tunable.value ?? ''));
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    setDraft(String(tunable.value ?? ''));
  }, [tunable.value]);

  const dirty = draft !== String(tunable.value ?? '');
  const isDefault =
    JSON.stringify(tunable.value) === JSON.stringify(tunable.default_value);

  const handleSave = async () => {
    setSaving(true);
    try {
      let parsed: any = draft;
      if (tunable.value_type === 'int') parsed = parseInt(draft, 10);
      else if (tunable.value_type === 'float') parsed = parseFloat(draft);
      else if (tunable.value_type === 'bool') parsed = draft === 'true';
      await onSave(parsed);
    } catch (e: any) {
      const detail = e?.response?.data?.detail || e?.message || 'Save failed';
      Alert.alert('Save failed', String(detail));
    } finally {
      setSaving(false);
    }
  };

  const handleReset = async () => {
    setSaving(true);
    try {
      await onReset();
    } finally {
      setSaving(false);
    }
  };

  const isNumeric = tunable.value_type === 'int' || tunable.value_type === 'float';

  return (
    <View style={styles.row}>
      <View style={styles.rowHeader}>
        <Text style={styles.rowTitle} numberOfLines={1}>
          {tunable.display_name}
          {!isDefault && <Text style={styles.modifiedBadge}>  MODIFIED</Text>}
        </Text>
      </View>
      {tunable.description && (
        <Text style={styles.rowDescription}>{tunable.description}</Text>
      )}
      <View style={styles.inputRow}>
        <TextInput
          value={draft}
          onChangeText={setDraft}
          keyboardType={isNumeric ? 'decimal-pad' : 'default'}
          autoCapitalize="none"
          autoCorrect={false}
          style={[styles.input, isNumeric && styles.inputNumeric]}
        />
        {tunable.unit && <Text style={styles.unit}>{tunable.unit}</Text>}
        <TouchableOpacity
          onPress={handleSave}
          disabled={!dirty || saving}
          style={[styles.saveButton, (!dirty || saving) && styles.saveButtonDisabled]}
        >
          <Text style={styles.saveButtonText}>Save</Text>
        </TouchableOpacity>
        {!isDefault && (
          <TouchableOpacity
            onPress={handleReset}
            disabled={saving}
            style={styles.resetButton}
          >
            <Text style={styles.resetButtonText}>Reset</Text>
          </TouchableOpacity>
        )}
      </View>
      {(tunable.min_value !== null || tunable.max_value !== null) && (
        <Text style={styles.bounds}>
          {tunable.min_value !== null ? `min ${tunable.min_value}` : ''}
          {tunable.min_value !== null && tunable.max_value !== null ? ' · ' : ''}
          {tunable.max_value !== null ? `max ${tunable.max_value}` : ''}
          {' · default '}
          {JSON.stringify(tunable.default_value)}
        </Text>
      )}
    </View>
  );
}

export default function TunablesSection() {
  const [tunables, setTunables] = useState<TunableSetting[]>([]);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    try {
      setLoading(true);
      const data = await apiClient.listTunables();
      setTunables(data);
    } catch (e) {
      console.error('Failed to load tunables', e);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const handleSave = async (key: string, value: any) => {
    await apiClient.updateTunable(key, value);
    await load();
  };

  const handleReset = async (key: string) => {
    await apiClient.resetTunable(key);
    await load();
  };

  const grouped = useMemo(() => {
    const map = new Map<string, TunableSetting[]>();
    for (const t of tunables) {
      if (!map.has(t.category)) map.set(t.category, []);
      map.get(t.category)!.push(t);
    }
    return Array.from(map.entries()).sort(([a], [b]) => a.localeCompare(b));
  }, [tunables]);

  return (
    <View style={styles.section}>
      <Text style={styles.sectionTitle}>Behavior Tunables</Text>
      <Text style={styles.settingHint}>
        Notification cooldowns, quiet hours, ACS thresholds, brief tone & length. Changes take effect within ~60 seconds.
      </Text>

      {loading && tunables.length === 0 ? (
        <ActivityIndicator size="small" color={colors.primary} style={{ marginTop: spacing.md }} />
      ) : (
        grouped.map(([category, items]) => (
          <View key={category} style={{ marginTop: spacing.md }}>
            <Text style={styles.categoryHeader}>
              {(CATEGORY_LABELS[category] ?? category).toUpperCase()}
            </Text>
            {items.map((t) => (
              <TunableRow
                key={t.key}
                tunable={t}
                onSave={(v) => handleSave(t.key, v)}
                onReset={() => handleReset(t.key)}
              />
            ))}
          </View>
        ))
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  section: {
    backgroundColor: colors.surface,
    marginHorizontal: spacing.md,
    marginBottom: spacing.md,
    padding: spacing.md,
    borderRadius: borderRadius.lg,
  },
  sectionTitle: {
    fontSize: fontSizes.lg,
    fontWeight: '600',
    color: colors.text,
    marginBottom: spacing.xs,
  },
  settingHint: {
    fontSize: fontSizes.xs,
    color: colors.textSecondary,
  },
  categoryHeader: {
    fontSize: fontSizes.xs,
    color: colors.textMuted,
    fontWeight: '600',
    letterSpacing: 1,
    marginBottom: spacing.xs,
  },
  row: {
    backgroundColor: colors.background,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: borderRadius.md,
    padding: spacing.sm,
    marginBottom: spacing.xs,
  },
  rowHeader: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  rowTitle: {
    fontSize: fontSizes.sm,
    color: colors.text,
    fontWeight: '500',
    flex: 1,
  },
  modifiedBadge: {
    fontSize: 9,
    color: colors.warning,
    fontWeight: '700',
  },
  rowDescription: {
    fontSize: fontSizes.xs,
    color: colors.textSecondary,
    marginTop: 2,
  },
  inputRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.xs,
    marginTop: spacing.sm,
  },
  input: {
    flex: 1,
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: borderRadius.sm,
    paddingHorizontal: spacing.sm,
    paddingVertical: 6,
    color: colors.text,
    fontSize: fontSizes.sm,
  },
  inputNumeric: {
    flex: 0,
    width: 100,
    fontFamily: 'Menlo',
  },
  unit: {
    fontSize: fontSizes.xs,
    color: colors.textMuted,
  },
  saveButton: {
    backgroundColor: colors.primary,
    paddingHorizontal: spacing.sm,
    paddingVertical: 6,
    borderRadius: borderRadius.sm,
  },
  saveButtonDisabled: {
    opacity: 0.3,
  },
  saveButtonText: {
    color: colors.text,
    fontSize: fontSizes.xs,
    fontWeight: '600',
  },
  resetButton: {
    backgroundColor: colors.surfaceLight,
    borderWidth: 1,
    borderColor: colors.border,
    paddingHorizontal: spacing.sm,
    paddingVertical: 6,
    borderRadius: borderRadius.sm,
  },
  resetButtonText: {
    color: colors.text,
    fontSize: fontSizes.xs,
  },
  bounds: {
    fontSize: 10,
    color: colors.textMuted,
    fontFamily: 'Menlo',
    marginTop: 4,
  },
});
