//+------------------------------------------------------------------+
//|                                    ARTEMIS_HistoryExport.mq5      |
//|                                                                    |
//| One-shot historical-candle exporter for the offline backtest      |
//| replay tool (mt5_ai_trader/backtest_replay.py).                   |
//|                                                                    |
//| This is a SCRIPT, not an Expert Advisor: it runs once (OnStart())|
//| when dragged onto a chart, writes a single JSON file to the       |
//| terminal's shared "common" folder, and then stops (no OnTick/     |
//| OnTimer, nothing keeps running in the background). It does not    |
//| touch any of ARTEMIS_Bridge.mq5's live files (market data, order  |
//| requests, account state, ...) and can safely be run on the same   |
//| chart, at any time, without interfering with the always-on EA.    |
//|                                                                    |
//| Usage: attach this script to a chart for the symbol/timeframe you |
//| want historical data for (or just set InpSymbol/InpTimeframe      |
//| below; it does not have to match the chart it is attached to),    |
//| adjust InpBarsCount if you want a longer/shorter history, run it  |
//| once, then look for the output file under                        |
//|   %APPDATA%\MetaQuotes\Terminal\Common\Files\                    |
//| (same shared folder ARTEMIS_Bridge.mq5 already uses). Copy that    |
//| file to the VPS's mt5_ai_trader/ directory (or wherever you run   |
//| backtest_replay.py from) and pass its path with --candles-file.   |
//|                                                                    |
//| How much history is actually available depends on the broker's    |
//| server-side history depth for that symbol/timeframe (retail M15   |
//| history is commonly available for a year or more, but this is not |
//| guaranteed). CopyRates() simply returns as many bars as the       |
//| terminal has, which may be fewer than InpBarsCount; check the      |
//| "exported N of M requested bars" message in the Experts log.       |
//|                                                                    |
//| NOTE: Keep this file plain-ASCII, same reasoning as                |
//| ARTEMIS_Bridge.mq5 (see that file's header comment).                |
//+------------------------------------------------------------------+
#property copyright "ARTEMIS"
#property version   "1.00"
#property strict
#property script_show_inputs

input string           InpSymbol     = "USDJPY";                 // Symbol to export
input ENUM_TIMEFRAMES  InpTimeframe  = PERIOD_M15;                // Timeframe to export
input int              InpBarsCount  = 200000;                    // Number of candles to request (actual count depends on broker history depth)
input string           InpOutputFile = "";                        // Output file name (common folder). Leave blank for an automatic name.

//+------------------------------------------------------------------+
//| Same UTC correction as ARTEMIS_Bridge.mq5 (see that file's header |
//| comment for why this is necessary: MQL5 datetimes are in the      |
//| trade server's own clock, not true UTC).                          |
//+------------------------------------------------------------------+
long ToUtcEpoch(datetime server_time)
{
   return (long)server_time - TimeGMTOffset();
}

string TimeframeToString(ENUM_TIMEFRAMES tf)
{
   string s = EnumToString(tf); // e.g. "PERIOD_M15"
   StringReplace(s, "PERIOD_", "");
   return s;
}

string JsonEscape(string value)
{
   StringReplace(value, "\\", "\\\\");
   StringReplace(value, "\"", "\\\"");
   return value;
}

void OnStart()
{
   MqlRates rates[];
   // Without ArraySetAsSeries, CopyRates fills the array oldest-first
   // (index 0 = oldest bar), matching the order backtest_replay.py /
   // indicators.py expect (same convention as ARTEMIS_Bridge.mq5's
   // WriteMarketData()).
   int copied = CopyRates(InpSymbol, InpTimeframe, 0, InpBarsCount, rates);
   if(copied <= 0)
   {
      Print("ARTEMIS_HistoryExport: failed to copy rates for ", InpSymbol,
            " ", TimeframeToString(InpTimeframe), ", last_error=", GetLastError());
      return;
   }
   Print("ARTEMIS_HistoryExport: exported ", copied, " of ", InpBarsCount, " requested bars for ",
         InpSymbol, " ", TimeframeToString(InpTimeframe));

   string output_file = InpOutputFile;
   if(output_file == "")
   {
      output_file = "artemis_history_" + InpSymbol + "_" + TimeframeToString(InpTimeframe) + ".json";
   }
   string tmp_file = output_file + ".tmp";

   int handle = FileOpen(tmp_file, FILE_WRITE | FILE_TXT | FILE_ANSI | FILE_COMMON);
   if(handle == INVALID_HANDLE)
   {
      Print("ARTEMIS_HistoryExport: failed to open output file, last_error=", GetLastError());
      return;
   }

   // Write the JSON incrementally, one candle per FileWriteString() call,
   // instead of building one giant in-memory string first. Concatenating
   // 100k+ candles into a single MQL5 string balloons to ~10 MB and the
   // repeated reallocation exhausts memory / aborts the script ("Abnormal
   // termination") on large exports. Streaming keeps memory flat and lets
   // us export the broker's full history depth safely.
   int digits = (int)SymbolInfoInteger(InpSymbol, SYMBOL_DIGITS);
   if(digits <= 0)
      digits = _Digits;

   FileWriteString(handle, "{");
   FileWriteString(handle, "\"symbol\":\"" + JsonEscape(InpSymbol) + "\",");
   FileWriteString(handle, "\"timeframe\":\"" + TimeframeToString(InpTimeframe) + "\",");
   FileWriteString(handle, "\"exported_at\":" + IntegerToString(ToUtcEpoch(TimeCurrent())) + ",");
   FileWriteString(handle, "\"candles\":[");
   for(int i = 0; i < copied; i++)
   {
      string row = "";
      if(i > 0)
         row += ",";
      row += "{";
      row += "\"time\":" + IntegerToString(ToUtcEpoch(rates[i].time)) + ",";
      row += "\"open\":" + DoubleToString(rates[i].open, digits) + ",";
      row += "\"high\":" + DoubleToString(rates[i].high, digits) + ",";
      row += "\"low\":" + DoubleToString(rates[i].low, digits) + ",";
      row += "\"close\":" + DoubleToString(rates[i].close, digits) + ",";
      row += "\"spread\":" + IntegerToString((long)rates[i].spread);
      row += "}";
      FileWriteString(handle, row);
   }
   FileWriteString(handle, "]");
   FileWriteString(handle, "}");
   FileClose(handle);

   if(!FileMove(tmp_file, FILE_COMMON, output_file, FILE_REWRITE | FILE_COMMON))
   {
      Print("ARTEMIS_HistoryExport: failed to rename output file, last_error=", GetLastError());
      return;
   }

   Print("ARTEMIS_HistoryExport: wrote ", output_file,
         " (in the terminal's Common\\Files folder). Copy this file to run backtest_replay.py against it.");
}
