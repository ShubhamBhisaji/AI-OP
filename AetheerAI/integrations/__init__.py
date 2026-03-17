"""
AetheerAI Integrations Package
==============================
Modular, drop-in connectors for external services:

  - Supabase       : PostgreSQL database, auth, and realtime
  - Infobip        : WhatsApp and Email messaging
  - PayU Money     : Payment processing and transaction verification
  - Meta Graph API : Facebook Pages, Instagram, and Messenger
  - Vercel         : Serverless hosting and deployment management

All connectors read credentials from environment variables
(or from the project .env file loaded at startup).
"""

from .supabase_client import SupabaseClient
from .infobip_client import InfobipClient
from .payu_client import PayUClient
from .meta_api_client import MetaAPIClient
from .vercel_client import VercelClient
from .service_factory import IntegrationFactory, IntegrationClients
from .errors import (
    IntegrationError,
    ConfigurationError,
    AuthenticationError,
    APIRequestError,
)

__all__ = [
    "SupabaseClient",
    "InfobipClient",
    "PayUClient",
    "MetaAPIClient",
    "VercelClient",
    "IntegrationFactory",
    "IntegrationClients",
    "IntegrationError",
    "ConfigurationError",
    "AuthenticationError",
    "APIRequestError",
]
