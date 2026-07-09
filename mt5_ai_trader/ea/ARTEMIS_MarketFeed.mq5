//+------------------------------------------------------------------+
//|                                       ARTEMIS_MarketFeed.mq5     |
//|                                                                    |
//| ARTEMIS (mt5_ai_trader) 用のファイルブリッジEA。                  |
//| MT5 Python API(MetaTrader5パッケージ)がIPC timeoutで安定動作      |
//| しない環境向けに、価格データをJSONファイルへ書き出すだけの        |
//| シンプルなEA。発注は一切行わない。                                |
//|                                                                    |
//| 書き出し先は「共有フォルダ」(FILE_COMMON)固定。パスは通常          |
//|   %APPDATA%\MetaQuotes\Terminal\Common\Files\<InpFileName>        |
//| となり、ブローカーごとのターミナルインストール先やターミナル      |
//| データフォルダのハッシュ名に依存しない。                          |
//|                                                                    |
//| 書き込みは一時ファイルに書いてからFileMove()でリネームする        |
//| ことでアトミックにし、Python側が書きかけの中途半端なJSONを         |
//| 読んでしまうことを防いでいる。                                    |
//+------------------------------------------------------------------+
#property copyright "ARTEMIS"
#property version   "1.00"
#property strict

input string           InpSymbol            = "USDJPY";                     // 対象シンボル
input ENUM_TIMEFRAMES  InpTimeframe         = PERIOD_M15;                   // 時間足
input int               InpBarsCount         = 100;                         // 書き出すローソク足の本数
input int               InpUpdateIntervalSec = 1;                           // 書き出し間隔(秒)
input string           InpFileName          = "artemis_market_data.json";   // 出力ファイル名(共有フォルダ内)

string g_tmp_file_name;

//+------------------------------------------------------------------+
int OnInit()
{
   g_tmp_file_name = InpFileName + ".tmp";

   if(!SymbolSelect(InpSymbol, true))
   {
      Print("ARTEMIS: シンボル '", InpSymbol, "' の選択に失敗しました。銘柄名を確認してください。");
      return INIT_FAILED;
   }

   EventSetTimer(MathMax(1, InpUpdateIntervalSec));
   WriteMarketData(); // 起動直後に1回書き出しておく(Python側の初回起動を待たせない)
   Print("ARTEMIS: 稼働開始。symbol=", InpSymbol, " timeframe=", TimeframeToString(InpTimeframe),
         " file=", InpFileName, " (共有フォルダ)");
   return INIT_SUCCEEDED;
}

//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   EventKillTimer();
}

//+------------------------------------------------------------------+
void OnTimer()
{
   WriteMarketData();
}

//+------------------------------------------------------------------+
string TimeframeToString(ENUM_TIMEFRAMES tf)
{
   string s = EnumToString(tf); // 例: "PERIOD_M15"
   StringReplace(s, "PERIOD_", "");
   return s;
}

//+------------------------------------------------------------------+
string JsonEscape(string value)
{
   StringReplace(value, "\\", "\\\\");
   StringReplace(value, "\"", "\\\"");
   return value;
}

//+------------------------------------------------------------------+
void WriteMarketData()
{
   MqlTick tick;
   if(!SymbolInfoTick(InpSymbol, tick))
   {
      Print("ARTEMIS: ティック取得に失敗しました last_error=", GetLastError());
      return;
   }

   // ArraySetAsSeriesを呼ばない場合、CopyRatesは古い順(index 0 = 最古)に
   // 配列を埋める。Python側(indicators.py)もこの並び順を前提にしている。
   MqlRates rates[];
   int copied = CopyRates(InpSymbol, InpTimeframe, 0, InpBarsCount, rates);
   if(copied <= 0)
   {
      Print("ARTEMIS: ローソク足取得に失敗しました last_error=", GetLastError());
      return;
   }

   int handle = FileOpen(g_tmp_file_name, FILE_WRITE | FILE_TXT | FILE_ANSI | FILE_COMMON);
   if(handle == INVALID_HANDLE)
   {
      Print("ARTEMIS: 一時ファイルのオープンに失敗しました last_error=", GetLastError());
      return;
   }

   string json = "{";
   json += "\"symbol\":\"" + JsonEscape(InpSymbol) + "\",";
   json += "\"timeframe\":\"" + TimeframeToString(InpTimeframe) + "\",";
   json += "\"updated_at\":" + IntegerToString((long)TimeCurrent()) + ",";
   json += "\"tick\":{";
   json += "\"bid\":" + DoubleToString(tick.bid, _Digits) + ",";
   json += "\"ask\":" + DoubleToString(tick.ask, _Digits) + ",";
   json += "\"time\":" + IntegerToString((long)tick.time);
   json += "},";
   json += "\"candles\":[";
   for(int i = 0; i < copied; i++)
   {
      if(i > 0)
         json += ",";
      json += "{";
      json += "\"time\":" + IntegerToString((long)rates[i].time) + ",";
      json += "\"open\":" + DoubleToString(rates[i].open, _Digits) + ",";
      json += "\"high\":" + DoubleToString(rates[i].high, _Digits) + ",";
      json += "\"low\":" + DoubleToString(rates[i].low, _Digits) + ",";
      json += "\"close\":" + DoubleToString(rates[i].close, _Digits) + ",";
      json += "\"tick_volume\":" + IntegerToString((long)rates[i].tick_volume) + ",";
      json += "\"spread\":" + IntegerToString((long)rates[i].spread) + ",";
      json += "\"real_volume\":" + IntegerToString((long)rates[i].real_volume);
      json += "}";
   }
   json += "]";
   json += "}";

   FileWriteString(handle, json);
   FileClose(handle);

   // 一時ファイル→本番ファイルへアトミックにリネーム。
   // Python側が読み込み中に書きかけのJSONを掴むことを防ぐ。
   if(!FileMove(g_tmp_file_name, FILE_COMMON, InpFileName, FILE_REWRITE | FILE_COMMON))
   {
      Print("ARTEMIS: 出力ファイルのリネームに失敗しました last_error=", GetLastError());
   }
}
