import csv
import os
from collections import defaultdict

def run_backtest(log_file="trade_log.csv"):
    
    if not os.path.exists(log_file):
        print("No log file found. Run live trading first.")
        return
    
    regime_stats = defaultdict(lambda: {"wins": 0, "losses": 0, "trades": 0})
    
    with open(log_file, 'r', newline='') as f:
        reader = csv.reader(f)
        next(reader)
        for row in reader:
            if len(row) < 12:
                continue
            regime = row[7]
            win_loss = row[11]
            
            if win_loss == "WIN":
                regime_stats[regime]["wins"] += 1
                regime_stats[regime]["trades"] += 1
            elif win_loss == "LOSS":
                regime_stats[regime]["losses"] += 1
                regime_stats[regime]["trades"] += 1
    
    print("\n" + "="*50)
    print("BACKTEST RESULTS")
    print("="*50)
    for regime, stats in regime_stats.items():
        trades = stats["trades"]
        if trades > 0:
            win_rate = stats["wins"] / trades * 100
            print(f"{regime:20s} | Trades: {trades:3d} | Wins: {stats['wins']:3d} | Losses: {stats['losses']:3d} | Win Rate: {win_rate:.1f}%")
    
    print("="*50)

if __name__ == "__main__":
    run_backtest()
