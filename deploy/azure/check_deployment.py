"""
Checks a deployed Sceptic site from outside. Uses only the Python standard library.

    python deploy/azure/check_deployment.py https://sceptic-yourname.centralindia.cloudapp.azure.com

Exit code 0 when every check passes, 1 otherwise.
"""
import json
import ssl
import sys
import urllib.error
import urllib.request

failures = 0


def get(url, timeout=20):
    request = urllib.request.Request(url, headers={"User-Agent": "sceptic-deployment-check"})
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=ssl.create_default_context()) as response:
            return response.status, dict(response.headers), response.read()
    except urllib.error.HTTPError as error:
        return error.code, dict(error.headers), error.read()
    except Exception as error:  # DNS, TLS and connection problems
        return None, {}, str(error).encode()


def check(name, ok, detail=""):
    global failures
    print(f"{'PASS' if ok else 'FAIL'}  {name}{('  (' + detail + ')') if detail else ''}")
    failures += 0 if ok else 1


def main():
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    base = sys.argv[1].rstrip("/")
    check("address uses HTTPS", base.startswith("https://") or base.startswith("http://localhost"))

    status, headers, body = get(base + "/")
    check("portal page loads", status == 200 and b'id="root"' in body, f"HTTP {status}")
    check("portal links the PWA manifest", b"manifest.webmanifest" in body)

    status, headers, body = get(base + "/manifest.webmanifest")
    check("manifest is served", status == 200 and b'"standalone"' in body, f"HTTP {status}")
    status, headers, body = get(base + "/sw.js")
    check("service worker is served", status == 200 and b"NEVER_CACHE" in body, f"HTTP {status}")
    check("service worker is not cached by the browser", "no-cache" in headers.get("Cache-Control", "").lower(),
          headers.get("Cache-Control", "missing"))
    status, headers, body = get(base + "/icons/icon-512.png")
    check("app icon is served", status == 200 and body[:4] == b"\x89PNG", f"HTTP {status}")

    status, headers, body = get(base + "/api/health")
    ok = status == 200
    try:
        ok = ok and json.loads(body).get("status") == "ok"
    except ValueError:
        ok = False
    check("backend /api/health answers ok", ok, f"HTTP {status}")
    status, headers, body = get(base + "/api/health/db")
    check("database is reachable", status == 200, f"HTTP {status}")
    status, headers, body = get(base + "/api/audits")
    check("protected API requires login", status in (401, 403), f"HTTP {status}")
    status, headers, body = get(base + "/api/projects")
    check("projects API requires login", status in (401, 403), f"HTTP {status}")
    check("HSTS header present", "Strict-Transport-Security" in headers or base.startswith("http://localhost"))

    print("\nAll checks passed." if failures == 0 else f"\n{failures} check(s) failed.")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
