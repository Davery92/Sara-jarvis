import React from 'react';
import TodayBrief from '../../components/sara/TodayBrief';

interface SaraScreenProps {
  navigation?: any;
  route?: any;
}

/**
 * Home tab. Redesigned into a clean daily brief (TodayBrief) — the old
 * dashboard (ACSStatusCard + SaraOverviewPanel) was too cluttered for a
 * personal assistant. Those components still exist for use elsewhere.
 */
export default function SaraScreen(props: SaraScreenProps) {
  return <TodayBrief navigation={props.navigation} />;
}
