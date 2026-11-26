# Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU Affero General Public License as published by the Free Software Foundation, version 3 of
# the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
"""View-only page for invited friends: a separate app on 127.0.0.1:8081.

Only the routes in app.viewer.app exist there, so nothing a tunnel forwards can reach
settings, the node, verdicts or sound.
"""
