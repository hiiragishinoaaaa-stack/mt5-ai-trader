"""「決まった時刻に起きる急変」を探し、その後の値動きに乗れるかを測る。

## なぜこれを試すのか

RESEARCH_FINDINGS.md の確定事項2〜6で、**価格から作った指標で方向を当てる**
やり方は全滅した(4年10万本 × 2通貨、独立した3手法で同じ結論)。

このツールが狙うのは**別の軸**:

1. **価格から導けない外生的な情報**である「スケジュール済みイベント」
   (経済指標の発表時刻)。価格の変換ではないので、確定事項2の対象外。
2. **方向を当てない。** 発表で「大きく動くか」だけを見る。ボラティリティは
   方向より予測しやすい。

## 何を測るか

### 第1部: 急変が特定の時刻に集中しているか

カレンダーを外部から持ってこない。**データ自身に語らせる。** 値幅が異常に
大きいバーを抜き出し、(曜日 × UTC時刻) ごとに集中度を見る。特定のマスに
偏っていれば、それがそのまま指標発表のスケジュールになっている。

### 第2部: 急変の後、値動きは続くのか戻るのか

これが本命の判定。発表前に買いストップと売りストップを両方置く戦略は、
**片方が刺さって走ってくれる**ことに賭けている。

- **続く** → その戦略は成立しうる
- **即戻る** → 両側のストップが刈られて往復ビンタ。**成立しない**

バー内での高値・安値の到達順はOHLCから復元できないため、ストップ注文の
約定を直接は再現できない。代わりに**急変バーの終値でエントリー**して測る。
ストップ注文は「動いた側に乗る」ための道具なので、これがその近似になる。

## この分析が踏まないようにしている罠(全て実際に踏んだもの)

- **多重比較**: 曜日×時刻は約480マスある。総当たりすれば、効果ゼロでも
  偶然「集中している」マスが必ず出る。→ 前半・後半に分けて独立に測り、
  **両方で基準を上回ったマスだけ**を採用する。
- **非対称な脱落**: 追従と逆張りを同じ分母で数えると、勝ちだけが残って
  負けの一部が消える(RESEARCH_FINDINGS.md「集計バイアスの罠」)。
  → 両者は常に**独立した分母**で数える。
- **コストの過小評価**: 発表時は業者がスプレッドを大きく広げる。実測の
  スプレッドに加えて `--extra-spread` で上乗せして測ること。
- **対照の欠如**: 同じ時刻の「急変していないバー」も並べて出す。両者が
  同じ数字なら、効いているのは急変ではなく単なる時間帯。

使い方:
  .venv/bin/python event_scan.py --candles-file artemis_history_USDJPY_M15.json
  .venv/bin/python event_scan.py --candles-file artemis_history_USDJPY_M15.json \\
      --extra-spread 40 --sl-atr-mult 2 --rr 1.5
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass

import numpy as np
import pandas as pd

from backtest_audit import _make_forward_scanner, _spread_series
from backtest_replay import infer_point_size, load_candles

_WEEKDAY_JA = ("月", "火", "水", "木", "金", "土", "日")


@dataclass
class Cell:
    """(曜日 × UTC時刻) 1マス分の急変の集中度。"""

    weekday: int
    hour: int
    minute: int
    bars: int
    spikes: int
    spikes_first: int
    bars_first: int
    spikes_second: int
    bars_second: int

    @property
    def label(self) -> str:
        return f"{_WEEKDAY_JA[self.weekday]} {self.hour:02d}:{self.minute:02d}"

    @property
    def rate(self) -> float:
        return self.spikes / self.bars * 100 if self.bars else 0.0

    @property
    def rate_first(self) -> float:
        return self.spikes_first / self.bars_first * 100 if self.bars_first else 0.0

    @property
    def rate_second(self) -> float:
        return self.spikes_second / self.bars_second * 100 if self.bars_second else 0.0


def true_range(candles: pd.DataFrame) -> np.ndarray:
    """各バーの値幅。前バーの終値を跨ぐ窓開けも含める。"""
    highs = candles["high"].to_numpy(dtype=float)
    lows = candles["low"].to_numpy(dtype=float)
    closes = candles["close"].to_numpy(dtype=float)
    prev_close = np.concatenate(([closes[0]], closes[:-1]))
    return np.maximum(highs - lows, np.maximum(np.abs(highs - prev_close), np.abs(lows - prev_close)))


def spike_flags(candles: pd.DataFrame, window: int, multiple: float) -> np.ndarray:
    """各バーが「急変」かどうか。

    直前 window 本の値幅の中央値と比べて multiple 倍を超えたら急変とする。
    固定の閾値ではなく直近との比で見るのは、年単位でボラティリティ水準が
    変わるため(2022年と2025年を同じ物差しで測ると、片方に偏る)。

    自分自身を含めない(=直前まで)ことで、先読みを避ける。
    """
    tr = true_range(candles)
    ref = pd.Series(tr).shift(1).rolling(window, min_periods=window // 2).median().to_numpy()
    with np.errstate(invalid="ignore", divide="ignore"):
        ratio = np.where(ref > 0, tr / ref, 0.0)
    flags = ratio >= multiple
    flags[np.isnan(ref)] = False
    return flags


def build_cells(candles: pd.DataFrame, spikes: np.ndarray) -> list[Cell]:
    """(曜日 × UTC時刻) ごとに、総バー数と急変数を数える。

    前半・後半それぞれの内訳も同時に持たせる(再現性の判定に使う)。
    """
    times = pd.DatetimeIndex(candles["time"])
    weekday = times.weekday.to_numpy()
    hour = times.hour.to_numpy()
    minute = times.minute.to_numpy()
    middle = len(candles) // 2

    counters: dict[tuple[int, int, int], list[int]] = {}
    for i in range(len(candles)):
        key = (int(weekday[i]), int(hour[i]), int(minute[i]))
        slot = counters.setdefault(key, [0, 0, 0, 0, 0, 0])
        is_first = i < middle
        slot[0] += 1
        slot[1] += int(spikes[i])
        if is_first:
            slot[2] += int(spikes[i])
            slot[3] += 1
        else:
            slot[4] += int(spikes[i])
            slot[5] += 1

    return [
        Cell(
            weekday=k[0], hour=k[1], minute=k[2],
            bars=v[0], spikes=v[1],
            spikes_first=v[2], bars_first=v[3],
            spikes_second=v[4], bars_second=v[5],
        )
        for k, v in counters.items()
    ]


def replicated_cells(cells: list[Cell], baseline_rate: float, factor: float, min_spikes: int) -> list[Cell]:
    """前半・後半の両方で基準を上回ったマスだけを返す。

    曜日×時刻は約480マスある。総当たりすれば効果ゼロでも偶然「集中して
    いる」マスが必ず出るので、片方だけ良いものは採らない。
    """
    kept = []
    for cell in cells:
        if cell.spikes_first < min_spikes or cell.spikes_second < min_spikes:
            continue
        if cell.rate_first >= baseline_rate * factor and cell.rate_second >= baseline_rate * factor:
            kept.append(cell)
    return sorted(kept, key=lambda c: -c.rate)


@dataclass
class Outcome:
    """追従・逆張りそれぞれの成績。**分母は必ず別々に数える。**"""

    trades: int = 0
    wins: int = 0
    total_r: float = 0.0
    total_r_squared: float = 0.0
    unresolved: int = 0

    def add(self, r: float, won: bool) -> None:
        self.trades += 1
        self.wins += int(won)
        self.total_r += r
        self.total_r_squared += r * r

    @property
    def win_rate(self) -> float:
        return self.wins / self.trades * 100 if self.trades else 0.0

    @property
    def ev_r(self) -> float:
        return self.total_r / self.trades if self.trades else 0.0

    @property
    def stderr_r(self) -> float:
        """EVの標準誤差(R)。件数が少ない結果を切り捨てる判断に使う。"""
        if self.trades < 2:
            return 0.0
        mean = self.ev_r
        variance = max(self.total_r_squared / self.trades - mean * mean, 0.0)
        return (variance ** 0.5) / (self.trades ** 0.5)


def beats(candidate: Outcome, control: Outcome) -> bool:
    """急変側が対照を、誤差を超えて上回っているか。

    差が小さければ「効いているのは急変ではなく時間帯」であって、発表を
    狙う意味がない。2つの標準誤差を合成し、その2倍を超えた差だけを採る。
    """
    if not candidate.trades or not control.trades:
        return False
    margin = 2.0 * ((candidate.stderr_r ** 2 + control.stderr_r ** 2) ** 0.5)
    return candidate.ev_r - control.ev_r > margin


def measure_entries(
    candles: pd.DataFrame,
    indexes: list[int],
    sl_atr_mult: float,
    rr: float,
    point_size: float,
    spreads: np.ndarray,
    extra_spread: float,
    ref_window: int,
    max_horizon: int,
) -> tuple[Outcome, Outcome]:
    """指定バーの終値で入った場合の、(追従, 逆張り) の成績を返す。

    追従 = そのバーが動いた方向へ。逆張り = その逆。
    **2つは独立に集計する。** 同じ分母で数えると、片方が期限内に決着しな
    かったときにもう片方まで巻き添えで捨てることになり、勝ちだけが残って
    負けが消える(RESEARCH_FINDINGS.mdの集計バイアスの罠)。
    """
    scan, n = _make_forward_scanner(candles, max_horizon, optimistic_fill=False)
    opens = candles["open"].to_numpy(dtype=float)
    closes = candles["close"].to_numpy(dtype=float)
    tr = true_range(candles)
    ref = pd.Series(tr).shift(1).rolling(ref_window, min_periods=ref_window // 2).median().to_numpy()

    follow, fade = Outcome(), Outcome()
    for i in indexes:
        if i >= n - 1 or np.isnan(ref[i]) or ref[i] <= 0:
            continue
        sl_px = sl_atr_mult * float(ref[i])
        tp_px = rr * sl_px
        if sl_px <= 0:
            continue
        entry = float(closes[i])
        cost_points = float(spreads[i]) + extra_spread
        cost_r = (cost_points * point_size) / sl_px

        up = closes[i] >= opens[i]
        for is_buy, bucket in ((up, follow), (not up, fade)):
            if is_buy:
                result = scan(i, entry + tp_px, entry - sl_px, True)
            else:
                result = scan(i, entry - tp_px, entry + sl_px, False)
            if result < 0:
                bucket.unresolved += 1
                continue
            if result == 1:
                bucket.add(rr - cost_r, won=True)
            else:
                bucket.add(-1.0 - cost_r, won=False)
    return follow, fade


def _print_outcome(label: str, outcome: Outcome, breakeven: float) -> None:
    if not outcome.trades:
        print(f"{label:<20}{'-':>8}{'-':>9}{'-':>10}{'-':>9}{outcome.unresolved:>10}")
        return
    print(
        f"{label:<20}{outcome.trades:>8}{outcome.win_rate:>8.1f}%{outcome.ev_r:>+10.3f}"
        f"{outcome.stderr_r:>9.3f}{outcome.unresolved:>10}{breakeven:>10.1f}%"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="決まった時刻の急変を探し、その後に乗れるかを測る")
    parser.add_argument("--candles-file", required=True)
    parser.add_argument("--spike-mult", type=float, default=3.0, help="直近の値幅中央値の何倍で急変とみなすか(既定3.0)")
    parser.add_argument("--ref-window", type=int, default=96, help="値幅の基準にする直前のバー数(既定96=M15で1日)")
    parser.add_argument("--min-spikes", type=int, default=5, help="前半・後半それぞれで必要な急変の最低件数")
    parser.add_argument("--rate-factor", type=float, default=2.0, help="全体の急変率の何倍で『集中』とみなすか")
    parser.add_argument("--sl-atr-mult", type=float, default=2.0, help="SL幅(直近値幅中央値の倍率)")
    parser.add_argument("--rr", type=float, default=1.5, help="リスクリワード比")
    parser.add_argument("--extra-spread", type=float, default=0.0, help="発表時のスプレッド拡大分(points)を上乗せする")
    parser.add_argument("--max-horizon", type=int, default=192, help="決済までに見る最大バー数")
    parser.add_argument("--point-size", type=float, default=None)
    parser.add_argument("--top", type=int, default=15, help="表示する時刻マスの数")
    args = parser.parse_args()

    print(f"{args.candles_file} を読み込んでいます...")
    candles = load_candles(args.candles_file)
    point_size = args.point_size or infer_point_size(candles)
    spreads = _spread_series(candles, None)
    spikes = spike_flags(candles, args.ref_window, args.spike_mult)

    total_spikes = int(spikes.sum())
    baseline_rate = total_spikes / len(candles) * 100
    span = pd.DatetimeIndex(candles["time"])
    print(
        f"{len(candles):,}本 / {span[0].date()}〜{span[-1].date()} / "
        f"急変 {total_spikes:,}本(全体の{baseline_rate:.2f}%)"
    )
    if total_spikes < 50:
        print("急変が少なすぎます。--spike-mult を下げて再実行してください。")
        return

    cells = build_cells(candles, spikes)
    kept = replicated_cells(cells, baseline_rate, args.rate_factor, args.min_spikes)

    print(f"\n=== 第1部: 急変が集中している時刻(UTC) ===")
    print(f"全{len(cells)}マス中、前半・後半の両方で全体の{args.rate_factor:g}倍以上だったのは {len(kept)}マス")
    if not kept:
        print(
            "\n→ 決まった時刻に集中している急変は見つかりませんでした。"
            "\n  『スケジュール済みイベント』という前提が成り立たないため、この案はここで終わり。"
            "\n  (--spike-mult や --rate-factor を緩めて再確認する価値はある)"
        )
        return

    print(f"\n{'時刻(UTC)':<14}{'バー数':>8}{'急変':>7}{'急変率':>9}{'前半':>9}{'後半':>9}")
    for cell in kept[: args.top]:
        print(
            f"{cell.label:<14}{cell.bars:>8}{cell.spikes:>7}{cell.rate:>8.1f}%"
            f"{cell.rate_first:>8.1f}%{cell.rate_second:>8.1f}%"
        )
    if len(kept) > args.top:
        print(f"...他{len(kept) - args.top}マス")

    keys = {(c.weekday, c.hour, c.minute) for c in kept}
    times = pd.DatetimeIndex(candles["time"])
    in_cell = np.array(
        [(int(w), int(h), int(m)) in keys for w, h, m in zip(times.weekday, times.hour, times.minute)]
    )
    event_indexes = [i for i in range(len(candles)) if in_cell[i] and spikes[i]]
    control_indexes = [i for i in range(len(candles)) if in_cell[i] and not spikes[i]]

    breakeven = 1.0 / (1.0 + args.rr) * 100
    print(f"\n=== 第2部: 急変の後、続くのか戻るのか ===")
    print(
        f"SL={args.sl_atr_mult:g}×直近値幅 / RR=1:{args.rr:g} / "
        f"スプレッド=実測+{args.extra_spread:g}pt / 期限={args.max_horizon}本"
    )
    print(f"{'':<20}{'件数':>8}{'勝率':>9}{'EV(R)':>10}{'誤差':>9}{'未決着':>10}{'まぐれ':>10}")

    follow, fade = measure_entries(
        candles, event_indexes, args.sl_atr_mult, args.rr, point_size,
        spreads, args.extra_spread, args.ref_window, args.max_horizon,
    )
    _print_outcome("急変に追従", follow, breakeven)
    _print_outcome("急変に逆張り", fade, breakeven)

    c_follow, c_fade = measure_entries(
        candles, control_indexes, args.sl_atr_mult, args.rr, point_size,
        spreads, args.extra_spread, args.ref_window, args.max_horizon,
    )
    print(f"{'--- 対照(同じ時刻・急変なし) ---':<20}")
    _print_outcome("  追従", c_follow, breakeven)
    _print_outcome("  逆張り", c_fade, breakeven)

    best = max(follow, fade, key=lambda o: o.ev_r if o.trades else -99)
    best_name = "追従" if best is follow else "逆張り"
    control = c_follow if best is follow else c_fade

    print(
        "\n※EV(R)は1トレードあたりの期待値をSL幅=1として表したもの。プラスなら期待値がある。"
        "\n※『まぐれ』はランダムな売買での勝率。これを超えて初めて意味がある。"
        "\n※追従と逆張りは**別々の分母**で数えている。件数が一致する実装は、"
        "\n  片方が未決着のときにもう片方まで捨てている疑いがある。"
        "\n※対照は『同じ時刻だが急変していないバー』。ここと差が無いなら、"
        "\n  効いているのは急変ではなく単なる時間帯であって、発表を狙う意味がない。"
    )

    if not best.trades:
        print("\n→ 決着した取引がありませんでした。--max-horizon を伸ばしてください。")
    elif best.ev_r <= 0:
        print(
            f"\n→ 追従 {follow.ev_r:+.3f}R / 逆張り {fade.ev_r:+.3f}R。**どちらもマイナス。**"
            "\n  急変の後、片方に乗って走る動きは無い(往復ビンタになっている)。"
            "\n  発表前に両側へストップを置く戦略は、この銘柄・この設定では成立しない。"
            "\n  --extra-spread を0にしてもマイナスなら、コストの問題ですらない。"
        )
    elif not beats(best, control):
        print(
            f"\n→ 『{best_name}』は{best.ev_r:+.3f}Rだが、対照(急変なし)も{control.ev_r:+.3f}Rで、"
            "\n  差は誤差の範囲。**急変であること自体は効いていない。**"
            "\n  効いているとすれば時間帯の方で、それなら発表を待つ必要は無い"
            "\n  (backtest_audit.py --by-hour の領分)。"
        )
    else:
        print(
            f"\n→ 『{best_name}』が {best.ev_r:+.3f}R(対照 {control.ev_r:+.3f}R)。**候補。**"
            "\n  ただしここまでは全期間をまとめた数字。次は必ず次を確認すること:"
            "\n   1. --extra-spread を40〜80まで上げても符号が保つか"
            "\n      (発表時は業者がスプレッドを数倍に広げる。ここで消えるなら実戦では取れない)"
            "\n   2. --sl-atr-mult と --rr を変えても符号が保つか(1マスだけ良いのは偶然)"
            "\n   3. 別の通貨ペア(EURUSD)でも同じ符号が出るか"
        )


if __name__ == "__main__":
    main()
