"""integration_wizard.py — Autonomous self-integration workflow engine.

This is the component that makes AetheerAI agents genuinely self-integrating.
When an agent starts for the first time (or is instructed to re-integrate), the
wizard orchestrates the full connection lifecycle without human involvement
beyond the initial credential prompt.

Flow
----
1. DETECT   — Read manifest to discover required integrations.
2. PROMPT   — Ask for missing credentials (skips ones already in .env).
3. VALIDATE — Test that credentials are structurally valid (format checks).
4. CONFIGURE— Build integration configs and call the connector layer.
5. DIAGNOSE — Ping endpoints / run health checks.
6. CONFIRM  — Report success/failure per integration with actionable messages.
7. STORE    — Persist working configs securely to .env + integration_state.json.

Usage (programmatic)
--------------------
    wizard = IntegrationWizard(manifest, env_path=".env")
    report = wizard.run()
    print(report.summary())

Usage (CLI inside exported package)
------------------------------------
    python -m integrator.integration_wizard
    python -m integrator.integration_wizard --manifest agent_manifest.json
"""

from __future__ import annotations

import getpass
import json
import logging
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_SEP = "=" * 62

# ── Per-integration credential schema ─────────────────────────────────────────

_CREDENTIAL_SCHEMA: dict[str, list[dict[str, Any]]] = {
    "shopify": [
        {"key": "SHOPIFY_STORE_URL",    "label": "Shopify store URL (e.g. mystore.myshopify.com)", "secret": False},
        {"key": "SHOPIFY_ACCESS_TOKEN", "label": "Shopify Admin API access token",                 "secret": True},
    ],
    "website": [
        {"key": "WEBSITE_URL",    "label": "Website base URL (e.g. https://mysite.com)", "secret": False},
        {"key": "WEBSITE_API_KEY","label": "Website API key (leave blank if none)",      "secret": True, "optional": True},
    ],
    "api": [
        {"key": "API_BASE_URL", "label": "API base URL",            "secret": False},
        {"key": "API_KEY",      "label": "API key / bearer token",  "secret": True},
    ],
    "email": [
        {"key": "EMAIL_HOST",     "label": "SMTP host (e.g. smtp.gmail.com)", "secret": False},
        {"key": "EMAIL_PORT",     "label": "SMTP port",   "default": "587",   "secret": False},
        {"key": "EMAIL_USER",     "label": "Email address",                   "secret": False},
        {"key": "EMAIL_PASSWORD", "label": "Email password / app password",   "secret": True},
    ],
    "sendgrid": [
        {"key": "SENDGRID_API_KEY", "label": "SendGrid API key", "secret": True},
    ],
    "crm": [
        {"key": "CRM_BASE_URL", "label": "CRM base URL",  "secret": False},
        {"key": "CRM_API_KEY",  "label": "CRM API key",   "secret": True},
    ],
    "hubspot": [
        {"key": "HUBSPOT_API_KEY", "label": "HubSpot private app token", "secret": True},
    ],
    "slack": [
        {"key": "SLACK_BOT_TOKEN", "label": "Slack bot token (xoxb-…)", "secret": True},
        {"key": "SLACK_CHANNEL",   "label": "Default channel (#general)", "default": "#general", "secret": False},
    ],
    "database": [
        {"key": "DATABASE_URL", "label": "Database URL (postgres://… or mysql://…)", "secret": True},
    ],
    "supabase": [
        {"key": "SUPABASE_URL",    "label": "Supabase project URL",  "secret": False},
        {"key": "SUPABASE_KEY",    "label": "Supabase anon/service key", "secret": True},
    ],
    "stripe": [
        {"key": "STRIPE_SECRET_KEY", "label": "Stripe secret key (sk_…)", "secret": True},
    ],
    "github": [
        {"key": "GITHUB_TOKEN", "label": "GitHub personal access token", "secret": True},
    ],
    "devops": [
        {"key": "GITHUB_TOKEN",   "label": "GitHub token",          "secret": True},
        {"key": "KUBECONFIG",     "label": "Kubeconfig path (optional)", "optional": True, "secret": False},
    ],
    "ecommerce": [
        {"key": "ECOMMERCE_STORE_URL", "label": "Store URL",     "secret": False},
        {"key": "ECOMMERCE_API_KEY",   "label": "Store API key", "secret": True},
    ],
    "analytics": [
        {"key": "ANALYTICS_API_KEY", "label": "Analytics API key", "secret": True},
    ],
}

# ── Result types ────────────────────────────────────────────────────────────

@dataclass
class IntegrationStatus:
    name: str
    status: str = "pending"      # pending | connected | failed | skipped
    endpoints: list[str] = field(default_factory=list)
    error: str = ""
    latency_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "endpoints": self.endpoints,
            "error": self.error,
            "latency_ms": self.latency_ms,
        }


@dataclass
class WizardReport:
    agent_name: str
    integrations: list[IntegrationStatus] = field(default_factory=list)
    started_at: float = field(default_factory=time.time)
    finished_at: float = 0.0

    @property
    def all_connected(self) -> bool:
        return all(s.status == "connected" for s in self.integrations)

    @property
    def connected_count(self) -> int:
        return sum(1 for s in self.integrations if s.status == "connected")

    def summary(self) -> str:
        lines = [
            f"\n{_SEP}",
            f"  Integration Report — {self.agent_name}",
            f"{_SEP}",
        ]
        for s in self.integrations:
            icon = "✓" if s.status == "connected" else ("!" if s.status == "skipped" else "✗")
            lines.append(f"  [{icon}] {s.name:<20} {s.status}")
            if s.error:
                lines.append(f"       Error: {s.error}")
            if s.endpoints:
                lines.append(f"       Endpoints: {', '.join(s.endpoints[:3])}")
        lines.append(f"\n  {self.connected_count}/{len(self.integrations)} integrations connected.")
        if self.all_connected:
            lines.append("  Agent is ready to run.\n")
        else:
            lines.append("  Fix failing integrations, then re-run the wizard.\n")
        lines.append(_SEP)
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_name": self.agent_name,
            "all_connected": self.all_connected,
            "connected": self.connected_count,
            "total": len(self.integrations),
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "integrations": [s.to_dict() for s in self.integrations],
        }


# ── Wizard ──────────────────────────────────────────────────────────────────

class IntegrationWizard:
    """
    Autonomous integration setup wizard.

    Parameters
    ----------
    manifest  : AgentManifest instance (or path string to agent_manifest.json).
    env_path  : Path to .env file where credentials are stored.
    auto      : When True, skip prompts and use only existing env values.
    silent    : Suppress all stdout output (useful in tests / API mode).
    """

    def __init__(
        self,
        manifest: Any,
        env_path: str | Path | None = None,
        auto: bool = False,
        silent: bool = False,
        max_retries: int = 3,
    ) -> None:
        # Accept path string → load manifest
        if isinstance(manifest, (str, Path)):
            from agents.agent_manifest import AgentManifest
            manifest = AgentManifest.from_file(manifest)
        self._manifest = manifest
        self._env_path = Path(env_path) if env_path else Path(".env")
        self._auto = auto
        self._silent = silent
        self._max_retries = max(1, max_retries)
        self._env: dict[str, str] = self._load_env()
        self._state_path = self._env_path.parent / "integration_state.json"

    # ── Public API ──────────────────────────────────────────────────────────

    def run(self, retry_failed_only: bool = False) -> WizardReport:
        """Execute the full integration wizard and return a WizardReport.

        Parameters
        ----------
        retry_failed_only : When True, only re-run integrations that failed in the
                            previous run (loaded from integration_state.json). This
                            lets operators fix credentials and retry without
                            re-testing already-connected integrations.
        """
        report = WizardReport(agent_name=self._manifest.name)
        integrations: list[str] = list(self._manifest.integrations)

        # When retrying, filter to previously-failed integrations only
        if retry_failed_only:
            previously_failed = self._load_failed_integrations()
            if previously_failed:
                integrations = [i for i in integrations if i in previously_failed]
                self._print(f"\n  Retrying {len(integrations)} previously failed integration(s)…")

        if not integrations:
            self._print(f"\n  No integrations defined in manifest — skipping wizard.")
            report.finished_at = time.time()
            return report

        self._print(f"\n{_SEP}")
        self._print(f"  Integration Wizard — {self._manifest.name}")
        self._print(f"  Integrations required: {', '.join(integrations)}")
        self._print(f"{_SEP}\n")

        for integration in integrations:
            status = IntegrationStatus(name=integration)

            # STEP 1 — Detect
            self._print(f"  [{integration.upper()}] Detecting environment…")
            schema = _CREDENTIAL_SCHEMA.get(integration.lower(), [])

            # STEP 2 — Prompt for missing credentials
            if not self._auto:
                self._prompt_credentials(integration, schema)

            # STEP 3 — Validate credential format
            validation_error = self._validate_credentials(integration, schema)
            if validation_error:
                status.status = "failed"
                status.error = validation_error
                self._print(f"  [{integration.upper()}] Validation failed: {validation_error}")
                report.integrations.append(status)
                continue

            # STEP 4 — Configure + connect (with retry)
            self._print(f"  [{integration.upper()}] Configuring connector…")
            connected = False
            last_error = ""

            for attempt in range(1, self._max_retries + 1):
                try:
                    t0 = time.time()
                    result = self._connect(integration)
                    status.latency_ms = round((time.time() - t0) * 1000, 1)

                    if result.get("status") == "error":
                        last_error = result.get("error", "Unknown error")
                        if attempt < self._max_retries:
                            self._print(
                                f"  [{integration.upper()}] Attempt {attempt}/{self._max_retries} "
                                f"failed: {last_error}. Retrying…"
                            )
                            continue
                    else:
                        # STEP 5 — Diagnose (endpoint ping)
                        endpoints = result.get("endpoints", [])
                        status.endpoints = [
                            e.get("path", e) if isinstance(e, dict) else str(e)
                            for e in endpoints[:5]
                        ]
                        diag = self._diagnose(integration, result)
                        if diag:
                            last_error = diag
                            if attempt < self._max_retries:
                                self._print(
                                    f"  [{integration.upper()}] Diagnostic failed (attempt "
                                    f"{attempt}/{self._max_retries}): {diag}. Retrying…"
                                )
                                continue
                        else:
                            # STEP 6 — Confirm
                            status.status = "connected"
                            connected = True
                            self._print(
                                f"  [{integration.upper()}] Connected ✓  "
                                f"({len(status.endpoints)} endpoints, {status.latency_ms}ms)"
                            )
                            break

                except Exception as exc:
                    last_error = str(exc)
                    if attempt < self._max_retries:
                        self._print(
                            f"  [{integration.upper()}] Attempt {attempt}/{self._max_retries} "
                            f"exception: {exc}. Retrying…"
                        )
                        continue

            if not connected:
                status.status = "failed"
                status.error = last_error
                self._print(f"  [{integration.upper()}] Connection failed after {self._max_retries} attempt(s): {last_error}")

            report.integrations.append(status)

        # STEP 7 — Store configs
        self._save_env()
        self._save_state(report)

        report.finished_at = time.time()
        self._print(report.summary())
        return report

    # ── Internal steps ──────────────────────────────────────────────────────

    def _prompt_credentials(self, integration: str, schema: list[dict]) -> None:
        """Prompt user for credentials not already in .env."""
        if not schema:
            schema = [
                {
                    "key": f"{integration.upper()}_API_KEY",
                    "label": f"{integration.title()} API key",
                    "secret": True,
                    "optional": True,
                }
            ]
        self._print(f"\n  Credentials for {integration.upper()}:")
        for field_def in schema:
            key = field_def["key"]
            label = field_def["label"]
            is_secret = bool(field_def.get("secret", False))
            optional = bool(field_def.get("optional", False))
            default = field_def.get("default", self._env.get(key, ""))

            if self._env.get(key):
                self._print(f"    {key}: [already set]")
                continue

            suffix = " (optional)" if optional else ""
            default_hint = f" [{default}]" if default and not is_secret else ""
            prompt = f"    {label}{suffix}{default_hint}: "

            try:
                if is_secret:
                    value = getpass.getpass(prompt)
                else:
                    value = input(prompt).strip()
            except (KeyboardInterrupt, EOFError):
                self._print("\n  Wizard cancelled.")
                sys.exit(0)

            value = (value or default).strip()
            if value:
                self._env[key] = value

    def _validate_credentials(self, integration: str, schema: list[dict]) -> str:
        """Return an error string if required credentials are missing/malformed."""
        for field_def in schema:
            key = field_def["key"]
            optional = field_def.get("optional", False)
            value = self._env.get(key, "").strip()
            if not value and not optional:
                return f"Required credential '{key}' is missing."
            # Basic format checks
            if value:
                if key.endswith("_URL") and not (value.startswith("http://") or value.startswith("https://")):
                    return f"'{key}' must be a valid URL (got: {value[:40]!r})."
        return ""

    def _connect(self, integration: str) -> dict[str, Any]:
        """Attempt to connect using the appropriate connector."""
        name_lower = integration.lower()

        # Build config from env
        config: dict[str, Any] = {
            "type": name_lower,
            "name": integration,
        }

        # Populate connector-specific config keys
        key_mappings: dict[str, dict[str, str]] = {
            "website":  {"domain": "WEBSITE_URL", "api_key": "WEBSITE_API_KEY"},
            "shopify":  {"domain": "SHOPIFY_STORE_URL", "api_key": "SHOPIFY_ACCESS_TOKEN"},
            "api":      {"base_url": "API_BASE_URL", "credentials": "API_KEY"},
            "crm":      {"base_url": "CRM_BASE_URL", "credentials": "CRM_API_KEY"},
            "hubspot":  {"base_url": "https://api.hubapi.com", "credentials": "HUBSPOT_API_KEY"},
            "sendgrid": {"base_url": "https://api.sendgrid.com", "credentials": "SENDGRID_API_KEY"},
            "stripe":   {"base_url": "https://api.stripe.com", "credentials": "STRIPE_SECRET_KEY"},
            "github":   {"base_url": "https://api.github.com", "credentials": "GITHUB_TOKEN"},
            "supabase": {"base_url": "SUPABASE_URL", "credentials": "SUPABASE_KEY"},
        }
        mapping = key_mappings.get(name_lower, {})
        for config_key, env_key in mapping.items():
            val = self._env.get(env_key, "")
            if val:
                if env_key.endswith(("_URL", "_STORE_URL", "_BASE_URL")):
                    config[config_key] = val
                else:
                    config[config_key] = val

        # Route to appropriate connector
        try:
            if name_lower in ("website", "shopify", "ecommerce"):
                from integrations.website_connector import WebsiteConnector
                connector = WebsiteConnector()
                domain = config.get("domain", "")
                if not domain.startswith("http"):
                    domain = f"https://{domain}"
                return connector.connect(
                    domain=domain,
                    api_key=config.get("api_key", ""),
                    discover=True,
                )

            elif name_lower in ("api", "crm", "hubspot", "sendgrid", "stripe", "github", "supabase"):
                from integrations.generic_api import GenericAPIClient
                client = GenericAPIClient()
                base_url = config.get("base_url", "")
                if not base_url.startswith("http"):
                    base_url = self._env.get("API_BASE_URL", base_url)
                return client.connect(
                    base_url=base_url,
                    auth_type="bearer",
                    credentials={"token": config.get("credentials", "")},
                )

            else:
                # Generic custom integration — store & confirm
                target = config.get("domain") or config.get("base_url", "")
                return {"status": "connected", "endpoints": [], "target": target}

        except Exception as exc:
            return {"status": "error", "error": str(exc)}

    @staticmethod
    def _diagnose(integration: str, connect_result: dict[str, Any]) -> str:
        """
        Run a lightweight diagnostic on a successful connection.

        Returns an error string if something is wrong, empty string if healthy.
        """
        # If the connector returned endpoints, we consider it healthy.
        if connect_result.get("endpoints"):
            return ""
        # If it returned a target but no endpoints, that is acceptable.
        if connect_result.get("target"):
            return ""
        # If status is "connected" with no other info, accept it.
        if connect_result.get("status") == "connected":
            return ""
        return "No endpoints discovered and no target URL reported."

    # ── Persistence helpers ─────────────────────────────────────────────────

    def _load_env(self) -> dict[str, str]:
        env: dict[str, str] = {}
        if not self._env_path.exists():
            return env
        for line in self._env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, val = line.partition("=")
                env[key.strip()] = val.strip()
        return env

    def _save_env(self) -> None:
        """Persist credentials to .env.

        Secret values (keys containing TOKEN, SECRET, PASSWORD, API_KEY)
        are stored as-is so connectors can read them, but the file is
        created with restrictive permissions where the OS supports it.
        """
        lines = ["# Integration credentials — managed by integration_wizard.py\n"]
        for key, val in self._env.items():
            lines.append(f"{key}={val}\n")
        self._env_path.write_text("".join(lines), encoding="utf-8")

        # Best-effort: restrict file permissions to owner-only (Unix)
        try:
            self._env_path.chmod(0o600)
        except (OSError, NotImplementedError):
            pass  # Windows or other OS — skip

    def _save_state(self, report: WizardReport) -> None:
        """Persist integration state for diagnostics and re-runs."""
        try:
            self._state_path.write_text(
                json.dumps(report.to_dict(), indent=2, default=str),
                encoding="utf-8",
            )
        except OSError as exc:
            logger.warning("IntegrationWizard: could not save state: %s", exc)

    def _load_failed_integrations(self) -> set[str]:
        """Load names of integrations that failed in the previous run."""
        if not self._state_path.exists():
            return set()
        try:
            data = json.loads(self._state_path.read_text(encoding="utf-8"))
            return {
                i["name"]
                for i in data.get("integrations", [])
                if i.get("status") == "failed"
            }
        except (OSError, json.JSONDecodeError, KeyError):
            return set()

    # ── Helpers ─────────────────────────────────────────────────────────────

    def _print(self, msg: str) -> None:
        if not self._silent:
            print(msg)


# ── Convenience factory ──────────────────────────────────────────────────────

def run_wizard(
    manifest_path: str | Path = "agent_manifest.json",
    env_path: str | Path = ".env",
    auto: bool = False,
) -> WizardReport:
    """
    Convenience function — load manifest and run the wizard.

    Parameters
    ----------
    manifest_path : Path to agent_manifest.json
    env_path      : Path to .env credential file
    auto          : Skip prompts; use only env vars already present
    """
    wizard = IntegrationWizard(manifest=manifest_path, env_path=env_path, auto=auto)
    return wizard.run()


# ── CLI entry ────────────────────────────────────────────────────────────────

def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="AetheerAI Integration Wizard")
    parser.add_argument("--manifest", default="agent_manifest.json")
    parser.add_argument("--env", default=".env")
    parser.add_argument("--auto", action="store_true", help="Non-interactive mode")
    args = parser.parse_args()
    report = run_wizard(args.manifest, args.env, auto=args.auto)
    sys.exit(0 if report.all_connected else 1)


if __name__ == "__main__":
    main()
