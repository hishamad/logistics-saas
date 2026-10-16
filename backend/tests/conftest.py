"""Tests never call OpenAI: a blank key (environment beats backend/.env) turns AI off.
Tests of the AI path patch in their own settings and a fake client."""

import os

from freight.settings import get_settings

os.environ["OPENAI_API_KEY"] = ""
get_settings.cache_clear()
