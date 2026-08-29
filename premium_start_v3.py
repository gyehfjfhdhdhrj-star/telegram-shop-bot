"""
MLBB MARKET - PREMIUM STARTER v3

Run this file on Render instead of changing main.py or supabase_launcher.py.

Render Start Command:
    python premium_start_v3.py

Load order:
    premium_start_v3.py
        -> supabase_launcher.py
            -> main.py
        -> premium_features_v3.py
        -> supabase_launcher.start_original_bot()
"""

import importlib.util
from pathlib import Path
import logging

import supabase_launcher


def load_premium_module():
    path = Path(__file__).with_name("premium_features_v3.py")
    spec = importlib.util.spec_from_file_location("premium_features_v3", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Premium feature module not found: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    premium = load_premium_module()
    premium.install(supabase_launcher.original)
    logging.info("PREMIUM_FEATURES_V3_READY")
    supabase_launcher.start_original_bot()


if __name__ == "__main__":
    main()
