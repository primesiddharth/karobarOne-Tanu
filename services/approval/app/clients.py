# app/clients.py
# External & cross-service clients with stubs marked per RULES.md §13 & docs/STUBS.md
import structlog

logger = structlog.get_logger("approval.clients")
