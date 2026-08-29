"""
MLBB MARKET - PREMIUM STARTER v10
--------------------------------
Runs the unchanged Supabase persistence launcher and separately loads
premium_features_v10.py.

Render Start Command:
    python premium_start_v10.py
"""

import importlib.util
from pathlib import Path
import logging
import supabase_launcher


def load_premium():
    path = Path(__file__).with_name("premium_features_v10.py")
    spec = importlib.util.spec_from_file_location("premium_features_v10", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Premium feature module not found: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    premium = load_premium()
    premium.install(supabase_launcher.original)
    logging.info("PREMIUM_FEATURES_V10_READY")
    supabase_launcher.start_original_bot()


if __name__ == "__main__":
    main()
