"""
Example usage for external service integrations.

Run from AetheerAI/:
    python examples/external_services_demo.py

Set RUN_LIVE_EXAMPLES=1 to execute live API calls.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.env_loader import load_env

load_env(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

from integrations import (
    IntegrationFactory,
    SupabaseClient,
    InfobipClient,
    PayUClient,
    MetaAPIClient,
    VercelClient,
)
from integrations.errors import IntegrationError


def demo_supabase(live_mode: bool) -> None:
    print("\n[Supabase]")
    if not live_mode:
        print("  Sample: client = SupabaseClient()")
        print("  Sample: session = client.sign_in_with_password(email='user@example.com', password='secret')")
        print("  Sample: rows = client.query_rows(table='profiles', limit=5, use_service_role=True)")
        print("  Sample: client.insert_row(table='orders', payload={'user_id': 1, 'total': 99.9})")
        print("  Sample: sub = client.build_realtime_subscription(table='orders')")
        print(f"  Sample realtime URL: wss://<project>.supabase.co/realtime/v1/websocket?apikey=<key>")
        return

    client = SupabaseClient()
    demo_table = os.getenv("SUPABASE_DEMO_TABLE", "")
    if demo_table:
        rows = client.query_rows(table=demo_table, limit=5, use_service_role=True)
        print(f"  Fetched rows from {demo_table}: {rows}")
    else:
        print("  Set SUPABASE_DEMO_TABLE to run a live query test")

    realtime_cfg = client.build_realtime_subscription(table=demo_table or "profiles")
    print(f"  Realtime websocket URL: {realtime_cfg['websocket_url']}")


def demo_infobip(live_mode: bool) -> None:
    print("\n[Infobip]")
    if not live_mode:
        print("  Sample: client = InfobipClient()")
        print("  Sample: client.send_whatsapp_text(to_number='+15551234567', text='Hello from AetheerAI')")
        print("  Sample: client.send_email(to_email='ops@company.com', subject='Alert', text_body='Build done')")
        print("  Sample: client.send_notification(channel='email', destination='ops@co.com', message='Done')")
        return

    client = InfobipClient()
    destination = os.getenv("INFOBIP_DEMO_EMAIL_TO", "")
    if destination:
        response = client.send_email(
            to_email=destination,
            subject="AetheerAI Integration Test",
            text_body="Infobip email integration is active.",
        )
        print(f"  Email send response: {response}")
    else:
        print("  Set INFOBIP_DEMO_EMAIL_TO to run a live email test")


def demo_payu() -> None:
    print("\n[PayU]")
    # PayU checkout payload generation is pure math (no network call needed).
    # This runs in dry-run too, but only if PAYU_MERCHANT_KEY / SALT are set.
    # Show sample code when env vars are absent.
    import os as _os
    if not (_os.environ.get("PAYU_MERCHANT_KEY") and _os.environ.get("PAYU_MERCHANT_SALT")):
        print("  Sample: client = PayUClient()")
        print("  Sample: checkout = client.build_checkout_payload(")
        print("              amount=499.00, product_info='AetheerAI Pro Plan',")
        print("              first_name='Alex', email='alex@example.com')")
        print("  Sample: redirect user browser to checkout['checkout_url'] with checkout['form_fields']")
        print("  Sample: txn = client.verify_transaction(transaction_id='TXN...')")
        print("  Sample: link = client.create_payment_link(amount=299.0, product_info='Starter', ...)")
        return

    client = PayUClient()
    checkout = client.build_checkout_payload(
        amount=499.00,
        product_info="AetheerAI Pro Plan",
        first_name="Alex",
        email="alex@example.com",
    )
    print(f"  Checkout URL: {checkout['checkout_url']}")
    print(f"  Transaction ID: {checkout['transaction_id']}")
    print("  Form fields prepared for frontend POST to PayU checkout endpoint")


def demo_meta(live_mode: bool) -> None:
    print("\n[Meta Graph API]")
    if not live_mode:
        print("  Sample: client = MetaAPIClient()")
        print("  Sample: pages = client.get_managed_pages()")
        print("  Sample: client.publish_page_post(message='New launch update!')")
        print("  Sample: client.publish_instagram_image(image_url='https://.../hero.jpg', caption='Launch day')")
        print("  Sample: client.send_messenger_text(recipient_id='PSID', text='Thanks for reaching out')")
        print("  Sample: insights = client.get_page_insights(metrics=['page_impressions'], period='day')")
        return

    client = MetaAPIClient()
    pages = client.get_managed_pages()
    print(f"  Managed pages: {pages}")


def demo_vercel(live_mode: bool) -> None:
    print("\n[Vercel]")
    if not live_mode:
        print("  Sample: client = VercelClient()")
        print("  Sample: client.create_project(name='aetheer-web', framework='nextjs')")
        print("  Sample: client.create_git_deployment(name='aetheer-web', repo='org/repo', branch='main')")
        print("  Sample: deployments = client.list_deployments(limit=5)"  )
        print("  Sample: client.upsert_project_env_var(project_id='prj_xxx', key='API_URL', value='https://...')")
        return

    client = VercelClient()
    projects = client.list_projects(limit=5)
    print(f"  Projects: {projects}")


def main() -> None:
    print("AetheerAI External Service Integrations Demo")
    print("-" * 48)

    live_mode = os.getenv("RUN_LIVE_EXAMPLES", "0").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    print(f"Live mode: {live_mode}")

    # Modular wiring example (replace any client with a mock/alternate provider).
    # IntegrationFactory eagerly validates all env vars — only works when .env is
    # fully populated.  We show sample output when running without credentials.
    try:
        clients = IntegrationFactory().create()
        print(
            "Factory clients loaded:",
            type(clients.supabase).__name__,
            type(clients.infobip).__name__,
            type(clients.payu).__name__,
            type(clients.meta).__name__,
            type(clients.vercel).__name__,
        )
    except IntegrationError as exc:
        print(f"[Factory] Skipped (env vars not configured): {exc}")

    try:
        demo_supabase(live_mode)
    except IntegrationError as exc:
        print(f"  [skipped — env vars not configured] {exc}")

    try:
        demo_infobip(live_mode)
    except IntegrationError as exc:
        print(f"  [skipped — env vars not configured] {exc}")

    try:
        demo_payu()
    except IntegrationError as exc:
        print(f"  [skipped — env vars not configured] {exc}")

    try:
        demo_meta(live_mode)
    except IntegrationError as exc:
        print(f"  [skipped — env vars not configured] {exc}")

    try:
        demo_vercel(live_mode)
    except IntegrationError as exc:
        print(f"  [skipped — env vars not configured] {exc}")


if __name__ == "__main__":
    main()
