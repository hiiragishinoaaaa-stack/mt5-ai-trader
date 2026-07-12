import { useEffect, useState } from "react";
import type { TradingSettings as TradingSettingsData } from "../../types";
import { fetchTradingSettings, saveTradingSettings, SettingsApiError } from "../../api/settingsApi";
import {
  ENTRY_STRICTNESS_PRESETS,
  TIMEFRAME_OPTIONS,
  validateTradingSettingsDraft,
  type ValidationErrors,
} from "../../lib/tradingSettingsSchema";
import { Card } from "../Card";
import { Eyebrow } from "../Eyebrow";
import { Badge } from "../Badge";
import { Button } from "../Button";
import { Skeleton } from "../Skeleton";
import { NumberField, PillGroup, TextField, Toggle, ToggleRow } from "./fields";
import { AlertIcon, CheckIcon } from "../icons";

type Status = "loading" | "ready" | "connection_error";

const SUCCESS_BANNER_TIMEOUT_MS = 4000;

function fieldsEqual(a: TradingSettingsData, b: TradingSettingsData): boolean {
  return (Object.keys(a) as (keyof TradingSettingsData)[]).every((key) => a[key] === b[key]);
}

export function TradingSettings() {
  const [status, setStatus] = useState<Status>("loading");
  const [connectionMessage, setConnectionMessage] = useState("");
  const [saved, setSaved] = useState<TradingSettingsData | null>(null);
  const [draft, setDraft] = useState<TradingSettingsData | null>(null);
  const [saving, setSaving] = useState(false);
  const [serverErrors, setServerErrors] = useState<ValidationErrors>({});
  const [banner, setBanner] = useState<{ tone: "success" | "error"; message: string } | null>(null);

  function load() {
    setStatus("loading");
    fetchTradingSettings()
      .then((settings) => {
        setSaved(settings);
        setDraft(settings);
        setStatus("ready");
      })
      .catch((err: unknown) => {
        setConnectionMessage(err instanceof SettingsApiError ? err.message : "設定の取得に失敗しました");
        setStatus("connection_error");
      });
  }

  useEffect(() => {
    load();
  }, []);

  useEffect(() => {
    if (!banner) return;
    const timer = window.setTimeout(() => setBanner(null), SUCCESS_BANNER_TIMEOUT_MS);
    return () => window.clearTimeout(timer);
  }, [banner]);

  function updateDraft(patch: Partial<TradingSettingsData>) {
    setDraft((prev) => (prev ? { ...prev, ...patch } : prev));
  }

  function applyEntryStrictness(level: keyof typeof ENTRY_STRICTNESS_PRESETS) {
    const preset = ENTRY_STRICTNESS_PRESETS[level];
    updateDraft({
      ENTRY_STRICTNESS: level,
      RSI_OVERBOUGHT: preset.RSI_OVERBOUGHT,
      RSI_OVERSOLD: preset.RSI_OVERSOLD,
    });
  }

  async function handleSave() {
    if (!draft) return;
    setSaving(true);
    setBanner(null);
    const result = await saveTradingSettings(draft);
    setSaving(false);

    if (!result.success) {
      setServerErrors((result.errors as ValidationErrors) ?? {});
      setBanner({ tone: "error", message: result.message ?? "保存に失敗しました" });
      return;
    }

    setServerErrors({});
    const next = result.settings ?? draft;
    setSaved(next);
    setDraft(next);
    setBanner({ tone: "success", message: "保存しました" });
  }

  function handleReset() {
    if (saved) setDraft(saved);
    setServerErrors({});
    setBanner(null);
  }

  if (status === "loading") {
    return (
      <Card>
        <Skeleton className="h-64 w-full" />
      </Card>
    );
  }

  if (status === "connection_error" || !draft) {
    return (
      <Card className="flex flex-col gap-3">
        <div className="flex items-center gap-2 text-loss">
          <AlertIcon className="h-5 w-5 shrink-0" />
          <span className="text-sm font-semibold">Bot APIに接続できません</span>
        </div>
        <p className="text-xs leading-relaxed text-ink-dim">{connectionMessage}</p>
        <p className="text-xs leading-relaxed text-ink-faint">
          PCで <code className="rounded bg-surface-2 px-1 py-0.5 font-mono">python settings_server.py</code>{" "}
          を起動しているか、Dashboardの接続先設定(VITE_SETTINGS_API_URL)がPCのIPと合っているか確認してください。
        </p>
        <Button variant="secondary" onClick={load}>
          再試行
        </Button>
      </Card>
    );
  }

  const clientErrors = validateTradingSettingsDraft(draft);
  const errors: ValidationErrors = { ...clientErrors, ...serverErrors };
  const hasErrors = Object.keys(errors).length > 0;
  const isDirty = !fieldsEqual(draft, saved!);

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <Eyebrow>Bot API</Eyebrow>
        <Badge tone="profit">
          <span className="h-1.5 w-1.5 rounded-full bg-profit" />
          Connected
        </Badge>
      </div>

      <Card className="flex flex-col gap-1">
        <span className="mb-1 text-sm font-semibold text-ink">AI判断ロジック</span>
        <div className="border-b border-border py-3 first:pt-0">
          <PillGroup
            label="Entry Strictness"
            value={draft.ENTRY_STRICTNESS}
            onChange={applyEntryStrictness}
            disabled={saving}
            options={(Object.keys(ENTRY_STRICTNESS_PRESETS) as (keyof typeof ENTRY_STRICTNESS_PRESETS)[]).map(
              (key) => ({ value: key, label: ENTRY_STRICTNESS_PRESETS[key].label }),
            )}
          />
          <span className="text-xs text-ink-faint">
            {ENTRY_STRICTNESS_PRESETS[draft.ENTRY_STRICTNESS].description}
            (選択すると下のRSI値も自動更新されます。その後個別に調整できます)
          </span>
        </div>
        <div className="grid grid-cols-2 gap-x-3">
          <NumberField
            label="RSI Overbought"
            step={1}
            value={draft.RSI_OVERBOUGHT}
            onChange={(v) => updateDraft({ RSI_OVERBOUGHT: v })}
            error={errors.RSI_OVERBOUGHT}
            disabled={saving}
          />
          <NumberField
            label="RSI Oversold"
            step={1}
            value={draft.RSI_OVERSOLD}
            onChange={(v) => updateDraft({ RSI_OVERSOLD: v })}
            error={errors.RSI_OVERSOLD}
            disabled={saving}
          />
        </div>
        <div className="grid grid-cols-2 gap-x-3">
          <NumberField
            label="EMA Fast"
            step={1}
            value={draft.EMA_FAST_PERIOD}
            onChange={(v) => updateDraft({ EMA_FAST_PERIOD: v })}
            error={errors.EMA_FAST_PERIOD}
            disabled={saving}
          />
          <NumberField
            label="EMA Slow"
            step={1}
            value={draft.EMA_SLOW_PERIOD}
            onChange={(v) => updateDraft({ EMA_SLOW_PERIOD: v })}
            error={errors.EMA_SLOW_PERIOD}
            disabled={saving}
          />
        </div>
        <PillGroup
          label="Timeframe"
          value={draft.TIMEFRAME}
          onChange={(v) => updateDraft({ TIMEFRAME: v })}
          disabled={saving}
          options={TIMEFRAME_OPTIONS.map((tf) => ({ value: tf, label: tf }))}
        />
        <span className="-mt-1 pb-2 text-xs text-ink-faint">
          MT5のEA(ARTEMIS_Bridge.mq5)のInpTimeframeも同じ値に設定してください。ここだけを変えても実際に取得される
          ローソク足の時間軸は変わりません。
        </span>
        <NumberField
          label="Loop Interval"
          step={5}
          suffix="秒"
          value={draft.LOOP_INTERVAL_SECONDS}
          onChange={(v) => updateDraft({ LOOP_INTERVAL_SECONDS: v })}
          error={errors.LOOP_INTERVAL_SECONDS}
          disabled={saving}
        />
      </Card>

      <Card className="flex flex-col gap-1">
        <span className="mb-1 text-sm font-semibold text-ink">発注設定</span>
        <ToggleRow
          label="Enable Orders"
          description="OFFの場合、AIは判断のみでMT5へ発注しません"
          checked={draft.ENABLE_ORDERS}
          onChange={(v) => updateDraft({ ENABLE_ORDERS: v })}
        />
        <div className="flex items-center justify-between gap-4 py-3">
          <div>
            <p className="text-sm font-medium text-ink">Demo Only</p>
            <p className="mt-0.5 text-xs text-ink-faint">OFFにするとライブ口座での発注リスクが発生します</p>
          </div>
          <div className="flex items-center gap-2">
            <Badge tone={draft.DEMO_ONLY ? "profit" : "loss"}>{draft.DEMO_ONLY ? "Demo" : "Live risk"}</Badge>
            <Toggle checked={draft.DEMO_ONLY} onChange={(v) => updateDraft({ DEMO_ONLY: v })} />
          </div>
        </div>
        <NumberField
          label="Order Volume"
          step={0.01}
          suffix="lot"
          value={draft.ORDER_VOLUME}
          onChange={(v) => updateDraft({ ORDER_VOLUME: v })}
          error={errors.ORDER_VOLUME}
          disabled={saving}
        />
        <div className="grid grid-cols-2 gap-x-3">
          <NumberField
            label="SL"
            step={10}
            suffix="points"
            value={draft.SL_POINTS}
            onChange={(v) => updateDraft({ SL_POINTS: v })}
            error={errors.SL_POINTS}
            disabled={saving}
          />
          <NumberField
            label="TP"
            step={10}
            suffix="points"
            value={draft.TP_POINTS}
            onChange={(v) => updateDraft({ TP_POINTS: v })}
            error={errors.TP_POINTS}
            disabled={saving}
          />
        </div>
      </Card>

      <Card className="flex flex-col gap-1">
        <span className="mb-1 text-sm font-semibold text-ink">Discord通知</span>
        <ToggleRow
          label="Discord通知を有効にする"
          description="取引の実行・失敗をDiscordへ送信します"
          checked={draft.DISCORD_ENABLED}
          onChange={(v) => updateDraft({ DISCORD_ENABLED: v })}
        />
        <TextField
          label="Webhook URL"
          mono
          value={draft.DISCORD_WEBHOOK_URL}
          onChange={(v) => updateDraft({ DISCORD_WEBHOOK_URL: v })}
          placeholder="https://discord.com/api/webhooks/..."
        />
        <ToggleRow
          label="取引ごとに通知"
          description="発注が成功したときに通知します"
          checked={draft.DISCORD_NOTIFY_ON_TRADE}
          onChange={(v) => updateDraft({ DISCORD_NOTIFY_ON_TRADE: v })}
        />
        <ToggleRow
          label="エラー通知"
          description="発注が失敗・タイムアウトしたときに通知します"
          checked={draft.DISCORD_NOTIFY_ON_ERROR}
          onChange={(v) => updateDraft({ DISCORD_NOTIFY_ON_ERROR: v })}
        />
        <ToggleRow
          label="日次サマリー"
          description="1日1回、その日の損益サマリーを通知します"
          checked={draft.DISCORD_NOTIFY_DAILY_SUMMARY}
          onChange={(v) => updateDraft({ DISCORD_NOTIFY_DAILY_SUMMARY: v })}
        />
      </Card>

      {banner ? (
        <div
          className={`flex items-center gap-2 rounded-xl border px-3 py-2.5 text-sm ${
            banner.tone === "success" ? "border-profit/40 bg-profit-soft text-profit" : "border-loss/40 bg-loss-soft text-loss"
          }`}
        >
          {banner.tone === "success" ? <CheckIcon className="h-4 w-4 shrink-0" /> : <AlertIcon className="h-4 w-4 shrink-0" />}
          {banner.message}
        </div>
      ) : null}

      <div className="flex gap-2.5">
        {isDirty ? (
          <Button variant="secondary" onClick={handleReset} disabled={saving}>
            リセット
          </Button>
        ) : null}
        <Button variant="primary" className="flex-1" onClick={handleSave} disabled={saving || !isDirty || hasErrors}>
          {saving ? "保存中..." : "変更を保存"}
        </Button>
      </div>
    </div>
  );
}
