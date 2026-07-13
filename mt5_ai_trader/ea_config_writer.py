"""DashboardのTIMEFRAME設定をMT5のEA(ARTEMIS_Bridge.mq5、v4.04以降)へ
ファイル経由で伝える書き出し役。

main.pyが各サイクルの先頭で、config.ENABLED_SYMBOLSの銘柄それぞれについて
write_ea_config(config.TIMEFRAME, symbol) を呼び出し、その銘柄用のEA
インスタンスがOnTimer()の度にこのファイルを読み込んで実際にCopyRatesへ
渡す時間軸を動的に切り替える(EA側のInpTimeframeはこのファイルが存在
しない場合の初期値としてのみ使われる)。これにより、DashboardでTIMEFRAME
を変更した後MT5のEAを再コンパイル・再設定しなくても次サイクルから反映
される。
"""
from __future__ import annotations

import json
import time

import config


def write_ea_config(timeframe: str, symbol: str) -> None:
    """現在のTIMEFRAMEを、指定した銘柄用のEA設定ファイルへ書き出す。

    main.pyの各サイクルで、有効な銘柄それぞれについて呼ばれる。
    """
    payload = {"timeframe": timeframe, "updated_at": time.time()}
    file_path = config.ea_config_file_path(symbol)
    tmp_path = file_path.with_suffix(".tmp")
    tmp_path.parent.mkdir(parents=True, exist_ok=True)
    with tmp_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)
    tmp_path.replace(file_path)
