import csv
import os
from datetime import datetime

LOG_FILE = "trade_log.csv"

def init_logger():
    if not os.path.exists(LOG_FILE):
        with open(LOG_FILE, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([
                "timestamp", "market_slug", "distance", "obi", "cme_delta",
                "velocity", "rsi_1h", "regime", "trade_direction", "executed",
                "actual_resolution", "win_loss", "notes"
            ])

def log_decision(timestamp, market_slug, distance, obi, cme_delta, velocity, 
                 rsi_1h, regime, trade_direction, executed, notes=""):
    with open(LOG_FILE, 'a', newline='') as f:
        writer = csv.writer(f)
        writer.writerow([
            timestamp, market_slug, distance, obi, cme_delta,
            velocity, rsi_1h, regime, trade_direction, executed,
            "", "", notes
        ])
    print(f"Logged: {regime} | {trade_direction} | Executed: {executed}")

def update_resolution(market_slug, actual_resolution, won):
    rows = []
    updated = False
    
    with open(LOG_FILE, 'r', newline='') as f:
        reader = csv.reader(f)
        headers = next(reader)
        for row in reader:
            if len(row) > 1 and row[1] == market_slug and not row[10]:
                row[10] = actual_resolution
                row[11] = "WIN" if won else "LOSS"
                updated = True
            rows.append(row)
    
    with open(LOG_FILE, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        writer.writerows(rows)
    
    if updated:
        print(f"Updated {market_slug}: {actual_resolution} - {'WIN' if won else 'LOSS'}")
