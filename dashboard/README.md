# ARTEMIS X Dashboard

ARTEMIS(mt5_ai_trader)のWeb管理画面。**現時点ではUIモックのみ**で、MT5・Python
(`mt5_ai_trader/`)側とは一切接続していない、完全に独立したフロントエンドである。

スマホでの片手操作を最優先に設計した、ダーク基調・ミニマルなダッシュボード。
画面下固定のナビゲーションで Home / Trade / Analytics / Settings の4画面を
切り替える。

## できること・できないこと

- ✅ 4画面のUI一式(レスポンシブ、PC/スマホ両対応)
- ✅ START/STOP/EMERGENCY STOPボタン(画面内の状態表示が変わるのみ)
- ✅ Settingsの各トグル・入力欄(その場の見た目が変わるのみ、保存はしない)
- ❌ MT5・Pythonボット・EAとの実際の通信(まだ実装していない)
- ❌ データの永続化(リロードするとモックデータに戻る)

## 技術構成

- [Vite](https://vite.dev/) + [React](https://react.dev/) + TypeScript
- [Tailwind CSS v4](https://tailwindcss.com/)(`src/index.css` の `@theme` でダークパレットを定義)
- 追加の状態管理ライブラリ・ルーターは使用しない(タブ切り替えは`App.tsx`の`useState`のみ)

## ディレクトリ構成

```
dashboard/
  src/
    types/            画面が扱うデータの型定義(将来のAPIレスポンスの形も兼ねる)
    data/mock.ts       UIモック用の静的データ
    api/client.ts       データ取得の唯一の窓口。今はmock.tsを返すだけ。
                        将来Python/MT5側と繋ぐ際はこのファイルだけを書き換えればよい
    components/         再利用可能なUI部品(Card, Button, BottomNav, チャート等)
    pages/               Home / Trade / Analytics / Settings の4画面
    lib/format.ts        通貨・日付等のフォーマット関数
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
