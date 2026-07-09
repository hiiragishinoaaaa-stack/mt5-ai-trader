//+------------------------------------------------------------------+
//|                                       ARTEMIS_MarketFeed.mq5     |
//|                                                                    |
//| ARTEMIS (mt5_ai_trader) file-bridge EA.                          |
//| Writes tick + candle data to a JSON file so that the Python side  |
//| (market_feed.py) can read prices without depending on the        |
//| MetaTrader5 Python API (which suffered from IPC timeouts).        |
//| This EA never sends orders; it only writes market data.           |
//|                                                                    |
//| The output file is written to the terminal's shared "common"      |
//| folder (FILE_COMMON), which is normally:                          |
//|   %APPDATA%\MetaQuotes\Terminal\Common\Files\<InpFileName>        |
//| This path does not depend on which broker's terminal build is    |
//| running, or on the terminal's per-install data-folder hash.       |
//|                                                                    |
//| Writes are made atomic by first writing to a temporary file and   |
//| then renaming it with FileMove(), so the Python side never reads  |
//| a half-written JSON file.                                         |
//|                                                                    |
//| NOTE: Keep this file plain-ASCII (no Japanese/non-ASCII           |
//| characters). Non-ASCII comments/strings in .mq5 files have been   |
//| observed to make MetaEditor misdetect the file's codepage on      |
//| some Windows setups, which corrupts parsing and produces          |
//| "undeclared identifier" errors for symbols declared near the      |
//| corrupted text. See README.md for the Japanese explanation of     |
//| this EA instead.                                                  |
//+------------------------------------------------------------------+
#property copyright "ARTEMIS"
#property version   "1.00"
#property strict

input string          InpSymbol            = "USDJPY";                    // Target symbol
input ENUM_TIMEFRAMES InpTimeframe         = PERIOD_M15;                  // Timeframe
input int             InpBarsCount         = 100;                        // Number of candles to export
input int             InpUpdateIntervalSec = 1;                          // Write interval (seconds)
input string          InpFileName          = "artemis_market_data.json"; // Output file name (in common folder)

string g_tmp_file_name;

//+------------------------------------------------------------------+
int OnInit()
{
   g_tmp_file_name = InpFileName + ".tmp";

   if(!SymbolSelect(InpSymbol, true))
   {
      Print("ARTEMIS: failed to select symbol '", InpSymbol, "'. Check the symbol name.");
      return INIT_FAILED;
   }

   EventSetTimer(MathMax(1, InpUpdateIntervalSec));
   WriteMarketData(); // write once immediately so Python does not have to wait for the first timer tick
   Print("ARTEMIS: started. symbol=", InpSymbol, " timeframe=", TimeframeToString(InpTimeframe),
         " file=", InpFileName, " (common folder)");
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
   string s = EnumToString(tf); // e.g. "PERIOD_M15"
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
      Print("ARTEMIS: failed to get tick, last_error=", GetLastError());
      return;
   }

   // Without ArraySetAsSeries, CopyRates fills the array oldest-first
   // (index 0 = oldest bar). The Python side (indicators.py) expects
   // that same chronological order.
   MqlRates rates[];
   int copied = CopyRates(InpSymbol, InpTimeframe, 0, InpBarsCount, rates);
   if(copied <= 0)
   {
      Print("ARTEMIS: failed to copy rates, last_error=", GetLastError());
      return;
   }

   int handle = FileOpen(g_tmp_file_name, FILE_WRITE | FILE_TXT | FILE_ANSI | FILE_COMMON);
   if(handle == INVALID_HANDLE)
   {
      Print("ARTEMIS: failed to open temp file, last_error=", GetLastError());
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

   // Atomically replace the published file with the freshly written one,
   // so the Python side never reads a half-written JSON file.
   if(!FileMove(g_tmp_file_name, FILE_COMMON, InpFileName, FILE_REWRITE | FILE_COMMON))
   {
      Print("ARTEMIS: failed to rename output file, last_error=", GetLastError());
   }
}
