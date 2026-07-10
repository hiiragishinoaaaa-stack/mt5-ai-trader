import { useEffect, useState } from "react";
import { getSettings, updateSettings } from "../api/client";
import type { SettingsState } from "../types";
import { Header } from "../components/Header";
import { PageShell, PageTitle } from "../components/PageShell";
import { Card } from "../components/Card";
import { Skeleton } from "../components/Skeleton";
import { PillGroup, SettingsSection, TextField, ToggleRow } from "../components/settings/fields";
import { TradingSettings } from "../components/settings/TradingSettings";
import { BellIcon, CpuIcon, LinkIcon, MessageIcon, ServerIcon } from "../components/icons";
import { Button } from "../components/Button";

export function SettingsPage() {
  const [settings, setSettings] = useState<SettingsState | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    getSettings().then((s) => {
      setSettings(s);
      setLoading(false);
    });
  }, []);

  function patch(update: (prev: SettingsState) => SettingsState) {
    setSettings((prev) => {
      if (!prev) return prev;
      const next = update(prev);
      void updateSettings(next);
      return next;
    });
  }

  return (
    <PageShell>
      <Header />
      <PageTitle sub="売買設定・Discord・VPS・通知・MT5の設定">Settings</PageTitle>

      {/* 売買設定(AI判断ロジック / 発注設定)だけがPython側と実際に接続されている。 */}
      <TradingSettings />

      <div className="mt-6 flex flex-col gap-4">
        {loading || !settings ? (
          [0, 1, 2, 3].map((i) => (
            <Card key={i}>
              <Skeleton className="h-28 w-full" />
            </Card>
          ))
        ) : (
          <>
            <SettingsSection icon={<MessageIcon className="h-4 w-4" />} title="Discord">
              <ToggleRow
                label="Discord連携を有効にする"
                description="AIの判断・発注結果をDiscordへ送信します"
                checked={settings.discord.enabled}
                onChange={(v) => patch((p) => ({ ...p, discord: { ...p.discord, enabled: v } }))}
              />
              <TextField
                label="Webhook URL"
                mono
                value={settings.discord.webhookUrl}
                onChange={(v) => patch((p) => ({ ...p, discord: { ...p.discord, webhookUrl: v } }))}
                placeholder="https://discord.com/api/webhooks/..."
              />
            </SettingsSection>

            <SettingsSection icon={<BellIcon className="h-4 w-4" />} title="通知">
              <ToggleRow
                label="取引ごとに通知"
                description="発注・決済のたびに通知します"
                checked={settings.discord.notifyOnTrade}
                onChange={(v) => patch((p) => ({ ...p, discord: { ...p.discord, notifyOnTrade: v } }))}
              />
              <ToggleRow
                label="エラー通知"
                description="接続エラーや発注失敗を通知します"
                checked={settings.discord.notifyOnError}
                onChange={(v) => patch((p) => ({ ...p, discord: { ...p.discord, notifyOnError: v } }))}
              />
              <ToggleRow
                label="日次サマリー"
                description="1日の損益をまとめて通知します"
                checked={settings.discord.notifyOnDailySummary}
                onChange={(v) => patch((p) => ({ ...p, discord: { ...p.discord, notifyOnDailySummary: v } }))}
              />
            </SettingsSection>

            <SettingsSection icon={<ServerIcon className="h-4 w-4" />} title="VPS">
              <TextField
                label="Host"
                mono
                value={settings.vps.host}
                onChange={(v) => patch((p) => ({ ...p, vps: { ...p.vps, host: v } }))}
              />
              <div className="flex items-center justify-between py-3 last:pb-0">
                <span className="text-sm font-medium text-ink">稼働時間</span>
                <span className="text-sm text-ink-dim">{settings.vps.uptimeHours}h</span>
              </div>
              <div className="pt-3">
                <Button variant="secondary" className="w-full" disabled>
                  <LinkIcon className="h-4 w-4" />
                  Connect VPS(準備中)
                </Button>
              </div>
            </SettingsSection>

            <SettingsSection icon={<CpuIcon className="h-4 w-4" />} title="AI">
              <PillGroup
                label="判断エンジン"
                value={settings.ai.engine}
                onChange={(v) => patch((p) => ({ ...p, ai: { ...p.ai, engine: v } }))}
                options={[
                  { value: "rule_based", label: "Rule-based" },
                  { value: "openai", label: "OpenAI", disabled: true },
                  { value: "claude", label: "Claude", disabled: true },
                ]}
              />
              <p className="pb-1 pt-2 text-xs text-ink-faint">
                Entry Strictness・Enable Ordersなどの売買判断に直結する設定は、上部の「AI判断ロジック」「発注設定」に
                移動しました。
              </p>
            </SettingsSection>

            <SettingsSection icon={<ServerIcon className="h-4 w-4" />} title="MT5(参考情報)">
              <TextField
                label="Server"
                value={settings.mt5.server}
                onChange={(v) => patch((p) => ({ ...p, mt5: { ...p.mt5, server: v } }))}
              />
              <TextField
                label="Account Login"
                mono
                value={settings.mt5.accountLogin}
                onChange={(v) => patch((p) => ({ ...p, mt5: { ...p.mt5, accountLogin: v } }))}
              />
              <TextField
                label="Symbol"
                value={settings.mt5.symbol}
                onChange={(v) => patch((p) => ({ ...p, mt5: { ...p.mt5, symbol: v } }))}
              />
              <p className="pb-1 pt-2 text-xs text-ink-faint">
                Timeframe・Demo Onlyは上部の「AI判断ロジック」「発注設定」に移動しました。ここはまだ参考表示のみで
                保存されません。
              </p>
            </SettingsSection>
          </>
        )}
      </div>
    </PageShell>
  );
}
