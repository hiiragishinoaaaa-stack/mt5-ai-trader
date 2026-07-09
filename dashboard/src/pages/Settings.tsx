import { useEffect, useState } from "react";
import { getSettings, updateSettings } from "../api/client";
import type { SettingsState } from "../types";
import { Header } from "../components/Header";
import { PageShell, PageTitle } from "../components/PageShell";
import { Card } from "../components/Card";
import { Badge } from "../components/Badge";
import { Button } from "../components/Button";
import { Skeleton } from "../components/Skeleton";
import { NumberField, PillGroup, SettingsSection, TextField, ToggleRow } from "../components/settings/fields";
import { BellIcon, CpuIcon, LinkIcon, MessageIcon, ServerIcon, ShieldIcon } from "../components/icons";

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

  if (loading || !settings) {
    return (
      <PageShell>
        <Header />
        <PageTitle sub="Discord・VPS・AI・通知・リスク・MT5の設定">Settings</PageTitle>
        <div className="flex flex-col gap-4">
          {[0, 1, 2, 3, 4, 5].map((i) => (
            <Card key={i}>
              <Skeleton className="h-28 w-full" />
            </Card>
          ))}
        </div>
      </PageShell>
    );
  }

  return (
    <PageShell>
      <Header />
      <PageTitle sub="Discord・VPS・AI・通知・リスク・MT5の設定">Settings</PageTitle>

      <div className="flex flex-col gap-4">
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
          <div className="flex items-center justify-between py-3 first:pt-0">
            <span className="text-sm font-medium text-ink">接続状態</span>
            <Badge tone={settings.vps.status === "connected" ? "profit" : "neutral"}>
              {settings.vps.status === "connected" ? "Connected" : "Disconnected"}
            </Badge>
          </div>
          <TextField label="Host" mono value={settings.vps.host} onChange={(v) => patch((p) => ({ ...p, vps: { ...p.vps, host: v } }))} />
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
          <PillGroup
            label="リスクレベル"
            value={settings.ai.riskLevel}
            onChange={(v) => patch((p) => ({ ...p, ai: { ...p.ai, riskLevel: v } }))}
            options={[
              { value: "low", label: "Low" },
              { value: "medium", label: "Medium" },
              { value: "high", label: "High" },
            ]}
          />
          <ToggleRow
            label="自動売買を有効にする"
            description="OFFの場合、AIは判断のみでMT5へ発注しません"
            checked={settings.ai.autoTradeEnabled}
            onChange={(v) => patch((p) => ({ ...p, ai: { ...p.ai, autoTradeEnabled: v } }))}
          />
        </SettingsSection>

        <SettingsSection icon={<ShieldIcon className="h-4 w-4" />} title="リスク">
          <NumberField
            label="Lot Size"
            step={0.01}
            value={settings.risk.lotSize}
            onChange={(v) => patch((p) => ({ ...p, risk: { ...p.risk, lotSize: v } }))}
          />
          <NumberField
            label="最大日次損失"
            step={1}
            suffix="%"
            value={settings.risk.maxDailyLossPercent}
            onChange={(v) => patch((p) => ({ ...p, risk: { ...p.risk, maxDailyLossPercent: v } }))}
          />
          <NumberField
            label="最大同時ポジション数"
            step={1}
            value={settings.risk.maxPositions}
            onChange={(v) => patch((p) => ({ ...p, risk: { ...p.risk, maxPositions: v } }))}
          />
          <NumberField
            label="SL"
            step={10}
            suffix="points"
            value={settings.risk.slPoints}
            onChange={(v) => patch((p) => ({ ...p, risk: { ...p.risk, slPoints: v } }))}
          />
          <NumberField
            label="TP"
            step={10}
            suffix="points"
            value={settings.risk.tpPoints}
            onChange={(v) => patch((p) => ({ ...p, risk: { ...p.risk, tpPoints: v } }))}
          />
        </SettingsSection>

        <SettingsSection icon={<ServerIcon className="h-4 w-4" />} title="MT5">
          <TextField label="Server" value={settings.mt5.server} onChange={(v) => patch((p) => ({ ...p, mt5: { ...p.mt5, server: v } }))} />
          <TextField
            label="Account Login"
            mono
            value={settings.mt5.accountLogin}
            onChange={(v) => patch((p) => ({ ...p, mt5: { ...p.mt5, accountLogin: v } }))}
          />
          <TextField label="Symbol" value={settings.mt5.symbol} onChange={(v) => patch((p) => ({ ...p, mt5: { ...p.mt5, symbol: v } }))} />
          <TextField label="Timeframe" value={settings.mt5.timeframe} onChange={(v) => patch((p) => ({ ...p, mt5: { ...p.mt5, timeframe: v } }))} />
          <div className="flex items-center justify-between py-3 last:pb-0">
            <div>
              <p className="text-sm font-medium text-ink">DEMO_ONLY</p>
              <p className="mt-0.5 text-xs text-ink-faint">OFFにするとライブ口座での発注リスクが発生します</p>
            </div>
            <Badge tone={settings.mt5.demoOnly ? "profit" : "loss"}>{settings.mt5.demoOnly ? "Demo" : "Live risk"}</Badge>
          </div>
        </SettingsSection>
      </div>
    </PageShell>
  );
}
