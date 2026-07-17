// MuscleMap — a stylized front-facing body that highlights the muscle groups a
// workout targets (the anatomical graphic in the Train mockup). Built with
// react-native-svg so it renders with no native rebuild. It's an indicator, not
// a medical diagram: back-only groups (lats, triceps, hamstrings) are mapped onto
// the nearest visible front region so a Pull/Push/Leg day still reads at a glance.
import React from 'react';
import Svg, { Ellipse, Path, Circle, G } from 'react-native-svg';
import { colors } from '../../../styles/theme';

export type MuscleKey =
  | 'traps'
  | 'shoulders'
  | 'chest'
  | 'arms'      // biceps/triceps (upper arm)
  | 'forearms'
  | 'abs'
  | 'quads'
  | 'calves';

interface MuscleMapProps {
  highlighted: Set<MuscleKey> | MuscleKey[];
  width?: number;
  height?: number;
  activeColor?: string;
}

const VB_W = 100;
const VB_H = 150;

export default function MuscleMap({ highlighted, width = 96, height = 140, activeColor = colors.primary }: MuscleMapProps) {
  const set = highlighted instanceof Set ? highlighted : new Set(highlighted);
  const base = colors.surfaceLight;
  const stroke = colors.border;
  const fillFor = (k: MuscleKey) => (set.has(k) ? activeColor : base);
  const opacityFor = (k: MuscleKey) => (set.has(k) ? 0.92 : 1);

  return (
    <Svg width={width} height={height} viewBox={`0 0 ${VB_W} ${VB_H}`}>
      {/* head + neck (non-muscle, neutral) */}
      <Circle cx={50} cy={13} r={9} fill={base} stroke={stroke} strokeWidth={1} />
      <Path d="M44 21 H56 V28 H44 Z" fill={base} stroke={stroke} strokeWidth={1} />

      {/* traps */}
      <Path
        d="M38 28 Q50 24 62 28 L58 36 Q50 33 42 36 Z"
        fill={fillFor('traps')}
        opacity={opacityFor('traps')}
        stroke={stroke}
        strokeWidth={1}
      />

      {/* shoulders (delts) */}
      <Ellipse cx={31} cy={37} rx={9} ry={7} fill={fillFor('shoulders')} opacity={opacityFor('shoulders')} stroke={stroke} strokeWidth={1} />
      <Ellipse cx={69} cy={37} rx={9} ry={7} fill={fillFor('shoulders')} opacity={opacityFor('shoulders')} stroke={stroke} strokeWidth={1} />

      {/* chest (pecs) */}
      <Path d="M42 37 Q50 35 50 35 L50 50 Q44 51 38 47 Q38 40 42 37 Z" fill={fillFor('chest')} opacity={opacityFor('chest')} stroke={stroke} strokeWidth={1} />
      <Path d="M58 37 Q50 35 50 35 L50 50 Q56 51 62 47 Q62 40 58 37 Z" fill={fillFor('chest')} opacity={opacityFor('chest')} stroke={stroke} strokeWidth={1} />

      {/* upper arms (biceps/triceps) */}
      <Ellipse cx={27} cy={52} rx={6} ry={11} fill={fillFor('arms')} opacity={opacityFor('arms')} stroke={stroke} strokeWidth={1} />
      <Ellipse cx={73} cy={52} rx={6} ry={11} fill={fillFor('arms')} opacity={opacityFor('arms')} stroke={stroke} strokeWidth={1} />

      {/* forearms */}
      <Ellipse cx={23} cy={72} rx={5} ry={10} fill={fillFor('forearms')} opacity={opacityFor('forearms')} stroke={stroke} strokeWidth={1} />
      <Ellipse cx={77} cy={72} rx={5} ry={10} fill={fillFor('forearms')} opacity={opacityFor('forearms')} stroke={stroke} strokeWidth={1} />

      {/* abs / core */}
      <Path d="M43 51 H57 Q58 64 50 70 Q42 64 43 51 Z" fill={fillFor('abs')} opacity={opacityFor('abs')} stroke={stroke} strokeWidth={1} />

      {/* pelvis (neutral) */}
      <Path d="M42 71 H58 L55 80 H45 Z" fill={base} stroke={stroke} strokeWidth={1} />

      {/* quads */}
      <Path d="M44 81 Q40 100 43 116 Q47 117 49 116 Q50 98 50 82 Z" fill={fillFor('quads')} opacity={opacityFor('quads')} stroke={stroke} strokeWidth={1} />
      <Path d="M56 81 Q60 100 57 116 Q53 117 51 116 Q50 98 50 82 Z" fill={fillFor('quads')} opacity={opacityFor('quads')} stroke={stroke} strokeWidth={1} />

      {/* knees (neutral) */}
      <Circle cx={45} cy={120} r={3.5} fill={base} stroke={stroke} strokeWidth={1} />
      <Circle cx={55} cy={120} r={3.5} fill={base} stroke={stroke} strokeWidth={1} />

      {/* calves */}
      <Ellipse cx={45} cy={134} rx={4.5} ry={11} fill={fillFor('calves')} opacity={opacityFor('calves')} stroke={stroke} strokeWidth={1} />
      <Ellipse cx={55} cy={134} rx={4.5} ry={11} fill={fillFor('calves')} opacity={opacityFor('calves')} stroke={stroke} strokeWidth={1} />
    </Svg>
  );
}

const KEYWORDS: Record<MuscleKey, string[]> = {
  traps: ['trap', 'shrug', 'back', 'lat', 'row', 'pull', 'rear delt', 'face pull'],
  shoulders: ['shoulder', 'delt', 'press', 'overhead', 'ohp', 'lateral raise', 'push', 'military'],
  chest: ['chest', 'pec', 'bench', 'fly', 'push', 'dip'],
  arms: ['bicep', 'tricep', 'curl', 'arm', 'pushdown', 'extension', 'skull', 'pull'],
  forearms: ['forearm', 'grip', 'wrist'],
  abs: ['ab', 'core', 'crunch', 'plank', 'oblique', 'leg raise'],
  quads: ['quad', 'squat', 'leg', 'lunge', 'leg press', 'glute', 'hamstring', 'deadlift', 'rdl'],
  calves: ['calf', 'calves', 'raise'],
};

/**
 * Derive highlighted muscle regions from a workout template — combines the
 * template name (e.g. "Push Day") with each exercise's name/muscle_group/target.
 */
export function musclesForWorkout(template: any | null | undefined): Set<MuscleKey> {
  const out = new Set<MuscleKey>();
  if (!template) return out;

  const haystacks: string[] = [];
  if (template.name) haystacks.push(String(template.name).toLowerCase());
  for (const ex of template.exercises || []) {
    if (ex?.name) haystacks.push(String(ex.name).toLowerCase());
    if (ex?.muscle_group) haystacks.push(String(ex.muscle_group).toLowerCase());
    if (ex?.target) haystacks.push(String(ex.target).toLowerCase());
  }
  const blob = haystacks.join(' | ');

  (Object.keys(KEYWORDS) as MuscleKey[]).forEach(key => {
    if (KEYWORDS[key].some(kw => blob.includes(kw))) out.add(key);
  });

  // "Calf raise" would otherwise also trip 'raise' under shoulders/abs; that's
  // fine — over-highlighting is harmless for a glanceable indicator.
  return out;
}
