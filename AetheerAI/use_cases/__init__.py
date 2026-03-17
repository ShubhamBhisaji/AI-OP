"""
use_cases — Pre-wired vertical workflows that make AetheerAI immediately useful.

Each use case is a concrete, named workflow: one command in, one deliverable out.
No agent-configuration knowledge required.

Registered packs
----------------
  content_factory   brand + product description → blog post, social posts, email, SEO file
  code_reviewer     file or folder path         → structured code-review report + fix suggestions
  market_intel      topic + competitors         → competitive-intelligence markdown brief

Usage (CLI)
-----------
  usecase list
  usecase run content_factory
  usecase run code_reviewer

Usage (API)
-----------
  GET  /api/usecases
  POST /api/usecases/content_factory/run   {"brand": ..., "product": ..., "audience": ...}
  POST /api/usecases/code_reviewer/run     {"path": "..."}
  POST /api/usecases/market_intel/run      {"topic": "...", "competitors": [...]}
"""

from use_cases.base import UseCaseRegistry
from use_cases.content_factory import ContentFactory
from use_cases.code_reviewer import CodeReviewer
from use_cases.market_intel import MarketIntel

registry = UseCaseRegistry()
registry.register(ContentFactory())
registry.register(CodeReviewer())
registry.register(MarketIntel())

__all__ = ["registry", "UseCaseRegistry", "ContentFactory", "CodeReviewer", "MarketIntel"]
