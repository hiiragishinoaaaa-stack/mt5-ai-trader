"""Google Gemini API(Generative Language API)を使ったAI判断エンジン。

外部ライブラリを追加せず、urllib.requestで直接Gemini APIへPOSTする
(openai_engine.py/claude_engine.pyと同じ方針)。Flashモデルは無料枠が
あるため(1日あたりのリクエスト数上限内であれば無課金)、低頻度な
呼び出し(ローソク足が変わった時だけ、CandleThrottledEngine参照)と
組み合わせることでコストをほぼゼロに抑えられる。

## 安全設計

openai_engine.py/claude_engine.pyと同様、APIキー未設定・ネットワーク
エラー・不正なレスポンスのいずれの場合も例外を送出せず、必ずWAITに
フォールバックする。
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

_API_URL_TEMPLATE = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


class GeminiEngine(AIEngine):
    """Google GeminiのGenerative Language APIにBUY/SELL/WAITを判断させるエンジン。"""

    def decide(self, df: pd.DataFrame) -> Signal:
        if not config.GEMINI_API_KEY:
            return Signal("WAIT", "GEMINI_API_KEYが未設定です(.envで設定してください)", {})

        if df.empty:
            return Signal("WAIT", "ローソク足データが空です", {})

        prompt = describe_market_conditions(df, config.SYMBOL, config.TIMEFRAME)

        body = json.dumps(
            {
                "system_instruction": {"parts": [{"text": LLM_SYSTEM_PROMPT}]},
                "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                "generationConfig": {"temperature": 0},
            }
        ).encode("utf-8")

        url = _API_URL_TEMPLATE.format(model=config.GEMINI_MODEL)
        req = urllib.request.Request(
            url,
            data=body,
            headers={
                "Content-Type": "application/json",
                "x-goog-api-key": config.GEMINI_API_KEY,
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=config.AI_ENGINE_TIMEOUT_SECONDS) as res:
                payload = json.loads(res.read().decode("utf-8"))
            content = payload["candidates"][0]["content"]["parts"][0]["text"]
        except (urllib.error.URLError, OSError, KeyError, IndexError, json.JSONDecodeError) as exc:
            logger.warning("gemini_engine: API呼び出しに失敗しました: %s", exc)
            return Signal("WAIT", f"Gemini API呼び出しに失敗しました({exc})", {})

        try:
            return parse_llm_signal_json(content)
        except ValueError as exc:
            logger.warning("gemini_engine: レスポンスの解析に失敗しました: %s (content=%s)", exc, content)
            return Signal("WAIT", f"Geminiの応答を解析できませんでした({exc})", {})
