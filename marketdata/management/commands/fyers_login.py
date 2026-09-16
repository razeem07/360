"""
Interactive helper to obtain a Fyers access token. Run this locally
whenever FYERS_ACCESS_TOKEN expires (roughly once a trading day) and paste
the resulting token into .env — this command never stores it for you, so
secrets stay out of source control (CLAUDE.md rule 8).
"""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from fyers_apiv3 import fyersModel


class Command(BaseCommand):
    help = "Walk through the Fyers OAuth flow and print an access token to place in .env."

    def add_arguments(self, parser):
        parser.add_argument(
            "--code",
            help=(
                "Skip the interactive prompt and exchange this auth_code directly "
                "(useful when driving this command from a non-interactive shell)."
            ),
        )

    def handle(self, *args, **options):
        if not (settings.FYERS_CLIENT_ID and settings.FYERS_SECRET_KEY and settings.FYERS_REDIRECT_URI):
            raise CommandError(
                "FYERS_CLIENT_ID, FYERS_SECRET_KEY, and FYERS_REDIRECT_URI must be set in .env first."
            )

        session = fyersModel.SessionModel(
            client_id=settings.FYERS_CLIENT_ID,
            secret_key=settings.FYERS_SECRET_KEY,
            redirect_uri=settings.FYERS_REDIRECT_URI,
            response_type="code",
            grant_type="authorization_code",
        )

        auth_url = session.generate_authcode()
        self.stdout.write("1. Open this URL, log in, and approve access:")
        self.stdout.write(f"   {auth_url}")
        self.stdout.write(
            "2. You'll be redirected to your FYERS_REDIRECT_URI with an "
            "'auth_code' query parameter — copy just that value."
        )

        auth_code = options.get("code")
        if not auth_code:
            auth_code = input("Paste auth_code here: ").strip()
        if not auth_code:
            raise CommandError("No auth_code provided.")

        session.set_token(auth_code)
        response = session.generate_token()

        access_token = response.get("access_token")
        if not access_token:
            raise CommandError(f"Fyers did not return an access token: {response}")

        self.stdout.write(self.style.SUCCESS("\nAccess token obtained. Put this in .env:"))
        self.stdout.write(f"FYERS_ACCESS_TOKEN={access_token}")
