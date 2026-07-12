"""OpenAI Chat Completions APIを使ったAI判断エンジン(Phase 7)。

外部ライブラリを追加せず、urllib.requestで直接OpenAIのAPIへPOSTする
(discord_notifier.pyと同じ方針)。

## 安全設計

- `config.OPENAI_API_KEY` が未設定の場合、APIを呼び出さずWAITを返す。
- ネットワークエラー・タイムアウト・不正なレスポンス(JSON形式でない、
  actionが不正、等)のいずれの場合も例外を送出せず、必ずWAITにフォールバック
  する。判断ロジックの不具合や外部API側の問題が、誤った発注に直結しない
  ようにするため(発注そのものはconfig.ENABLE_ORDERS/DEMO_ONLYがさらに
  ゲートしている。order_executor.py参照)。
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

_API_URL = "https://api.openai.com/v1/chat/completions"


class OpenAIEngine(AIEngine):
    """OpenAIのChat Completions APIにBUY/SELL/WAITを判断させるエンジン。"""

    def decide(self, df: pd.DataFrame) -> Signal:
        if not config.OPENAI_API_KEY:
            return Signal("WAIT", "OPENAI_API_KEYが未設定です(.envで設定してください)", {})

        if df.empty:
            return Signal("WAIT", "ローソク足データが空です", {})

        prompt = describe_market_conditions(df, config.SYMBOL, config.TIMEFRAME)

        body = json.dumps(
            {
                "model": config.OPENAI_MODEL,
                "messages": [
                    {"role": "system", "content": LLM_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                "response_format": {"type": "json_object"},
                "temperature": 0,
            }
        ).encode("utf-8")

        req = urllib.request.Request(
            _API_URL,
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {config.OPENAI_API_KEY}",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=config.AI_ENGINE_TIMEOUT_SECONDS) as res:
                payload = json.loads(res.read().decode("utf-8"))
            content = payload["choices"][0]["message"]["content"]
        except (urllib.error.URLError, OSError, KeyError, IndexError, json.JSONDecodeError) as exc:
            logger.warning("openai_engine: API呼び出しに失敗しました: %s", exc)
            return Signal("WAIT", f"OpenAI API呼び出しに失敗しました({exc})", {})

        try:
            return parse_llm_signal_json(content)
        except ValueError as exc:
            logger.warning("openai_engine: レスポンスの解析に失敗しました: %s (content=%s)", exc, content)
            return Signal("WAIT", f"OpenAIの応答を解析できませんでした({exc})", {})
