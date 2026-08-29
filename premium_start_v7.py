"""
MLBB MARKET - PREMIUM STARTER v7
--------------------------------
Loads unchanged supabase_launcher.py and separate premium_features_v7.py.

Render Start Command:
    python premium_start_v7.py
"""

import importlib.util
from pathlib import Path
import logging
import supabase_launcher

def load_premium():
    path = Path(__file__).with_name("premium_features_v7.py")
    spec = importlib.util.spec_from_file_location("premium_features_v7", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Premium feature module not found: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

def main():
    premium = load_premium()
    premium.install(supabase_launcher.original)
    logging.info("PREMIUM_FEATURES_V7_READY")
    supabase_launcher.start_original_bot()

if __name__ == "__main__":
    main()
