"""security_tool — Website security header and TLS configuration checker."""
from __future__ import annotations
import json, ssl, socket, logging
import urllib.request, urllib.error
from urllib.parse import urlparse
import ipaddress

logger = logging.getLogger(__name__)

_TIMEOUT = 10

# Security headers and what each one does
_SECURITY_HEADERS = {
    "strict-transport-security":       ("HSTS",          "Enforces HTTPS connections"),
    "content-security-policy":         ("CSP",           "Controls resource loading origins"),
    "x-frame-options":                 ("Clickjacking",  "Prevents iframe embedding"),
    "x-content-type-options":          ("MIME sniff",    "Stops MIME-type sniffing"),
    "referrer-policy":                 ("Referrer",      "Controls referrer header leakage"),
    "permissions-policy":              ("Permissions",   "Restricts browser feature access"),
    "x-xss-protection":                ("XSS filter",    "Legacy browser XSS filter"),
    "cross-origin-opener-policy":      ("COOP",          "Isolates browsing context"),
    "cross-origin-embedder-policy":    ("COEP",          "Controls cross-origin embedding"),
    "cross-origin-resource-policy":    ("CORP",          "Controls cross-origin resource reads"),
    "cache-control":                   ("Cache",         "Controls caching behaviour"),
    "x-permitted-cross-domain-policies": ("Flash/PDF",   "Cross-domain policy for Flash/PDF"),
}

_PRIVATE_NETS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
]


def security_tool(url: str, action: str = "scan") -> str:
    """
    Check the security posture of a public website.

    url    : Full URL of the target (https://example.com or http://...).
    action : scan | headers | tls | redirects | cookies | info

    Actions:
        scan      : Full security report (headers + TLS + cookies + redirects).
        headers   : Audit HTTP security response headers (present/missing/value).
        tls       : TLS/SSL certificate details and cipher info.
        redirects : Follow the redirect chain and flag HTTP→HTTPS upgrades.
        cookies   : Inspect Set-Cookie flags (Secure, HttpOnly, SameSite).
        info      : Basic server info (Server, X-Powered-By, tech hints).
    """
    if not url or not isinstance(url, str):
        return "Error: 'url' must be a non-empty string."

    url = url.strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    parsed = urlparse(url)
    action = (action or "scan").strip().lower()

    # ── SSRF guard — block private/internal addresses ─────────────────
    host = parsed.hostname or ""
    if host.lower() in ("localhost", "host.docker.internal"):
        return "Error: Scanning internal/loopback addresses is not allowed."
    try:
        resolved = socket.gethostbyname(host)
        ip = ipaddress.ip_address(resolved)
        if any(ip in net for net in _PRIVATE_NETS):
            return f"Error: Resolved IP {resolved} is a private address — scanning not allowed."
    except socket.gaierror:
        return f"Error: Could not resolve hostname '{host}'."
    except ValueError:
        pass  # IPv6 edge-case — proceed

    # ── Fetch headers ─────────────────────────────────────────────────
    resp_info = _fetch(url)
    if isinstance(resp_info, str):
        return resp_info  # error string

    final_url, status, hdrs, redirect_chain = resp_info

    if action == "headers":   return _check_headers(final_url, status, hdrs)
    if action == "tls":       return _check_tls(parsed.hostname)
    if action == "redirects": return _check_redirects(url, redirect_chain, final_url)
    if action == "cookies":   return _check_cookies(hdrs)
    if action == "info":      return _server_info(final_url, status, hdrs)

    if action == "scan":
        parts = [
            "=" * 55,
            f"  SECURITY SCAN  —  {_truncate(final_url, 45)}",
            "=" * 55,
            "",
            _check_headers(final_url, status, hdrs),
            "",
            _check_tls(parsed.hostname),
            "",
            _check_redirects(url, redirect_chain, final_url),
            "",
            _check_cookies(hdrs),
            "",
            _server_info(final_url, status, hdrs),
            "",
            _score(final_url, status, hdrs, redirect_chain, parsed.hostname),
        ]
        return "\n".join(parts)

    return f"Unknown action '{action}'. Use: scan, headers, tls, redirects, cookies, info."


# ── network helpers ───────────────────────────────────────────────────────────

def _fetch(url: str):
    """Returns (final_url, status, headers_dict, redirect_chain) or error string."""
    redirect_chain: list[tuple[str, int]] = []
    current = url
    ctx = ssl.create_default_context()
    for _ in range(10):
        req = urllib.request.Request(current, method="HEAD", headers={"User-Agent": "AetherSecChecker/1.0"})
        try:
            # We use a no-redirect opener to track chain manually
            opener = urllib.request.build_opener(urllib.request.HTTPRedirectHandler())
            with opener.open(req, timeout=_TIMEOUT) as resp:
                hdrs = {k.lower(): v for k, v in resp.headers.items()}
                return current, resp.status, hdrs, redirect_chain
        except urllib.error.HTTPError as e:
            if e.code in (301, 302, 303, 307, 308) and "Location" in e.headers:
                redirect_chain.append((current, e.code))
                current = e.headers["Location"]
                if not current.startswith("http"):
                    current = urlparse(url).scheme + "://" + urlparse(url).hostname + current
                continue
            hdrs = {k.lower(): v for k, v in e.headers.items()}
            return current, e.code, hdrs, redirect_chain
        except urllib.error.URLError as e:
            return f"Error connecting to {url}: {e.reason}"
        except ssl.SSLError as e:
            return f"TLS/SSL error: {e}"
        except Exception as e:
            return f"Request error: {e}"
    return f"Error: Too many redirects following {url}."


def _check_headers(url: str, status: int, hdrs: dict) -> str:
    present  = []
    missing  = []
    for header, (short, desc) in _SECURITY_HEADERS.items():
        val = hdrs.get(header, "")
        if val:
            present.append(f"  ✔ {short:<14} [{header}]: {_truncate(val, 60)}")
        else:
            missing.append(f"  ✘ {short:<14} [{header}] — MISSING — {desc}")

    lines = [f"[ HTTP Security Headers ]  (Status {status})"]
    lines += present
    if missing:
        lines.append("")
        lines += missing
    score = len(present)
    total = len(_SECURITY_HEADERS)
    lines.append(f"\n  Headers present: {score}/{total}")
    return "\n".join(lines)


def _check_tls(hostname: str | None) -> str:
    if not hostname:
        return "[ TLS ] — No hostname to check."
    lines = ["[ TLS / SSL Certificate ]"]
    try:
        ctx = ssl.create_default_context()
        with socket.create_connection((hostname, 443), timeout=_TIMEOUT) as sock:
            with ctx.wrap_socket(sock, server_hostname=hostname) as ssock:
                cert    = ssock.getpeercert()
                cipher  = ssock.cipher()
                version = ssock.version()
        subject = dict(x[0] for x in cert.get("subject", []))
        issuer  = dict(x[0] for x in cert.get("issuer", []))
        lines += [
            f"  Protocol    : {version}",
            f"  Cipher      : {cipher[0] if cipher else 'unknown'}",
            f"  Common Name : {subject.get('commonName', '?')}",
            f"  Issuer      : {issuer.get('organizationName', '?')}",
            f"  Valid From  : {cert.get('notBefore', '?')}",
            f"  Valid Until : {cert.get('notAfter', '?')}",
            f"  ALT Names   : {', '.join(h for _, h in cert.get('subjectAltName', [])[:6])}",
        ]
        # Warn on old TLS
        if version in ("TLSv1", "TLSv1.1", "SSLv3"):
            lines.append(f"  ⚠ WARNING: {version} is deprecated and insecure!")
    except ssl.SSLCertVerificationError as e:
        lines.append(f"  ✘ Certificate verification FAILED: {e}")
    except ConnectionRefusedError:
        lines.append("  Port 443 not reachable — site may not support HTTPS.")
    except Exception as e:
        lines.append(f"  Error checking TLS: {e}")
    return "\n".join(lines)


def _check_redirects(original: str, chain: list, final: str) -> str:
    lines = ["[ Redirect Chain ]"]
    all_hops = [(original, "START")] + [(u, str(c)) for u, c in chain] + [(final, "FINAL")]
    for i, (u, label) in enumerate(all_hops):
        scheme = urlparse(u).scheme
        flag   = "🔒" if scheme == "https" else "⚠ HTTP"
        lines.append(f"  {i:2}. [{label:5}] {flag}  {_truncate(u, 60)}")
    # Flag HTTP-only (no upgrade to HTTPS)
    if urlparse(final).scheme == "http":
        lines.append("  ⚠ WARNING: Final URL is plain HTTP — no HTTPS upgrade detected.")
    elif urlparse(original).scheme == "http" and urlparse(final).scheme == "https":
        lines.append("  ✔ HTTP→HTTPS redirect is in place.")
    return "\n".join(lines)


def _check_cookies(hdrs: dict) -> str:
    raw_cookies = hdrs.get("set-cookie", "")
    if not raw_cookies:
        return "[ Cookies ] — No Set-Cookie headers found."
    # Headers may contain multiple cookies as a single concatenated string
    cookies = [c.strip() for c in raw_cookies.split(",") if "=" in c]
    lines = [f"[ Cookies ]  ({len(cookies)} found)"]
    for ck in cookies[:10]:
        parts = [p.strip().lower() for p in ck.split(";")]
        name  = ck.split("=")[0].strip()
        has_secure   = "secure"   in parts
        has_httponly = "httponly" in parts
        samesite     = next((p for p in parts if p.startswith("samesite")), None)
        flags = []
        flags.append("✔ Secure"   if has_secure   else "✘ Secure MISSING")
        flags.append("✔ HttpOnly" if has_httponly  else "✘ HttpOnly MISSING")
        flags.append(f"✔ {samesite.title()}" if samesite else "✘ SameSite MISSING")
        lines.append(f"  {name} :  {' | '.join(flags)}")
    return "\n".join(lines)


def _server_info(url: str, status: int, hdrs: dict) -> str:
    server    = hdrs.get("server", "(not disclosed)")
    powered   = hdrs.get("x-powered-by", "(not disclosed)")
    aspnet    = hdrs.get("x-aspnet-version", "")
    aspnetmvc = hdrs.get("x-aspnetmvc-version", "")
    via       = hdrs.get("via", "")
    lines = [
        "[ Server Info ]",
        f"  URL            : {_truncate(url, 60)}",
        f"  HTTP Status    : {status}",
        f"  Server         : {server}",
        f"  X-Powered-By   : {powered}",
    ]
    if aspnet:    lines.append(f"  ASP.NET Version: {aspnet}")
    if aspnetmvc: lines.append(f"  ASP.NET MVC    : {aspnetmvc}")
    if via:       lines.append(f"  Via (proxy)    : {via}")
    # Check for info disclosure warnings
    if server not in ("(not disclosed)", "") and any(
        tech in server.lower() for tech in ["apache", "nginx", "iis", "php", "microsoft"]
    ):
        lines.append("  ⚠ Server header discloses technology — consider hiding it.")
    if powered not in ("(not disclosed)", ""):
        lines.append("  ⚠ X-Powered-By discloses framework — consider removing it.")
    return "\n".join(lines)


def _score(url: str, status: int, hdrs: dict, chain: list, hostname: str | None) -> str:
    """Simple overall security score out of 100."""
    score = 0
    max_s = 0

    # Headers (60 pts)
    for h in _SECURITY_HEADERS:
        max_s += 5
        if hdrs.get(h):
            score += 5

    # HTTPS final (15 pts)
    max_s += 15
    if urlparse(url).scheme == "https":
        score += 15

    # No version disclosure (10 pts)
    max_s += 10
    server  = hdrs.get("server", "")
    powered = hdrs.get("x-powered-by", "")
    if not server and not powered:
        score += 10
    elif not powered:
        score += 5

    # Redirect to HTTPS (15 pts — already there if score > 0 for HTTPS)
    max_s += 15
    if any(urlparse(from_url).scheme == "http" for from_url, _ in chain):
        if urlparse(url).scheme == "https":
            score += 15

    pct = int(score / max_s * 100) if max_s > 0 else 0
    bar_fill = int(pct / 5)
    bar = "█" * bar_fill + "░" * (20 - bar_fill)
    if pct >= 80:    grade = "A — Good"
    elif pct >= 60:  grade = "B — Acceptable"
    elif pct >= 40:  grade = "C — Needs Work"
    elif pct >= 20:  grade = "D — Weak"
    else:            grade = "F — Poor"

    return f"[ Overall Security Score ]\n  [{bar}] {pct}%  Grade: {grade}"


def _truncate(s: str, n: int) -> str:
    return s if len(s) <= n else s[:n - 3] + "..."
