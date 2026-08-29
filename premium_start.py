"""
MLBB MARKET - PREMIUM STARTER
------------------------------
Separate starter that loads:
    1) supabase_launcher.py  -> persistence
    2) premium_features.py   -> premium features

main.py remains untouched.
supabase_launcher.py remains a separate file.
"""

import importlib
import logging

import supabase_launcher
import premium_features


def main():
    premium_features.install(supabase_launcher.original)
    logging.info("PREMIUM_FEATURES_LOADED")
    supabase_launcher.start_original_bot()


if __name__ == "__main__":
    main()
