import { useEffect, useState } from "react";
import type { TradingSettings as TradingSettingsData } from "../../types";
import { fetchTradingSettings, saveTradingSettings, SettingsApiError } from "../../api/settingsApi";
import type { AvailableSymbol } from "../../types";
import {
  AI_ENGINE_LABELS,
  AVAILABLE_SYMBOLS,
  ENTRY_STRICTNESS_PRESETS,
  STOP_MODE_OPTIONS,
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
    const { label: _label, description: _description, extra, ...rest } = ENTRY_STRICTNESS_PRESETS[level];
    updateDraft({
      ENTRY_STRICTNESS: level,
      ...rest,
      ...(extra ?? {}),
    });
  }

  function toggleSymbol(symbol: AvailableSymbol, enabled: boolean) {
    if (!draft) return;
    const next = enabled
      ? [...draft.ENABLED_SYMBOLS, symbol]
      : draft.ENABLED_SYMBOLS.filter((s) => s !== symbol);
    updateDraft({ ENABLED_SYMBOLS: next });
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
            label="判断エンジン"
            value={draft.AI_ENGINE}
            onChange={(v) => updateDraft({ AI_ENGINE: v })}
            disabled={saving}
            options={(Object.keys(AI_ENGINE_LABELS) as (keyof typeof AI_ENGINE_LABELS)[]).map((key) => ({
              value: key,
              label: AI_ENGINE_LABELS[key],
            }))}
          />
          <span className="text-xs text-ink-faint">
            {draft.AI_ENGINE === "rule_based"
              ? "EMA/RSI/MACDのルールでBUY/SELL/WAITを判断します(無料)"
              : "実際にAPIを呼び出して判断します" +
                (draft.AI_ENGINE === "gemini" ? "(Flash系モデルなら無料枠あり)" : "(利用ごとに料金が発生します)") +
                "。.envに" +
                { openai: "OPENAI_API_KEY", claude: "ANTHROPIC_API_KEY", gemini: "GEMINI_API_KEY" }[
                  draft.AI_ENGINE as "openai" | "claude" | "gemini"
                ] +
                "を設定していない場合、常にWAITになります"}
          </span>
        </div>
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
            (選択すると下のRSI帯域・必要スコアも自動更新されます。その後個別に調整できます)
          </span>
        </div>
        <div className="grid grid-cols-2 gap-x-3">
          <NumberField
            label="RSI BUY Min"
            step={1}
            value={draft.RSI_BUY_MIN}
            onChange={(v) => updateDraft({ RSI_BUY_MIN: v })}
            error={errors.RSI_BUY_MIN}
            disabled={saving}
          />
          <NumberField
            label="RSI BUY Max"
            step={1}
            value={draft.RSI_BUY_MAX}
            onChange={(v) => updateDraft({ RSI_BUY_MAX: v })}
            error={errors.RSI_BUY_MAX}
            disabled={saving}
          />
        </div>
        <div className="grid grid-cols-2 gap-x-3">
          <NumberField
            label="RSI SELL Min"
            step={1}
            value={draft.RSI_SELL_MIN}
            onChange={(v) => updateDraft({ RSI_SELL_MIN: v })}
            error={errors.RSI_SELL_MIN}
            disabled={saving}
          />
          <NumberField
            label="RSI SELL Max"
            step={1}
            value={draft.RSI_SELL_MAX}
            onChange={(v) => updateDraft({ RSI_SELL_MAX: v })}
            error={errors.RSI_SELL_MAX}
            disabled={saving}
          />
        </div>
        <span className="-mt-1 pb-2 text-xs text-ink-faint">
          BUY/SELLそれぞれの判断条件の1つとして、RSIがこの範囲内にあるかを1点で採点する(EMAトレンド・MACD方向等の
          他の条件と合算した合計スコアがRequired Score以上ならエントリー)。
        </span>
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
        <div className="grid grid-cols-2 gap-x-3">
          <NumberField
            label="RSI Period"
            step={1}
            value={draft.RSI_PERIOD}
            onChange={(v) => updateDraft({ RSI_PERIOD: v })}
            error={errors.RSI_PERIOD}
            disabled={saving}
          />
          <NumberField
            label="ATR Period"
            step={1}
            value={draft.ATR_PERIOD}
            onChange={(v) => updateDraft({ ATR_PERIOD: v })}
            error={errors.ATR_PERIOD}
            disabled={saving}
          />
        </div>
        <NumberField
          label="Required Score"
          step={1}
          suffix="点"
          value={draft.REQUIRED_SCORE}
          onChange={(v) => updateDraft({ REQUIRED_SCORE: v })}
          error={errors.REQUIRED_SCORE}
          disabled={saving}
        />
        <span className="-mt-1 pb-2 text-xs text-ink-faint">
          EMAトレンド・押し目・RSI帯域・MACD方向等、判断条件(方向ごとに約9〜13点満点、データ不足で判定不能な条件は
          満点からも除外される)を1点ずつ均等に採点し、合計がこの点数以上ならエントリーする。
          {draft.REQUIRE_NO_NEW_EXTREME_5BARS
            ? " 現在のプリセットでは、直近5本の安値/高値を更新していないことも条件の1つに追加されている(満点も+1)。"
            : ""}
        </span>
        <div className="grid grid-cols-2 gap-x-3">
          <NumberField
            label="Max Spread"
            step={1}
            suffix="points"
            value={draft.MAX_SPREAD_POINTS}
            onChange={(v) => updateDraft({ MAX_SPREAD_POINTS: v })}
            error={errors.MAX_SPREAD_POINTS}
            disabled={saving}
          />
          <NumberField
            label="ATR Min"
            step={1}
            suffix="points"
            value={draft.ATR_MIN_POINTS}
            onChange={(v) => updateDraft({ ATR_MIN_POINTS: v })}
            error={errors.ATR_MIN_POINTS}
            disabled={saving}
          />
        </div>
        <span className="-mt-1 pb-2 text-xs text-ink-faint">
          スプレッドがMax Spreadを超える、またはATR(値動きの大きさ)がATR
          Min未満の場合はエントリーしない(いずれも0でチェック無効)。
        </span>
        <PillGroup
          label="Timeframe"
          value={draft.TIMEFRAME}
          onChange={(v) => updateDraft({ TIMEFRAME: v })}
          disabled={saving}
          options={TIMEFRAME_OPTIONS.map((tf) => ({ value: tf, label: tf }))}
        />
        <span className="-mt-1 pb-2 text-xs text-ink-faint">
          EA(ARTEMIS_Bridge.mq5)がv4.04以降なら、ここを変えるだけで次サイクルから自動的にMT5側にも反映されます
          (PC・MetaEditorの操作は不要)。v4.03以前のEAでは、MT5のEAのInpTimeframeも手動で同じ値に設定しない限り、
          ここだけ変えても実際に取得されるローソク足の時間軸は変わりません。
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
        <span className="mb-1 text-sm font-semibold text-ink">銘柄</span>
        <span className="-mt-0.5 pb-1 text-xs text-ink-faint">
          ONの銘柄だけがAI判断・発注の対象になる。銘柄ごとにMT5側へ別のEAインスタンスを追加する必要がある
          (入力パラメータだけ変更、再コンパイル不要)。
        </span>
        {AVAILABLE_SYMBOLS.map((symbol) => (
          <ToggleRow
            key={symbol}
            label={symbol}
            checked={draft.ENABLED_SYMBOLS.includes(symbol)}
            onChange={(checked) => toggleSymbol(symbol, checked)}
          />
        ))}
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
        <PillGroup
          label="Stop Mode"
          value={draft.STOP_MODE}
          onChange={(v) => updateDraft({ STOP_MODE: v })}
          disabled={saving}
          options={STOP_MODE_OPTIONS.map((mode) => ({
            value: mode,
            label: mode === "fixed" ? "Fixed" : "ATR",
          }))}
        />
        <span className="-mt-1 pb-2 text-xs text-ink-faint">
          Fixed: 下のSL/TP(points)を毎回そのまま使う。ATR: 発注のたびにATR(値動きの大きさ)×倍率でSL/TPを動的に計算する。
        </span>
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
        {draft.STOP_MODE === "atr" ? (
          <>
            <div className="grid grid-cols-2 gap-x-3">
              <NumberField
                label="ATR SL倍率"
                step={0.1}
                value={draft.ATR_SL_MULTIPLIER}
                onChange={(v) => updateDraft({ ATR_SL_MULTIPLIER: v })}
                error={errors.ATR_SL_MULTIPLIER}
                disabled={saving}
              />
              <NumberField
                label="ATR TP倍率"
                step={0.1}
                value={draft.ATR_TP_MULTIPLIER}
                onChange={(v) => updateDraft({ ATR_TP_MULTIPLIER: v })}
                error={errors.ATR_TP_MULTIPLIER}
                disabled={saving}
              />
            </div>
            <div className="grid grid-cols-2 gap-x-3">
              <NumberField
                label="Point Size"
                step={0.0001}
                value={draft.POINT_SIZE}
                onChange={(v) => updateDraft({ POINT_SIZE: v })}
                error={errors.POINT_SIZE}
                disabled={saving}
              />
              <NumberField
                label="Broker Min Stop"
                step={1}
                suffix="points"
                value={draft.BROKER_MIN_STOP_POINTS}
                onChange={(v) => updateDraft({ BROKER_MIN_STOP_POINTS: v })}
                error={errors.BROKER_MIN_STOP_POINTS}
                disabled={saving}
              />
            </div>
            <span className="-mt-1 pb-2 text-xs text-ink-faint">
              Point SizeはブローカーのUSDJPY 1point単位の価格(例: 3桁ブローカーなら0.001)。実際の値と合っていないと
              SL/TP幅がずれるので必ず確認すること。
            </span>
          </>
        ) : null}
        <NumberField
          label="Max Concurrent Positions"
          step={1}
          suffix="件"
          value={draft.MAX_CONCURRENT_POSITIONS}
          onChange={(v) => updateDraft({ MAX_CONCURRENT_POSITIONS: v })}
          error={errors.MAX_CONCURRENT_POSITIONS}
          disabled={saving}
        />
        <span className="-mt-1 pb-2 text-xs text-ink-faint">
          同じ銘柄で同時に保有できるポジション数の上限(1〜10)。実際のカウント・強制はEA側(v4.01以降)が行う。
        </span>
      </Card>

      <Card className="flex flex-col gap-1">
        <span className="mb-1 text-sm font-semibold text-ink">リスク管理</span>
        <span className="-mt-0.5 pb-1 text-xs text-ink-faint">
          エントリー頻度の制御・サーキットブレーカー。AIがBUY/SELLと判断しても、ここでブロックされる場合は
          自動的にWAITへ差し替えられる(Trade画面のAI Judgementに理由が表示される)。
        </span>
        <NumberField
          label="Entry Cooldown"
          step={30}
          suffix="秒"
          value={draft.ENTRY_COOLDOWN_SECONDS}
          onChange={(v) => updateDraft({ ENTRY_COOLDOWN_SECONDS: v })}
          error={errors.ENTRY_COOLDOWN_SECONDS}
          disabled={saving}
        />
        <div className="grid grid-cols-2 gap-x-3">
          <NumberField
            label="Max Trades/Hour"
            step={1}
            value={draft.MAX_TRADES_PER_HOUR}
            onChange={(v) => updateDraft({ MAX_TRADES_PER_HOUR: v })}
            error={errors.MAX_TRADES_PER_HOUR}
            disabled={saving}
          />
          <NumberField
            label="Max Trades/Day"
            step={1}
            value={draft.MAX_TRADES_PER_DAY}
            onChange={(v) => updateDraft({ MAX_TRADES_PER_DAY: v })}
            error={errors.MAX_TRADES_PER_DAY}
            disabled={saving}
          />
        </div>
        <span className="-mt-1 pb-2 text-xs text-ink-faint">
          いずれも0でチェック無効。直近1時間/24時間に新規オープンした回数(手動決済・自動決済を問わない)で判定する。
        </span>
        <div className="grid grid-cols-2 gap-x-3">
          <NumberField
            label="連敗数"
            step={1}
            value={draft.LOSS_STREAK_THRESHOLD}
            onChange={(v) => updateDraft({ LOSS_STREAK_THRESHOLD: v })}
            error={errors.LOSS_STREAK_THRESHOLD}
            disabled={saving}
          />
          <NumberField
            label="連敗後の停止時間"
            step={5}
            suffix="分"
            value={draft.COOLDOWN_AFTER_LOSSES_MINUTES}
            onChange={(v) => updateDraft({ COOLDOWN_AFTER_LOSSES_MINUTES: v })}
            error={errors.COOLDOWN_AFTER_LOSSES_MINUTES}
            disabled={saving}
          />
        </div>
        <NumberField
          label="1日の最大損失"
          step={1}
          suffix="%"
          value={draft.MAX_DAILY_LOSS_PERCENT}
          onChange={(v) => updateDraft({ MAX_DAILY_LOSS_PERCENT: v })}
          error={errors.MAX_DAILY_LOSS_PERCENT}
          disabled={saving}
        />
        <span className="-mt-1 pb-2 text-xs text-ink-faint">
          連敗後の停止時間・1日の最大損失は0で無効。決済方法(手動/自動)は区別せず、損益の実績だけで判定する。
        </span>
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
