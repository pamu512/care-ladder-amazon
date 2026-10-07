"""Print the AgentCore judge transcript. Does not create a gateway."""

from __future__ import annotations

import sys

from care_ladder.cloud.agentcore_gateway import main

if __name__ == "__main__":
    sys.exit(main())
