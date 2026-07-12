"""Anthropic Claude Messages APIを使ったAI判断エンジン(Phase 7)。

外部ライブラリを追加せず、urllib.requestで直接AnthropicのAPIへPOSTする
(discord_notifier.py/openai_engine.pyと同じ方針)。

## 安全設計

openai_engine.pyと同様、APIキー未設定・ネットワークエラー・不正なレスポンスの
いずれの場合も例外を送出せず、必ずWAITにフォールバックする。
"""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request

import pandas as pd

import config
from ai_engine import AIEngine, LLM_SYSTEM_PROMPT, Signal, describe_market_conditions, parse_llm_signal_json

logger = logging.getLogger("mt5_ai_trader")

_API_URL = "https://api.anthropic.com/v1/messages"
_ANTHROPIC_VERSION = "2023-06-01"
_MAX_TOKENS = 300


class ClaudeEngine(AIEngine):
    """AnthropicのMessages APIにBUY/SELL/WAITを判断させるエンジン。"""

    def decide(self, df: pd.DataFrame) -> Signal:
        if not config.ANTHROPIC_API_KEY:
            return Signal("WAIT", "ANTHROPIC_API_KEYが未設定です(.envで設定してください)", {})

        if df.empty:
            return Signal("WAIT", "ローソク足データが空です", {})

        prompt = describe_market_conditions(df, config.SYMBOL, config.TIMEFRAME)

        body = json.dumps(
            {
                "model": config.ANTHROPIC_MODEL,
                "max_tokens": _MAX_TOKENS,
                "system": LLM_SYSTEM_PROMPT,
                "messages": [{"role": "user", "content": prompt}],
            }
        ).encode("utf-8")

        req = urllib.request.Request(
            _API_URL,
            data=body,
            headers={
                "Content-Type": "application/json",
                "x-api-key": config.ANTHROPIC_API_KEY,
                "anthropic-version": _ANTHROPIC_VERSION,
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=config.AI_ENGINE_TIMEOUT_SECONDS) as res:
                payload = json.loads(res.read().decode("utf-8"))
            content = payload["content"][0]["text"]
        except (urllib.error.URLError, OSError, KeyError, IndexError, json.JSONDecodeError) as exc:
            logger.warning("claude_engine: API呼び出しに失敗しました: %s", exc)
            return Signal("WAIT", f"Claude API呼び出しに失敗しました({exc})", {})

        try:
            return parse_llm_signal_json(content)
        except ValueError as exc:
            logger.warning("claude_engine: レスポンスの解析に失敗しました: %s (content=%s)", exc, content)
            return Signal("WAIT", f"Claudeの応答を解析できませんでした({exc})", {})
