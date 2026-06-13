import { SettingsTabPanel } from "@/components/settings-tab-panel";
import { SETTINGS_TABS, type SettingsTab } from "@/lib/settings-tabs";

export const dynamicParams = false;

export function generateStaticParams() {
  return SETTINGS_TABS.map((tab) => ({ tab }));
}

export default async function SettingsTabPage({ params }: { params: Promise<{ tab: string }> }) {
  const { tab } = await params;
  return <SettingsTabPanel tab={tab as SettingsTab} />;
}
