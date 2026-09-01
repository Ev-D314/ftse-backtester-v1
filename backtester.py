
import yfinance as yf
import pandas as pd

#Downloads FTSE100 data from YoohooFinance
ticker = "^FTSE"
data = yf.download(ticker, period="60d", interval="5m", progress=False)
data.to_csv("ftse_5min.csv")

#Creates dictionary of variables in used terms and reshapes Yahoo data in this way
data.columns = data.columns.get_level_values(0)
ohlc_rules = {
    'Open': 'first',
    'High': 'max',
    'Low': 'min',
    'Close': 'last'
}
hourly = data.resample('1h').agg(ohlc_rules)
four_hour = data.resample('4h').agg(ohlc_rules)
four_hour = four_hour[four_hour['High'].notna()]
five_min = data.resample('5min').agg(ohlc_rules)
fifteen_min = data.resample('15min').agg(ohlc_rules)

#Defines difference in time between candles
time_gaps = hourly.index.to_series().diff()

#Function that defines candle type, previous candle type, previous high and low
def prepare_candles(df, expected_gap):
    df['Type'] = 'bearish'
    df.loc[df['Close'] > df['Open'], 'Type'] = 'bullish'
    df = df[df['Open'].notna()]
    
    df['PrevType'] = df['Type'].shift(1)
    df['TimeGap'] = df.index.to_series().diff()
    valid_pair = df['TimeGap'] == expected_gap
    
    df['PrevHigh'] = df['High'].shift(1)
    df['PrevLow'] = df['Low'].shift(1)
    
    return df, valid_pair

hourly, valid_pair_1h = prepare_candles(hourly, pd.Timedelta(hours=1))
four_hour, valid_pair_4h = prepare_candles(four_hour, pd.Timedelta(hours=4))
fifteen_min, valid_pair_15m = prepare_candles(fifteen_min, pd.Timedelta(minutes=15))

#Function that defines FVGs
def detect_fvg(df):
    df['High_2back'] = df['High'].shift(2)
    df['Low_2back'] = df['Low'].shift(2)
    df['BullishFVG'] = df['High_2back'] < df['Low']
    df['BearishFVG'] = df['Low_2back'] > df['High']

#Defines swing highs and swing lows on the 1hr timeframe
is_swing_high = valid_pair_1h & (hourly['PrevType'] == 'bullish') & (hourly['Type'] == 'bearish')
is_swing_low = valid_pair_1h & (hourly['PrevType'] == 'bearish') & (hourly['Type'] == 'bullish')

#Creates an empty column that is only filled if these swing points are found
hourly['SwingHigh'] = None
hourly['SwingLow'] = None

#How to find the value of the swing high
hourly.loc[is_swing_high, 'SwingHigh'] = hourly.loc[is_swing_high, ['PrevHigh', 'High']].max(axis=1)
hourly.loc[is_swing_low, 'SwingLow'] = hourly.loc[is_swing_low, ['PrevLow', 'Low']].min(axis=1)

detect_fvg(hourly)

#Defines swing highs and swing lows on the 4hr timeframe
is_swing_high = valid_pair_4h & (four_hour['PrevType'] == 'bullish') & (four_hour['Type'] == 'bearish')
is_swing_low = valid_pair_4h & (four_hour['PrevType'] == 'bearish') & (four_hour['Type'] == 'bullish')

#Creates an empty column that is only filled if these swing points are found
four_hour['SwingHigh'] = None
four_hour['SwingLow'] = None

#How to find the value of the swing high
four_hour.loc[is_swing_high, 'SwingHigh'] = four_hour.loc[is_swing_high, ['PrevHigh', 'High']].max(axis=1)
four_hour.loc[is_swing_low, 'SwingLow'] = four_hour.loc[is_swing_low, ['PrevLow', 'Low']].min(axis=1)

#Function used to find Active Swing Highs and Lows
def carry_forward(df, column_name):
    active_value = None
    result_column = []

    for i in range(len(df)):
        if pd.notna(df[column_name].iloc[i]):
            active_value = df[column_name].iloc[i]
        result_column.append(active_value)

    return result_column

hourly['ActiveSwingHigh'] = carry_forward(hourly, 'SwingHigh')
hourly['ActiveSwingLow'] = carry_forward(hourly, 'SwingLow')
four_hour['ActiveSwingHigh'] = carry_forward(four_hour, 'SwingHigh')
four_hour['ActiveSwingLow'] = carry_forward(four_hour, 'SwingLow')

#Allows the relevant data on 1hr timeframe to be compared to individual 5min candle movement
five_min = five_min.sort_index()
hourly_lookup = hourly[['ActiveSwingHigh', 'ActiveSwingLow']].sort_index()

merged = pd.merge_asof(
    five_min,
    hourly_lookup,
    left_index=True,
    right_index=True,
    direction='backward'       #For each row in five_min find most recent row in hourly_lookup whose timestamp is at or before this one - removes any lookahead bias (no lookahead rule)
)

#Allows the relevant data on 4hr timeframe to be compared to individual 5min candle movement
four_hour_lookup = four_hour[['ActiveSwingHigh', 'ActiveSwingLow']].rename(
    columns={'ActiveSwingHigh': 'ActiveSwingHigh_4h', 'ActiveSwingLow': 'ActiveSwingLow_4h'}
).sort_index()

merged = pd.merge_asof(
    merged,
    four_hour_lookup,
    left_index=True,
    right_index=True,
    direction='backward'       #For each row in five_min find most recent row in hourly_lookup whose timestamp is at or before this one - removes any lookahead bias (no lookahead rule)
)

detect_fvg(merged)

#Function used to find active swing points
def detect_sweeps(df, high_column, low_column):
    active_high = None
    active_low = None
    last_seen_df_low = None
    last_seen_df_high = None
    sweep_high_flags =[]
    sweep_low_flags = []
    active_high_column = []
    active_low_column =[]

    for i in range(len(df)):
        df_high_here = df[high_column].iloc[i]
        df_low_here = df[low_column].iloc[i]

        if pd.notna(df_high_here) and df_high_here != last_seen_df_high:
            active_high = df_high_here
            last_seen_df_high = df_high_here
        if pd.notna(df_low_here) and df_low_here != last_seen_df_low:
            active_low = df_low_here
            last_seen_df_low = df_low_here

        swept_high_now = active_high is not None and merged['High'].iloc[i] > active_high
        swept_low_now = active_low is not None and merged['Low'].iloc[i] < active_low

        sweep_high_flags.append(swept_high_now)
        sweep_low_flags.append(swept_low_now)

        if swept_high_now:
            active_high = None
        if swept_low_now:
            active_low = None

        active_high_column.append(active_high)
        active_low_column.append(active_low)

    return active_high_column, active_low_column, sweep_high_flags, sweep_low_flags

active_high_1h, active_low_1h, sweep_high_1h, sweep_low_1h = detect_sweeps(merged, 'ActiveSwingHigh', 'ActiveSwingLow')
active_high_4h, active_low_4h, sweep_high_4h, sweep_low_4h = detect_sweeps(merged, 'ActiveSwingHigh_4h', 'ActiveSwingLow_4h')

merged['ActiveSwingHigh'] = active_high_1h
merged['ActiveSwingLow'] = active_low_1h
merged['SweptHigh'] = pd.Series(sweep_high_1h, index=merged.index) | pd.Series(sweep_high_4h, index=merged.index)
merged['SweptLow'] = pd.Series(sweep_low_1h, index=merged.index) | pd.Series(sweep_low_4h, index=merged.index)

#This loop tracks the most recent bullish 5min FVGs
active_bullish_fvg_top = None
active_bullish_fvg_bottom = None
bullish_fvg_top_column = []
bullish_fvg_bottom_column = []

for i in range(len(merged)):
    if merged['BullishFVG'].iloc[i]:
        active_bullish_fvg_top = merged['Low'].iloc[i]
        active_bullish_fvg_bottom = merged['High_2back'].iloc[i]

    bullish_fvg_top_column.append(active_bullish_fvg_top)
    bullish_fvg_bottom_column.append(active_bullish_fvg_bottom)

merged['ActiveBullishFVG_Top'] = bullish_fvg_top_column
merged['ActiveBullishFVG_Bottom'] = bullish_fvg_bottom_column

#This loop tracks the most recent bearish 5min FVGs
active_bearish_fvg_top = None
active_bearish_fvg_bottom = None
bearish_fvg_top_column = []
bearish_fvg_bottom_column = []

for i in range(len(merged)):
    if merged['BearishFVG'].iloc[i]:
        active_bearish_fvg_top = merged['Low_2back'].iloc[i]
        active_bearish_fvg_bottom = merged['High'].iloc[i]

    bearish_fvg_top_column.append(active_bearish_fvg_top)
    bearish_fvg_bottom_column.append(active_bearish_fvg_bottom)

merged['ActiveBearishFVG_Top'] = bearish_fvg_top_column
merged['ActiveBearishFVG_Bottom'] = bearish_fvg_bottom_column

#Defines that after a sweep has occured, look for the most recent 5min FVG
merged['SetupFVG_Top'] = None
merged['SetupFVG_Bottom'] = None
merged['SetupDirection'] = None

merged.loc[merged['SweptHigh'], 'SetupFVG_Top'] = merged.loc[merged['SweptHigh'], 'ActiveBullishFVG_Top']
merged.loc[merged['SweptHigh'], 'SetupFVG_Bottom'] = merged.loc[merged['SweptHigh'], 'ActiveBullishFVG_Bottom']
merged.loc[merged['SweptHigh'], 'SetupDirection'] = 'short'

merged.loc[merged['SweptLow'], 'SetupFVG_Top'] = merged.loc[merged['SweptLow'], 'ActiveBearishFVG_Top']
merged.loc[merged['SweptLow'], 'SetupFVG_Bottom'] = merged.loc[merged['SweptLow'], 'ActiveBearishFVG_Bottom']
merged.loc[merged['SweptLow'], 'SetupDirection'] = 'long'

merged.loc[merged['SetupFVG_Top'].isna(), 'SetupDirection'] = None   

#Defines swing highs and swing lows on the 15min timeframe
is_swing_high = valid_pair_15m & (fifteen_min['PrevType'] == 'bullish') & (fifteen_min['Type'] == 'bearish')
is_swing_low = valid_pair_15m & (fifteen_min['PrevType'] == 'bearish') & (fifteen_min['Type'] == 'bullish')

#Creates an empty column that is only filled if these swing points are found
fifteen_min['SwingHigh'] = None
fifteen_min['SwingLow'] = None

#How to find the value of the swing high
fifteen_min.loc[is_swing_high, 'SwingHigh'] = fifteen_min.loc[is_swing_high, ['PrevHigh', 'High']].max(axis=1)
fifteen_min.loc[is_swing_low, 'SwingLow'] = fifteen_min.loc[is_swing_low, ['PrevLow', 'Low']].min(axis=1)

detect_fvg(fifteen_min)

#Evaluates if a trade is worth taking
def evaluate_candidates(candidate_prices, entry_price, sl_price):
    if candidate_prices.empty:
        return None, None
    distances = abs(candidate_prices - entry_price)
    best_idx = distances.idxmin()
    best_price = candidate_prices.loc[best_idx]

    reward = abs(best_price - entry_price)
    risk = abs(entry_price - sl_price)
    rr = reward / risk

    if rr >= 1:
        return best_price, rr
    else:
        return None, rr

#Finds TP for trade
def find_tp(entry_time, entry_price, sl_price, direction):
    candidates_fifteen = fifteen_min[fifteen_min.index < entry_time]
    candidates_hourly = hourly[hourly.index < entry_time]

    if direction == 'short':
        layer1_candidates = candidates_fifteen[candidates_fifteen['SwingLow'].notna() & (candidates_fifteen['SwingLow'] < entry_price)]['SwingLow']
        best_price, rr = evaluate_candidates(layer1_candidates, entry_price, sl_price)

        if best_price is not None:
            return best_price, rr

        layer2_candidates = candidates_fifteen[candidates_fifteen['BullishFVG'] & (candidates_fifteen['Low'] < entry_price)]['Low']
        best_price, rr = evaluate_candidates(layer2_candidates, entry_price, sl_price)

        if best_price is not None:
            return best_price, rr

        layer3_candidates = candidates_hourly[candidates_hourly['SwingLow'].notna() & (candidates_hourly['SwingLow'] < entry_price)]['SwingLow']
        best_price, rr = evaluate_candidates(layer3_candidates, entry_price, sl_price) 

        if best_price is not None:
            return best_price, rr

        layer4_candidates = candidates_hourly[candidates_hourly['BullishFVG'] & (candidates_hourly['Low'] < entry_price)]['Low']
        best_price, rr = evaluate_candidates(layer4_candidates, entry_price, sl_price)

        if best_price is not None:
            return best_price, rr

    elif direction == 'long':
        layer1_candidates = candidates_fifteen[candidates_fifteen['SwingHigh'].notna() & (candidates_fifteen['SwingHigh'] > entry_price)]['SwingHigh']
        best_price, rr = evaluate_candidates(layer1_candidates, entry_price, sl_price)

        if best_price is not None:
            return best_price, rr

        layer2_candidates = candidates_fifteen[candidates_fifteen['BearishFVG'] & (candidates_fifteen['High'] > entry_price)]['High']
        best_price, rr = evaluate_candidates(layer2_candidates, entry_price, sl_price)
        
        if best_price is not None:
            return best_price, rr

        layer3_candidates = candidates_hourly[candidates_hourly['SwingHigh'].notna() & (candidates_hourly['SwingHigh'] > entry_price)]['SwingHigh']
        best_price, rr = evaluate_candidates(layer3_candidates, entry_price, sl_price) 
        
        if best_price is not None:
            return best_price, rr

        layer4_candidates = candidates_hourly[candidates_hourly['BearishFVG'] & candidates_hourly['High'] > entry_price]['High']
        best_price, rr = evaluate_candidates(layer4_candidates, entry_price, sl_price)
        
        if best_price is not None:
            return best_price, rr

    return None, None

#IFVG Detection and trade entry
pending_top = None
pending_bottom = None
pending_direction = None

entry_signal = []
entry_direction_list = []
sl_price_list = []
tp_price_list = []
rr_list = []

for i in range(len(merged)):
    merged_SetupDirection_here = merged['SetupDirection'].iloc[i]
    current_time = merged.index[i].time()  

    if pd.notna(merged_SetupDirection_here):
        pending_top = merged['SetupFVG_Top'].iloc[i]
        pending_bottom = merged['SetupFVG_Bottom'].iloc[i]
        pending_direction = merged_SetupDirection_here
        
    entry_triggered = False
    entry_direction = None
    sl_price = None
    tp_price = None
    rr = None

    if pending_direction == 'short' and current_time < pd.Timestamp('12:00').time():
        if merged['Close'].iloc[i] < pending_bottom:
            entry_triggered = True
            entry_direction = 'short'
            sl_price = pending_top + 0.8
            tp_price, rr = find_tp(entry_time=merged.index[i], entry_price=merged['Close'].iloc[i], sl_price=sl_price, direction='short' )
    elif pending_direction == 'long' and current_time < pd.Timestamp('12:00').time():
        if merged['Close'].iloc[i] > pending_top:
            entry_triggered = True
            entry_direction = 'long'
            sl_price = pending_bottom - 0.8
            tp_price, rr = find_tp(entry_time=merged.index[i], entry_price=merged['Close'].iloc[i], sl_price=sl_price, direction='long' )

    entry_signal.append(entry_triggered)
    entry_direction_list.append(entry_direction)
    sl_price_list.append(sl_price)
    tp_price_list.append(tp_price)
    rr_list.append(rr)

    if entry_triggered:
        pending_top = None
        pending_bottom = None
        pending_direction = None

    if current_time >= pd.Timestamp('12:00').time():
        pending_top = None
        pending_bottom = None
        pending_direction = None

merged['EntrySignal'] = entry_signal
merged['EntryDirection'] = entry_direction_list
merged['SLPrice'] = sl_price_list
merged['TPPrice'] = tp_price_list   
merged['RR'] = rr_list

def simulate_trade(entry_time, sl_price, tp_price, direction):
    future_candles = merged[merged.index > entry_time]
    last_valid_close = None

    for timestamp, row in future_candles.iterrows():
        if pd.notna(row['Close']):
            last_valid_close = row['Close']

        if direction == 'short':
            if row['High'] >= sl_price:
                return 'loss', sl_price, timestamp
            elif row['Low'] <= tp_price:
                return 'win', tp_price, timestamp

        elif direction == 'long':
            if row['Low'] <= sl_price:
                return 'loss', sl_price, timestamp
            elif row['High'] >= tp_price:
                return 'win', tp_price, timestamp

        current_time = timestamp.time()
        if current_time >= pd.Timestamp('16:30').time():
            return 'closed_eod', last_valid_close, timestamp

    return 'in trade', None, None

#Creating formula for R
def calculate_r(row):
    risk_distance = abs(row['EntryPrice'] - row['SLPrice'])

    if row['Direction'] == 'short':
        profit_points = row['EntryPrice'] - row['ExitPrice']
    elif row['Direction'] == 'long':
        profit_points = row['ExitPrice'] - row['EntryPrice']

    r = profit_points / risk_distance
    return r

#Creates a trade log
trade_log = []
trades = merged[merged['EntrySignal']]
trades = trades[trades['TPPrice'].notna()]

for timestamp, row in trades.iterrows():
    outcome, exit_price, exit_time = simulate_trade(entry_time=timestamp, sl_price=row['SLPrice'], tp_price=row['TPPrice'], direction=row['EntryDirection'])

    trade_log.append({
        'EntryTime': timestamp,
        'Direction': row['EntryDirection'],
        'EntryPrice': row['Close'],            
        'SLPrice': row['SLPrice'],
        'TPPrice': row['TPPrice'],
        'Outcome': outcome,
        'ExitPrice': exit_price,
        'ExitTime': exit_time
        })

trade_log_df = pd.DataFrame(trade_log)
trade_log_df['R'] = trade_log_df.apply(calculate_r, axis=1)

#Creates win rate
total_trades = len(trade_log_df)
total_wins = (trade_log_df['Outcome'] == 'win').sum()
win_rate = total_wins / total_trades

total_r = trade_log_df['R'].sum()
expectancy = trade_log_df['R'].mean()

#Creates equity curve
trade_log_df['CumulativeR'] = trade_log_df['R'].cumsum()

#Creates max drawdown
trade_log_df['RunningMax'] = trade_log_df['CumulativeR'].cummax()
trade_log_df['Drawdown'] = trade_log_df['CumulativeR'] - trade_log_df['RunningMax']
max_drawdown = trade_log_df['Drawdown'].min()




