"""Google OAuth2 credentials; shared by Gmail and Calendar."""

import asyncio
import os
import threading
from urllib.parse import parse_qs, urlparse

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from google.auth.transport.requests import Request as AuthRequest
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
import uvicorn

# How long to wait for the redirect callback before suggesting paste flow (e.g. dev container)
AUTH_CALLBACK_TIMEOUT_SEC = 120

SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/calendar",
]


def get_credentials() -> Credentials:
    """Load or refresh credentials; run local server if no valid token."""
    tokens_path = os.path.expanduser(
        os.getenv("DOOT_TOKENS_PATH", "~/.doot/tokens.json")
    )
    creds = None

    if os.path.exists(tokens_path):
        creds = Credentials.from_authorized_user_file(tokens_path, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(AuthRequest())
        else:
            auth_port = int(os.getenv("DOOT_AUTH_PORT", "8080"))
            redirect_uri = (os.getenv("GOOGLE_REDIRECT_URI") or f"http://localhost:{auth_port}").rstrip("/")
            flow = InstalledAppFlow.from_client_config(
                {
                    "installed": {
                        "client_id": os.getenv("GOOGLE_CLIENT_ID"),
                        "client_secret": os.getenv("GOOGLE_CLIENT_SECRET"),
                        "redirect_uris": [redirect_uri, "http://localhost", f"http://localhost:{auth_port}"],
                        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                        "token_uri": "https://oauth2.googleapis.com/token",
                    }
                },
                SCOPES,
                redirect_uri=redirect_uri,
            )

            use_paste = os.getenv("DOOT_AUTH_PASTE_URL", "").strip().lower() in ("1", "true", "yes")
            if use_paste:
                creds = _auth_via_paste_url(flow, redirect_uri)
            else:
                print(
                    "\nListening for redirect at",
                    redirect_uri,
                    "(bound to 0.0.0.0 so port forwarding works).",
                )
                print(
                    "If you're in a dev container / Codespaces, the browser redirect won't reach this app."
                )
                print(
                    "Either forward port",
                    auth_port,
                    "from host to container, or set DOOT_AUTH_PASTE_URL=1 and paste the redirect URL.\n",
                )
                creds = _run_local_server_bind_all(flow, redirect_uri, auth_port)

        os.makedirs(os.path.dirname(tokens_path), exist_ok=True)
        with open(tokens_path, "w") as f:
            f.write(creds.to_json())

    return creds


def _run_local_server_bind_all(
    flow: InstalledAppFlow, redirect_uri: str, port: int
) -> Credentials:
    """Run a FastAPI callback server on 0.0.0.0 so port forwarding from host reaches it."""
    app = FastAPI()
    app.state.flow = flow
    app.state.redirect_uri = redirect_uri
    app.state.result = []
    app.state.server = None

    @app.get("/", response_class=HTMLResponse)
    def callback(request: Request, code: str | None = None):
        if code:
            flow = request.app.state.flow
            flow.fetch_token(code=code)
            request.app.state.result.append(flow.credentials)
        html = "<html><body><p>Auth complete. You can close this tab.</p></body></html>"
        if request.app.state.server:
            request.app.state.server.should_exit = True
        return HTMLResponse(html)

    config = uvicorn.Config(
        app,
        host="0.0.0.0",
        port=port,
        log_level="warning",
        access_log=False,
        lifespan="off",
    )
    server = uvicorn.Server(config)
    server.force_exit = True
    app.state.server = server

    auth_url, _ = flow.authorization_url(prompt="consent")
    print("Please visit this URL to authorize this application:", auth_url, flush=True)

    def run_server():
        asyncio.run(server.serve())

    thread = threading.Thread(target=run_server, daemon=True)
    thread.start()
    thread.join(timeout=AUTH_CALLBACK_TIMEOUT_SEC + 10)

    if not app.state.result:
        raise SystemExit(
            "No callback received in time. If you're in a dev container, the redirect goes to your host, not here.\n"
            "Run again with DOOT_AUTH_PASTE_URL=1 and paste the full redirect URL when prompted."
        )
    return app.state.result[0]


def _auth_via_paste_url(flow: InstalledAppFlow, redirect_uri: str) -> Credentials:
    """Run OAuth by having the user open the URL, then paste the redirect URL back."""
    auth_url, _ = flow.authorization_url(prompt="consent")
    print("\n1. Open this URL in your browser (e.g. on your host machine):\n")
    print(auth_url)
    print("\n2. Sign in and click Continue.")
    print("3. You will be redirected to a page that cannot load (e.g. 'This site can't be reached').")
    print("4. Copy the *entire URL* from your browser's address bar and paste it below.\n")
    redirect_response = input("Paste the redirect URL here: ").strip()
    if not redirect_response:
        raise SystemExit("No URL pasted. Exiting.")
    # Parse code from redirect URL (e.g. http://localhost/?code=XXX&scope=...)
    parsed = urlparse(redirect_response)
    params = parse_qs(parsed.query)
    code = params.get("code")
    if not code:
        raise SystemExit("Could not find 'code' in the URL. Make sure you pasted the full URL.")
    flow.fetch_token(code=code[0], redirect_uri=redirect_uri)
    return flow.credentials
