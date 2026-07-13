"""DashboardのTIMEFRAME設定をMT5のEA(ARTEMIS_Bridge.mq5、v4.04以降)へ
ファイル経由で伝える書き出し役。

main.pyが各サイクルの先頭で write_ea_config(config.TIMEFRAME) を呼び出し、
EAはOnTimer()の度にこのファイルを読み込んで実際にCopyRatesへ渡す時間軸を
動的に切り替える(EA側のInpTimeframeはこのファイルが存在しない場合の
初期値としてのみ使われる)。これにより、DashboardでTIMEFRAMEを変更した後
MT5のEAを再コンパイル・再設定しなくても次サイクルから反映される。
"""
from __future__ import annotations

import json
import time

import config


def write_ea_config(timeframe: str) -> None:
    """現在のTIMEFRAMEをEA設定ファイルへ書き出す。main.pyの各サイクルで呼ばれる。"""
    payload = {"timeframe": timeframe, "updated_at": time.time()}
    tmp_path = config.EA_CONFIG_FILE_PATH.with_suffix(".tmp")
    tmp_path.parent.mkdir(parents=True, exist_ok=True)
    with tmp_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)
    tmp_path.replace(config.EA_CONFIG_FILE_PATH)
