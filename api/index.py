"""Vercel serverless function entry point."""

import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from app import app

# Vercel expects the app to be named 'app' or 'application'
application = app
