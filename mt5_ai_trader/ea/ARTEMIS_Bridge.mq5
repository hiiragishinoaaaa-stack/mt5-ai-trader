//+------------------------------------------------------------------+
//|                                            ARTEMIS_Bridge.mq5    |
//|                                                                    |
//| ARTEMIS (mt5_ai_trader) file-bridge EA.                          |
//|                                                                    |
//| This EA has three jobs, all driven by JSON files in the terminal's|
//| shared "common" folder (FILE_COMMON), so that the Python side     |
//| never needs the MetaTrader5 Python API (which suffered from IPC   |
//| timeouts):                                                        |
//|                                                                    |
//|  1) Market data feed: writes tick + candle data so Python         |
//|     (market_feed.py) can read prices.                             |
//|  2) Order execution (Phase 2): reads an order-request JSON file   |
//|     written by Python (order_executor.py) and, if all safety      |
//|     checks pass, places a market order via CTrade. Writes back a  |
//|     result JSON file so Python can log success/failure.           |
//|  3) Account state feed (Phase 3): writes balance/equity/margin    |
//|     and all open positions so Python (account_feed.py) can show   |
//|     a live account overview on the Dashboard.                    |
//|  4) Trade history feed (Phase 4): writes recently closed trades   |
//|     (matched entry/exit deal pairs) so Python                     |
//|     (trade_history_feed.py) can show real order history and       |
//|     stats on the Dashboard instead of mock data.                  |
//|                                                                    |
//| Order execution is OFF by default (InpEnableOrders=false) and,    |
//| even when enabled, this EA refuses to place any order unless the  |
//| connected account is verified to be a DEMO account. It also caps  |
//| how many of this EA's own positions may be open at once for the   |
//| same symbol: each order request from Python carries a             |
//| "max_positions" value (Python config.MAX_CONCURRENT_POSITIONS,    |
//| Dashboard-adjustable), and this EA counts its own open positions  |
//| (matched by InpMagicNumber) for that symbol and rejects the       |
//| request if the count has already reached that limit.              |
//|                                                                    |
//| The shared folder is normally:                                    |
//|   %APPDATA%\MetaQuotes\Terminal\Common\Files\                    |
//| This path does not depend on which broker's terminal build is    |
//| running, or on the terminal's per-install data-folder hash.       |
//|                                                                    |
//| All timestamps written to these JSON files go through             |
//| ToUtcEpoch(), which corrects MQL5's server-clock datetimes         |
//| (TimeCurrent(), POSITION_TIME, DEAL_TIME, bar times, ...) to true  |
//| UTC via TimeGMTOffset(). Without this, every timestamp the         |
//| Dashboard/Python side reads would be off by the broker server's    |
//| UTC offset (commonly a few hours), since Python/JS always treat    |
//| these integers as true UTC epoch seconds.                          |
//|                                                                    |
//| All file writes (market data, order result) are made atomic by    |
//| first writing to a temporary file and then renaming it with       |
//| FileMove(), so Python never reads a half-written file.             |
//|                                                                    |
//| NOTE: Keep this file plain-ASCII (no Japanese/non-ASCII           |
//| characters). Non-ASCII comments/strings in .mq5 files have been   |
//| observed to make MetaEditor misdetect the file's codepage on      |
//| some Windows setups, which corrupts parsing and produces          |
//| "undeclared identifier" errors. See README.md for the Japanese    |
//| explanation of this EA instead.                                   |
//+------------------------------------------------------------------+
#property copyright "ARTEMIS"
#property version   "4.02"
#property strict

#include <Trade\Trade.mqh>

//--- market data settings
input string           InpSymbol            = "USDJPY";                    // Target symbol
input ENUM_TIMEFRAMES  InpTimeframe         = PERIOD_M15;                  // Timeframe
input int              InpBarsCount         = 100;                        // Number of candles to export
input int              InpUpdateIntervalSec = 1;                          // Write interval (seconds)
input string           InpFileName          = "artemis_market_data.json"; // Market data output file (common folder)

//--- account/position state settings (Phase 3: Dashboard balance/positions)
input string           InpAccountStateFile  = "artemis_account_state.json"; // Account+position output file (common folder)

//--- trade history settings (Phase 4: Dashboard order history / stats)
input string           InpTradeHistoryFile     = "artemis_trade_history.json"; // Closed-trade history output file (common folder)
input int              InpTradeHistoryDays     = 30;                          // How many days back to include
input int              InpTradeHistoryMaxCount = 50;                          // Max closed trades to include (most recent kept)
input int              InpTradeHistoryIntervalSec = 10;                       // Minimum seconds between trade-history rewrites (HistorySelect is heavier than a tick read)

//--- order execution settings (Phase 2)
input bool             InpEnableOrders      = false;                              // Master switch: allow this EA to place orders
input string           InpOrderRequestFile  = "artemis_order_request.json";       // Order request file written by Python
input string           InpOrderResultFile   = "artemis_order_result.json";        // Order result file written by this EA
input ulong            InpMagicNumber       = 990101;                             // Magic number used to tag orders placed by this EA
input int              InpSlippagePoints    = 20;                                 // Allowed slippage (points) for market orders
// Some brokers (confirmed with XM/XMTrading demo servers, and documented as a
// known MQL5 issue with non-expiring demo accounts) report ACCOUNT_TRADE_MODE
// as NOT demo even though the terminal clearly shows "Demo Account". If that
// happens, set this to your verified demo account login number to allow order
// execution anyway. Leave at 0 to rely solely on ACCOUNT_TRADE_MODE.
// NEVER put a real/live account number here.
input long              InpConfirmedDemoAccount = 0;                               // Manual override: your verified DEMO account login (0 = off)

string   g_tmp_file_name;
bool     g_orders_effectively_enabled = false;
CTrade   g_trade;
datetime g_last_trade_history_write = 0;

//+------------------------------------------------------------------+
int OnInit()
{
   g_tmp_file_name = InpFileName + ".tmp";

   if(!SymbolSelect(InpSymbol, true))
   {
      Print("ARTEMIS: failed to select symbol '", InpSymbol, "'. Check the symbol name.");
      return INIT_FAILED;
   }

   Print("ARTEMIS: account info - login=", AccountInfoInteger(ACCOUNT_LOGIN),
         " server=", AccountInfoString(ACCOUNT_SERVER),
         " company=", AccountInfoString(ACCOUNT_COMPANY),
         " trade_mode=", EnumToString((ENUM_ACCOUNT_TRADE_MODE)AccountInfoInteger(ACCOUNT_TRADE_MODE)));

   g_orders_effectively_enabled = InpEnableOrders;
   if(InpEnableOrders && !IsDemoAccount())
   {
      g_orders_effectively_enabled = false;
      Print("ARTEMIS: WARNING - InpEnableOrders is true but this account is NOT recognized as a demo "
            "account. Order execution is forced OFF for safety. If this IS your demo account (some "
            "brokers, e.g. XM/XMTrading, misreport ACCOUNT_TRADE_MODE for demo accounts), set "
            "InpConfirmedDemoAccount to this account's login number (", AccountInfoInteger(ACCOUNT_LOGIN),
            ") to explicitly confirm it and re-add the EA to the chart.");
   }

   g_trade.SetExpertMagicNumber(InpMagicNumber);
   g_trade.SetDeviationInPoints(InpSlippagePoints);

   EventSetTimer(MathMax(1, InpUpdateIntervalSec));
   WriteMarketData(); // write once immediately so Python does not have to wait for the first timer tick
   WriteAccountState();
   WriteTradeHistory();
   Print("ARTEMIS: started. symbol=", InpSymbol, " timeframe=", TimeframeToString(InpTimeframe),
         " file=", InpFileName, " orders_enabled=", g_orders_effectively_enabled, " (common folder)");
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
   WriteAccountState();
   if(TimeCurrent() - g_last_trade_history_write >= InpTradeHistoryIntervalSec)
   {
      WriteTradeHistory();
      g_last_trade_history_write = TimeCurrent();
   }
   ProcessOrderRequest();
}

//+------------------------------------------------------------------+
//| Whether it is safe to treat the connected account as a demo       |
//| account for the purpose of allowing automated order execution.    |
//|                                                                     |
//| ACCOUNT_TRADE_MODE is the official way to do this, but it is       |
//| known to misreport some brokers' demo accounts (confirmed with     |
//| XM/XMTrading, and documented for non-expiring demo accounts in     |
//| general) as not-demo even though the terminal UI shows             |
//| "Demo Account". To work around that without weakening the safety   |
//| guarantee, an explicit user-confirmed account-number override      |
//| (InpConfirmedDemoAccount) is accepted as a second path: it only     |
//| takes effect if the trader has deliberately typed their own         |
//| verified demo account number into the EA's input parameters.       |
//+------------------------------------------------------------------+
bool IsDemoAccount()
{
   if((ENUM_ACCOUNT_TRADE_MODE)AccountInfoInteger(ACCOUNT_TRADE_MODE) == ACCOUNT_TRADE_MODE_DEMO)
      return true;

   long current_login = AccountInfoInteger(ACCOUNT_LOGIN);
   if(InpConfirmedDemoAccount != 0 && current_login == InpConfirmedDemoAccount)
      return true;

   return false;
}

//+------------------------------------------------------------------+
string TimeframeToString(ENUM_TIMEFRAMES tf)
{
   string s = EnumToString(tf); // e.g. "PERIOD_M15"
   StringReplace(s, "PERIOD_", "");
   return s;
}

//+------------------------------------------------------------------+
//| All MQL5 datetime values (TimeCurrent(), POSITION_TIME,           |
//| DEAL_TIME, bar times from CopyRates, ...) are expressed in the    |
//| trade server's own clock, which is commonly offset from true UTC  |
//| (many brokers run their servers a few hours ahead, e.g. UTC+2/+3).|
//| Every place in this EA that writes a Unix-epoch integer into a    |
//| JSON file for Python/the Dashboard to consume must go through     |
//| this helper, since the Python/JS side always treats that integer  |
//| as a true UTC epoch (time.time(), new Date(epoch*1000), daily     |
//| summary UTC day-boundary math, staleness checks, etc.). Without   |
//| this correction, every displayed/compared timestamp is off by     |
//| the server's UTC offset.                                          |
//+------------------------------------------------------------------+
long ToUtcEpoch(datetime server_time)
{
   return (long)server_time - TimeGMTOffset();
}

//+------------------------------------------------------------------+
string JsonEscape(string value)
{
   StringReplace(value, "\\", "\\\\");
   StringReplace(value, "\"", "\\\"");
   return value;
}

//+------------------------------------------------------------------+
//| Minimal hand-rolled JSON value extraction.                       |
//| The request file has a fixed, flat schema written by our own     |
//| Python code, so a full JSON parser is not needed.                |
//|                                                                    |
//| Whitespace right after the ':' is explicitly skipped, because     |
//| Python's json.dump() default output includes a space there        |
//| ("key": value) while a naive compact-JSON assumption ("key":value)|
//| would otherwise fail to find any value at all.                    |
//+------------------------------------------------------------------+
int JsonSkipWhitespace(string json, int pos)
{
   int len = StringLen(json);
   while(pos < len)
   {
      ushort c = StringGetCharacter(json, pos);
      if(c != ' ' && c != '\t' && c != '\r' && c != '\n')
         break;
      pos++;
   }
   return pos;
}

string JsonGetStringValue(string json, string key)
{
   string pattern = "\"" + key + "\":";
   int pos = StringFind(json, pattern);
   if(pos < 0)
      return "";
   int start = JsonSkipWhitespace(json, pos + StringLen(pattern));
   if(StringGetCharacter(json, start) != '"')
      return "";
   start++; // skip the opening quote
   int end = StringFind(json, "\"", start);
   if(end < 0)
      return "";
   return StringSubstr(json, start, end - start);
}

double JsonGetNumberValue(string json, string key, double default_value)
{
   string pattern = "\"" + key + "\":";
   int pos = StringFind(json, pattern);
   if(pos < 0)
      return default_value;
   int start = JsonSkipWhitespace(json, pos + StringLen(pattern));
   int len = StringLen(json);
   int end = start;
   while(end < len)
   {
      ushort c = StringGetCharacter(json, end);
      bool is_number_char = (c >= '0' && c <= '9') || c == '.' || c == '-' || c == '+' || c == 'e' || c == 'E';
      if(!is_number_char)
         break;
      end++;
   }
   if(end == start)
      return default_value;
   return StringToDouble(StringSubstr(json, start, end - start));
}

bool JsonGetBoolValue(string json, string key, bool default_value)
{
   string pattern = "\"" + key + "\":";
   int pos = StringFind(json, pattern);
   if(pos < 0)
      return default_value;
   int start = JsonSkipWhitespace(json, pos + StringLen(pattern));
   if(StringSubstr(json, start, 4) == "true")
      return true;
   if(StringSubstr(json, start, 5) == "false")
      return false;
   return default_value;
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
   json += "\"updated_at\":" + IntegerToString(ToUtcEpoch(TimeCurrent())) + ",";
   json += "\"tick\":{";
   json += "\"bid\":" + DoubleToString(tick.bid, _Digits) + ",";
   json += "\"ask\":" + DoubleToString(tick.ask, _Digits) + ",";
   json += "\"time\":" + IntegerToString(ToUtcEpoch(tick.time));
   json += "},";
   json += "\"candles\":[";
   for(int i = 0; i < copied; i++)
   {
      if(i > 0)
         json += ",";
      json += "{";
      json += "\"time\":" + IntegerToString(ToUtcEpoch(rates[i].time)) + ",";
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
      Print("ARTEMIS: failed to rename market data file, last_error=", GetLastError());
   }
}

//+------------------------------------------------------------------+
//| Phase 3: write account balance/equity/margin and all open         |
//| positions (not just this EA's own trades) so the Dashboard can    |
//| show a live account overview. Written to its own file so a        |
//| parse failure here can never affect market data or order          |
//| processing.                                                       |
//+------------------------------------------------------------------+
void WriteAccountState()
{
   string tmp_name = InpAccountStateFile + ".tmp";
   int handle = FileOpen(tmp_name, FILE_WRITE | FILE_TXT | FILE_ANSI | FILE_COMMON);
   if(handle == INVALID_HANDLE)
   {
      Print("ARTEMIS: failed to open account state temp file, last_error=", GetLastError());
      return;
   }

   string json = "{";
   json += "\"updated_at\":" + IntegerToString(ToUtcEpoch(TimeCurrent())) + ",";
   json += "\"account\":{";
   json += "\"login\":" + IntegerToString((long)AccountInfoInteger(ACCOUNT_LOGIN)) + ",";
   json += "\"currency\":\"" + JsonEscape(AccountInfoString(ACCOUNT_CURRENCY)) + "\",";
   json += "\"balance\":" + DoubleToString(AccountInfoDouble(ACCOUNT_BALANCE), 2) + ",";
   json += "\"equity\":" + DoubleToString(AccountInfoDouble(ACCOUNT_EQUITY), 2) + ",";
   json += "\"margin\":" + DoubleToString(AccountInfoDouble(ACCOUNT_MARGIN), 2) + ",";
   json += "\"margin_free\":" + DoubleToString(AccountInfoDouble(ACCOUNT_MARGIN_FREE), 2) + ",";
   json += "\"profit\":" + DoubleToString(AccountInfoDouble(ACCOUNT_PROFIT), 2);
   json += "},";

   json += "\"positions\":[";
   int total = PositionsTotal();
   int written = 0;
   for(int i = 0; i < total; i++)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0)
         continue;
      if(!PositionSelectByTicket(ticket))
         continue;

      if(written > 0)
         json += ",";
      written++;

      long   type      = PositionGetInteger(POSITION_TYPE);
      string type_str  = (type == POSITION_TYPE_BUY) ? "BUY" : "SELL";
      string pos_symbol = PositionGetString(POSITION_SYMBOL);

      json += "{";
      json += "\"ticket\":" + IntegerToString((long)ticket) + ",";
      json += "\"symbol\":\"" + JsonEscape(pos_symbol) + "\",";
      json += "\"type\":\"" + type_str + "\",";
      json += "\"volume\":" + DoubleToString(PositionGetDouble(POSITION_VOLUME), 2) + ",";
      json += "\"price_open\":" + DoubleToString(PositionGetDouble(POSITION_PRICE_OPEN), _Digits) + ",";
      json += "\"price_current\":" + DoubleToString(PositionGetDouble(POSITION_PRICE_CURRENT), _Digits) + ",";
      json += "\"sl\":" + DoubleToString(PositionGetDouble(POSITION_SL), _Digits) + ",";
      json += "\"tp\":" + DoubleToString(PositionGetDouble(POSITION_TP), _Digits) + ",";
      json += "\"profit\":" + DoubleToString(PositionGetDouble(POSITION_PROFIT), 2) + ",";
      json += "\"open_time\":" + IntegerToString(ToUtcEpoch((datetime)PositionGetInteger(POSITION_TIME))) + ",";
      json += "\"magic\":" + IntegerToString((long)PositionGetInteger(POSITION_MAGIC)) + ",";
      json += "\"is_artemis\":" + ((PositionGetInteger(POSITION_MAGIC) == (long)InpMagicNumber) ? "true" : "false");
      json += "}";
   }
   json += "]";
   json += "}";

   FileWriteString(handle, json);
   FileClose(handle);

   if(!FileMove(tmp_name, FILE_COMMON, InpAccountStateFile, FILE_REWRITE | FILE_COMMON))
   {
      Print("ARTEMIS: failed to rename account state file, last_error=", GetLastError());
   }
}

//+------------------------------------------------------------------+
//| Counts this EA's own open positions (matched by InpMagicNumber)   |
//| for the given symbol. Used by ProcessOrderRequest() to enforce    |
//| max_positions. Manually-opened or other-EA positions on the same  |
//| symbol are not counted, matching the is_artemis distinction used  |
//| elsewhere (WriteAccountState/WriteTradeHistory).                  |
//+------------------------------------------------------------------+
int CountArtemisPositions(string symbol)
{
   int count = 0;
   int total = PositionsTotal();
   for(int i = 0; i < total; i++)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0)
         continue;
      if(!PositionSelectByTicket(ticket))
         continue;
      if(PositionGetString(POSITION_SYMBOL) != symbol)
         continue;
      if(PositionGetInteger(POSITION_MAGIC) != (long)InpMagicNumber)
         continue;
      count++;
   }
   return count;
}

//+------------------------------------------------------------------+
//| Phase 4: write recently closed trades (matched entry/exit deal    |
//| pairs) so the Dashboard can show real order history / stats       |
//| instead of mock data. MQL5 has no built-in map type, so entry     |
//| deals are collected into a small array and matched to their exit  |
//| deal by POSITION_ID as the deal history (chronological) is        |
//| scanned. Deals whose entry falls outside the lookback window are  |
//| skipped (no matching entry found).                                 |
//+------------------------------------------------------------------+
struct ArtemisTradeEntry
{
   long   position_id;
   string symbol;
   string type;
   double volume;
   double price;
   long   time;
};

void WriteTradeHistory()
{
   datetime from = TimeCurrent() - (datetime)(InpTradeHistoryDays * 86400);
   if(!HistorySelect(from, TimeCurrent()))
   {
      Print("ARTEMIS: failed to select deal history, last_error=", GetLastError());
      return;
   }

   int total = HistoryDealsTotal();
   ArtemisTradeEntry entries[];
   ArrayResize(entries, 0);

   string json = "{";
   json += "\"updated_at\":" + IntegerToString(ToUtcEpoch(TimeCurrent())) + ",";
   json += "\"trades\":[";

   int written = 0;
   for(int i = 0; i < total; i++)
   {
      ulong deal_ticket = HistoryDealGetTicket(i);
      if(deal_ticket == 0)
         continue;

      long deal_type = HistoryDealGetInteger(deal_ticket, DEAL_TYPE);
      if(deal_type != DEAL_TYPE_BUY && deal_type != DEAL_TYPE_SELL)
         continue; // skip balance/credit/correction pseudo-deals

      long position_id = (long)HistoryDealGetInteger(deal_ticket, DEAL_POSITION_ID);
      long entry_flag   = HistoryDealGetInteger(deal_ticket, DEAL_ENTRY);

      if(entry_flag == DEAL_ENTRY_IN)
      {
         ArtemisTradeEntry e;
         e.position_id = position_id;
         e.symbol      = HistoryDealGetString(deal_ticket, DEAL_SYMBOL);
         e.type        = (deal_type == DEAL_TYPE_BUY) ? "BUY" : "SELL";
         e.volume      = HistoryDealGetDouble(deal_ticket, DEAL_VOLUME);
         e.price       = HistoryDealGetDouble(deal_ticket, DEAL_PRICE);
         e.time        = ToUtcEpoch((datetime)HistoryDealGetInteger(deal_ticket, DEAL_TIME));

         int n = ArraySize(entries);
         ArrayResize(entries, n + 1);
         entries[n] = e;
         continue;
      }

      if(entry_flag != DEAL_ENTRY_OUT && entry_flag != DEAL_ENTRY_OUT_BY)
         continue;

      int match = -1;
      for(int k = 0; k < ArraySize(entries); k++)
      {
         if(entries[k].position_id == position_id)
         {
            match = k;
            break;
         }
      }
      if(match < 0)
         continue; // entry deal is outside the lookback window; skip this exit

      double exit_price = HistoryDealGetDouble(deal_ticket, DEAL_PRICE);
      double profit = HistoryDealGetDouble(deal_ticket, DEAL_PROFIT)
                     + HistoryDealGetDouble(deal_ticket, DEAL_SWAP)
                     + HistoryDealGetDouble(deal_ticket, DEAL_COMMISSION);
      long close_time = ToUtcEpoch((datetime)HistoryDealGetInteger(deal_ticket, DEAL_TIME));
      long magic = HistoryDealGetInteger(deal_ticket, DEAL_MAGIC);

      if(written > 0)
         json += ",";
      written++;

      json += "{";
      json += "\"position_id\":" + IntegerToString(position_id) + ",";
      json += "\"symbol\":\"" + JsonEscape(entries[match].symbol) + "\",";
      json += "\"type\":\"" + entries[match].type + "\",";
      json += "\"volume\":" + DoubleToString(entries[match].volume, 2) + ",";
      json += "\"price_open\":" + DoubleToString(entries[match].price, _Digits) + ",";
      json += "\"price_close\":" + DoubleToString(exit_price, _Digits) + ",";
      json += "\"profit\":" + DoubleToString(profit, 2) + ",";
      json += "\"open_time\":" + IntegerToString(entries[match].time) + ",";
      json += "\"close_time\":" + IntegerToString(close_time) + ",";
      json += "\"magic\":" + IntegerToString(magic) + ",";
      json += "\"is_artemis\":" + ((magic == (long)InpMagicNumber) ? "true" : "false");
      json += "}";

      if(written >= InpTradeHistoryMaxCount)
         break;
   }

   json += "]}";

   string tmp_name = InpTradeHistoryFile + ".tmp";
   int handle = FileOpen(tmp_name, FILE_WRITE | FILE_TXT | FILE_ANSI | FILE_COMMON);
   if(handle == INVALID_HANDLE)
   {
      Print("ARTEMIS: failed to open trade history temp file, last_error=", GetLastError());
      return;
   }
   FileWriteString(handle, json);
   FileClose(handle);

   if(!FileMove(tmp_name, FILE_COMMON, InpTradeHistoryFile, FILE_REWRITE | FILE_COMMON))
   {
      Print("ARTEMIS: failed to rename trade history file, last_error=", GetLastError());
   }
}

//+------------------------------------------------------------------+
//| Phase 2: read an order request written by Python and, if all      |
//| safety checks pass, place a market order. Always writes back a    |
//| result file so Python can log success/failure.                    |
//+------------------------------------------------------------------+
void ProcessOrderRequest()
{
   if(!g_orders_effectively_enabled)
      return;

   if(!FileIsExist(InpOrderRequestFile, FILE_COMMON))
      return;

   int handle = FileOpen(InpOrderRequestFile, FILE_READ | FILE_TXT | FILE_ANSI | FILE_COMMON);
   if(handle == INVALID_HANDLE)
   {
      Print("ARTEMIS: failed to open order request file, last_error=", GetLastError());
      return;
   }

   string json = "";
   while(!FileIsEnding(handle))
      json += FileReadString(handle);
   FileClose(handle);

   // Consume the request immediately so it is processed exactly once,
   // even if the order placement below fails.
   FileDelete(InpOrderRequestFile, FILE_COMMON);

   string request_id = JsonGetStringValue(json, "request_id");
   string action      = JsonGetStringValue(json, "action");
   string symbol      = JsonGetStringValue(json, "symbol");
   double volume      = JsonGetNumberValue(json, "volume", 0.0);
   double sl_points   = JsonGetNumberValue(json, "sl_points", 0.0);
   double tp_points   = JsonGetNumberValue(json, "tp_points", 0.0);
   int    max_positions = (int)JsonGetNumberValue(json, "max_positions", 1.0);
   bool   demo_only   = JsonGetBoolValue(json, "demo_only", false);

   if(max_positions < 1)
      max_positions = 1; // older Python builds may omit this field; also guards against a bad/zero value

   if(request_id == "")
   {
      Print("ARTEMIS: order request file could not be parsed, ignoring it");
      return;
   }

   if(!demo_only)
   {
      WriteOrderResult(request_id, false, "rejected: demo_only flag was not true", 0, 0);
      return;
   }
   if(!IsDemoAccount())
   {
      WriteOrderResult(request_id, false,
                        "rejected: this account is not recognized as a demo account "
                        "(set InpConfirmedDemoAccount if this is actually your demo account)",
                        0, 0);
      return;
   }
   if(symbol != InpSymbol)
   {
      WriteOrderResult(request_id, false, "rejected: symbol mismatch (" + symbol + " vs " + InpSymbol + ")", 0, 0);
      return;
   }
   if(action != "BUY" && action != "SELL")
   {
      WriteOrderResult(request_id, false, "rejected: unknown action '" + action + "'", 0, 0);
      return;
   }
   if(volume <= 0.0)
   {
      WriteOrderResult(request_id, false, "rejected: invalid volume", 0, 0);
      return;
   }
   int existing_positions = CountArtemisPositions(symbol);
   if(existing_positions >= max_positions)
   {
      WriteOrderResult(request_id, false,
                        "skipped: max_positions reached (" + IntegerToString(existing_positions) +
                        "/" + IntegerToString(max_positions) + ") for this symbol", 0, 0);
      return;
   }

   double point = SymbolInfoDouble(symbol, SYMBOL_POINT);
   bool ok;
   if(action == "BUY")
   {
      double price = SymbolInfoDouble(symbol, SYMBOL_ASK);
      double sl = (sl_points > 0.0) ? price - sl_points * point : 0.0;
      double tp = (tp_points > 0.0) ? price + tp_points * point : 0.0;
      ok = g_trade.Buy(volume, symbol, 0.0, sl, tp, "ARTEMIS");
   }
   else
   {
      double price = SymbolInfoDouble(symbol, SYMBOL_BID);
      double sl = (sl_points > 0.0) ? price + sl_points * point : 0.0;
      double tp = (tp_points > 0.0) ? price - tp_points * point : 0.0;
      ok = g_trade.Sell(volume, symbol, 0.0, sl, tp, "ARTEMIS");
   }

   uint   retcode = g_trade.ResultRetcode();
   ulong  ticket  = g_trade.ResultOrder();
   string message = ok ? "order sent" : ("order failed: " + g_trade.ResultRetcodeDescription());

   Print("ARTEMIS: order ", action, " ", symbol, " volume=", DoubleToString(volume, 2),
         " ok=", ok, " retcode=", retcode, " ticket=", ticket);

   WriteOrderResult(request_id, ok, message, (long)retcode, (long)ticket);
}

//+------------------------------------------------------------------+
void WriteOrderResult(string request_id, bool success, string message, long retcode, long ticket)
{
   string tmp_name = InpOrderResultFile + ".tmp";
   int handle = FileOpen(tmp_name, FILE_WRITE | FILE_TXT | FILE_ANSI | FILE_COMMON);
   if(handle == INVALID_HANDLE)
   {
      Print("ARTEMIS: failed to open order result temp file, last_error=", GetLastError());
      return;
   }

   string json = "{";
   json += "\"request_id\":\"" + JsonEscape(request_id) + "\",";
   json += "\"processed_at\":" + IntegerToString(ToUtcEpoch(TimeCurrent())) + ",";
   json += "\"success\":" + (success ? "true" : "false") + ",";
   json += "\"retcode\":" + IntegerToString(retcode) + ",";
   json += "\"ticket\":" + IntegerToString(ticket) + ",";
   json += "\"message\":\"" + JsonEscape(message) + "\"";
   json += "}";

   FileWriteString(handle, json);
   FileClose(handle);

   if(!FileMove(tmp_name, FILE_COMMON, InpOrderResultFile, FILE_REWRITE | FILE_COMMON))
   {
      Print("ARTEMIS: failed to rename order result file, last_error=", GetLastError());
   }
}
