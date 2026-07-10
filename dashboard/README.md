# ARTEMIS X Dashboard

ARTEMIS(mt5_ai_trader)のWeb管理画面。

Home / Trade / Analytics の3画面と、Settingsの大部分は**UIモック**で、
MT5・Python(`mt5_ai_trader/`)側とは接続していない。一方、Settings画面の
「AI判断ロジック」「発注設定」(売買設定)は Python側の `settings_server.py`
と実際にHTTP通信しており、保存すると `mt5_ai_trader/config.json` に書き込まれ、
実行中のボットに反映される(詳細は `mt5_ai_trader/README.md` の
「Dashboardからの設定変更(settings_server.py)」を参照)。

スマホでの片手操作を最優先に設計した、ダーク基調・ミニマルなダッシュボード。
画面下固定のナビゲーションで Home / Trade / Analytics / Settings の4画面を
切り替える。

## できること・できないこと

- ✅ 4画面のUI一式(レスポンシブ、PC/スマホ両対応)
- ✅ START/STOP/EMERGENCY STOPボタン(画面内の状態表示が変わるのみ、まだ未接続)
- ✅ Settings画面上部「AI判断ロジック」「発注設定」: `settings_server.py`
  経由でPython側の実際の設定を取得・保存できる(ORDER_VOLUME/SL_POINTS/
  TP_POINTS/TIMEFRAME/LOOP_INTERVAL_SECONDS/RSI_OVERBOUGHT/RSI_OVERSOLD/
  EMA_FAST_PERIOD/EMA_SLOW_PERIOD/Entry Strictness/ENABLE_ORDERS/DEMO_ONLY)
- ✅ Settingsのそれ以外の項目(Discord/通知/VPS/AI判断エンジン選択/MT5参考情報)
  はその場の見た目が変わるのみで保存はしない
- ❌ Home/Trade/AnalyticsのMT5・Pythonボット・EAとの実際の通信(まだ実装していない)
- ❌ Discord/VPS/通知設定の永続化(リロードするとモックデータに戻る)

## 技術構成

- [Vite](https://vite.dev/) + [React](https://react.dev/) + TypeScript
- [Tailwind CSS v4](https://tailwindcss.com/)(`src/index.css` の `@theme` でダークパレットを定義)
- 追加の状態管理ライブラリ・ルーターは使用しない(タブ切り替えは`App.tsx`の`useState`のみ)

## ディレクトリ構成

```
dashboard/
  src/
    types/                    画面が扱うデータの型定義(将来のAPIレスポンスの形も兼ねる)
    data/mock.ts               UIモック用の静的データ
    api/client.ts               モックデータ取得の窓口(Home/Trade/Analytics/Settingsの大部分)
    api/settingsApi.ts          settings_server.py(Python)への実際のfetch()クライアント。
                                売買設定(TradingSettings)のみここを通る
    lib/tradingSettingsSchema.ts 売買設定のクライアント側バリデーション(Python側のsettings_schema.pyと対応)
    components/                 再利用可能なUI部品(Card, Button, BottomNav, チャート等)
    components/settings/TradingSettings.tsx  売買設定フォーム本体(Python側と実際に接続)
    pages/                       Home / Trade / Analytics / Settings の4画面
    lib/format.ts                通貨・日付等のフォーマット関数
```

### 将来の接続に備えた設計

すべてのページは `src/api/client.ts` の関数(`getHomeSummary()` 等)経由でのみ
データを取得し、`src/data/mock.ts` を直接importしない。将来、Pythonボット側
(`mt5_ai_trader/logs/` や、将来追加されるDB・APIサーバー)と接続する際は、
`api/client.ts` の各関数の中身を実際の`fetch()`呼び出しに差し替えるだけで、
ページ・コンポーネント側のコードは変更不要になるよう設計している。

## 起動方法

Node.js 20以上を推奨。

```
cd dashboard
npm install
npm run dev
```

表示されるURL(既定 http://localhost:5173 )をブラウザで開く。スマホ実機で
確認する場合は `npm run dev -- --host` で同一Wi-Fi内の他端末からアクセスできる。

### 売買設定(Settings画面上部)を実際に使うには

Settings画面の「AI判断ロジック」「発注設定」を動かすには、PC側で
`mt5_ai_trader/settings_server.py` を別途起動しておく必要がある(詳細は
`mt5_ai_trader/README.md` 参照)。

```
cd mt5_ai_trader
python settings_server.py
```

DashboardはVite環境変数で接続先を指定する。プロジェクト直下(`dashboard/`)に
`.env.local` を作成し、`.env.example` を参考に以下を設定する。

```
# PCのブラウザから開く場合は未設定のままでよい(既定 http://localhost:8787)。
# スマホなど別端末から開く場合は必ずPCのLAN IPを指定すること。
VITE_SETTINGS_API_URL=http://192.168.x.x:8787
# settings_server.py側でSETTINGS_API_TOKENを設定した場合のみ、同じ値を設定する。
VITE_SETTINGS_API_TOKEN=
```

`.env.local` は `.gitignore` 対象なので、値を書き換えてもコミットされない。
`settings_server.py` に接続できない場合、Settings画面上部に接続エラーと
再試行ボタンが表示される(既存のHome/Trade/Analyticsのモック表示には影響しない)。

### ビルド

```
npm run build      # dist/ に静的ファイルを出力
npm run preview    # ビルド結果をローカルで確認
```

### Lint / 型チェック

```
npm run lint
npx tsc --noEmit -p tsconfig.app.json
```
