"""ADK entry point.

`adk web` / `adk run` discover the app by importing this package and reading `root_agent`. The
package name equals `config.APP_NAME` so the dev UI lists the served sessions.

Construction is import-safe: building the graph opens no connection, because the instruction
provider reads the catalog lazily, per turn.
"""

from __future__ import annotations

from aziza_adk.agents.sales import sales_agent

root_agent = sales_agent
