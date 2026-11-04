"""Portal URLs, matching the port table in CLAUDE.md (#220).

The one place app code gets a portal link from. Each can be overridden by env
for a deployment where the portals don't live on localhost.
"""

import os

EXPLORATORY_PORTAL_URL = os.getenv("EXPLORATORY_PORTAL_URL", "http://localhost:8501")
FORMAL_PORTAL_URL = os.getenv("FORMAL_PORTAL_URL", "http://localhost:8502")
ADMIN_DASHBOARD_URL = os.getenv("ADMIN_DASHBOARD_URL", "http://localhost:8503")
