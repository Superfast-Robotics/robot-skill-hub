"""Deployment helper. Uses existing Git Credential Manager / Wrangler login.

Never prints credentials. Mutations are explicit subcommands.
"""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import urllib.error
import urllib.request

REPO = "Superfast-Robotics/robot-skill-hub"
ACCOUNT = "8df378989a27166c1180b588582573df"


def github_token():
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if token:
        return token
    proc = subprocess.run(["git", "credential", "fill"],
        input="protocol=https\nhost=github.com\n\n", text=True,
        capture_output=True, env={**os.environ, "GIT_TERMINAL_PROMPT": "0", "GCM_INTERACTIVE": "Never"})
    values = dict(line.split("=", 1) for line in proc.stdout.splitlines() if "=" in line)
    if not values.get("password"):
        raise RuntimeError("Sign in to GitHub using Git Credential Manager first.")
    return values["password"]


def cloudflare_token():
    token = os.environ.get("CLOUDFLARE_API_TOKEN")
    if token:
        return token
    config = Path(os.environ["APPDATA"]) / "xdg.config/.wrangler/config/default.toml"
    match = re.search(r'^oauth_token\s*=\s*"([^"]+)"', config.read_text(), re.M)
    if not match:
        raise RuntimeError("Run npx wrangler login first.")
    return match[1]


def request(service, path, method="GET", data=None):
    base, token = (("https://api.github.com/", github_token()) if service == "github"
                   else ("https://api.cloudflare.com/client/v4/", cloudflare_token()))
    headers = {"Authorization": "Bearer " + token, "Accept": "application/json", "User-Agent": "robot-skill-hub-deployment"}
    if service == "github":
        headers["X-GitHub-Api-Version"] = "2022-11-28"
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(base + path, method=method, headers=headers,
        data=json.dumps(data).encode() if data is not None else None)
    try:
        with urllib.request.urlopen(req, timeout=40) as response:
            body = response.read()
            return json.loads(body) if body else {"ok": True}
    except urllib.error.HTTPError as error:
        body = json.loads(error.read())
        # API errors contain no request headers or tokens.
        return {"http_status": error.code, "message": body.get("message"), "errors": body.get("errors")}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("service", choices=["github", "cloudflare"])
    parser.add_argument("path")
    parser.add_argument("--method", default="GET", choices=["GET", "POST", "PUT", "PATCH", "DELETE"])
    parser.add_argument("--body-file", type=Path)
    args = parser.parse_args()
    data = json.loads(args.body_file.read_text(encoding="utf-8-sig")) if args.body_file else None
    result = request(args.service, args.path, args.method, data)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result.get("http_status") else 0


if __name__ == "__main__":
    sys.exit(main())
