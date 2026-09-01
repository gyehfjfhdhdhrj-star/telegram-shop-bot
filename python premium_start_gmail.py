"""MLBB MARKET - Premium + Gmail OAuth launcher (v36 fixed).

Render start command:
    python premium_start_gmail.py

This launcher loads the v36 premium addon, including the admin payout
receipt handler, while keeping the existing supabase launcher and Gmail
integration.
"""
from __future__ import annotations

import importlib.util
import logging
from pathlib import Path

import gmail_bot_integration
import supabase_launcher


PREMIUM_FILE = "premium_features_v36_allmenus_discount_receipt_payout_fixed.py"
PREMIUM_MODULE = "premium_features_v36"


def load_module(filename: str, module_name: str):
    path = Path(__file__).with_name(filename)
    if not path.exists():
        raise RuntimeError(f"Required module not found: {path}")

    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load module: {path}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    premium = load_module(PREMIUM_FILE, PREMIUM_MODULE)
    premium.install(supabase_launcher.original)

    # Keep the existing Gmail integration.
    gmail_bot_integration.install(supabase_launcher.original)

    logging.info("PREMIUM_FEATURES_V36_READY")
    logging.info("PREMIUM_GMAIL_INTEGRATION_READY")

    supabase_launcher.start_original_bot()


if __name__ == "__main__":
    main()
