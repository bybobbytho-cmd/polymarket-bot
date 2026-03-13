#!/usr/bin/env python3
"""
Main entry point for Polymarket bot on Railway.
This simply runs the config.py test function.
"""

from config import test_bot

if __name__ == "__main__":
    print("🚀 Starting Polymarket Bot...")
    test_bot()
