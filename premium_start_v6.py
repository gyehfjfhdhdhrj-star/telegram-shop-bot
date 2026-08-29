"""
MLBB MARKET - PREMIUM STARTER v6
---------------------------------
Separate runner:
- main.py is NOT modified.
- supabase_launcher.py is NOT modified on disk.
- premium_features_v6.py is loaded as a separate addon.

Render Start Command:
    python premium_start_v6.py
"""

import importlib.util
from pathlib import Path
import logging

import supabase_launcher


def load_module():
    path = Path(__file__).with_name("premium_features_v6.py")
    spec = importlib.util.spec_from_file_location("premium_features_v6", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Premium feature module not found: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    premium = load_module()
    premium.install(supabase_launcher.original)
    logging.info("PREMIUM_FEATURES_V6_READY")
    supabase_launcher.start_original_bot()


if __name__ == "__main__":
    main()
