"""MLBB MARKET - Premium + Gmail OAuth starter.
Render Start Command: python premium_start_gmail.py
"""
from __future__ import annotations
import importlib.util, logging
from pathlib import Path
import gmail_bot_integration
import supabase_launcher


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
    premium = load_module("premium_features_v17.py", "premium_features_v17")
    premium.install(supabase_launcher.original)
    gmail_bot_integration.install(supabase_launcher.original)
    logging.info("PREMIUM_GMAIL_INTEGRATION_READY")
    supabase_launcher.start_original_bot()


if __name__ == "__main__":
    main()
