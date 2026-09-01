"""Standalone Playwright Browser Captcha Solver API Server.

Runs as a standalone microservice on http://127.0.0.1:5001.
Maintains a pool/queue of Playwright Chromium instances loaded with the
selected browser extension (configured in config.json or per-request) to solve
hCaptcha, reCAPTCHA, and Turnstile challenges.

API Specification:
  - POST /solve
      Payload: {
        "sitekey": "a9b5fb07-92ff-493f-86fe-352a2803b3df",
        "host": "discord.com",
        "userAgent": "Mozilla/5.0 ...",
        "proxy": "http://user:pass@host:port",
        "rqdata": "...",
        "extension": "nopecha" | "captchasonic"  # Optional override
      }
      Response: { "task_id": "uuid-str", "status": "processing" }

  - GET /result/<task_id>
      Response: { "status": "completed", "token": "P1_..." }
            or: { "status": "processing" }
            or: { "status": "failed", "error": "description" }
"""

import os
import time
import uuid
import json
import tempfile
import threading
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
import sys
from playwright.sync_api import sync_playwright

os.environ["CLOAKBROWSER_SUPPRESS_FONT_WARNING"] = "1"

try:
    import cloakbrowser
    USE_CLOAKBROWSER = True
except ImportError:
    USE_CLOAKBROWSER = False

# Works whether server.py is launched as a script (run.py) or imported as part
# of the captchasonic_solver package.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from stealth import (
    apply_user_agent_override,
    build_init_script,
    generate_dynamic_profile,
    parse_user_agent,
    stealth_launch_args,
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")
EXTENSIONS_DIR = os.path.join(BASE_DIR, "extensions")
CAPTCHASONIC_EXT_PATH = os.path.join(EXTENSIONS_DIR, "captchasonic")
NOPECHA_EXT_PATH = os.path.join(EXTENSIONS_DIR, "nopecha")

HCAPTCHA_WRAPPER_HTML = """<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Captcha Render</title>
    <script src="https://js.hcaptcha.com/1/api.js?render=explicit" async defer></script>
</head>
<body style="background:#202225; display:flex; justify-content:center; align-items:center; height:100vh; margin:0;">
    <div id="captcha-container"></div>
    <script>
        // Resolves once js.hcaptcha.com/1/api.js has finished loading. Without
        // this the render call can fire before `hcaptcha` exists (the script is
        // async/defer), which would drop the rqdata binding on the floor.
        window.hcaptchaReady = function(timeoutMs) {
            return new Promise(function(resolve) {
                var deadline = Date.now() + (timeoutMs || 30000);
                (function poll() {
                    if (typeof hcaptcha !== 'undefined' && hcaptcha && hcaptcha.render) {
                        return resolve(true);
                    }
                    if (Date.now() > deadline) { return resolve(false); }
                    setTimeout(poll, 100);
                })();
            });
        };

        window.initCaptcha = function(sitekey, rqdata) {
            var opts = {
                sitekey: sitekey,
                // Discord's real client uses an invisible widget driven by
                // execute(). rqdata is only honoured on that path.
                size: 'invisible',
                callback: function(token) {
                    window.hcaptchaToken = token;
                },
                "error-callback": function(err) {
                    window.hcaptchaError = err || "Rate limited or network error";
                },
                "chalexpired-callback": function() {
                    window.hcaptchaExpired = true;
                },
                "expired-callback": function() {
                    window.hcaptchaExpired = true;
                }
            };
            try {
                window.hcaptchaWidgetId = hcaptcha.render('captcha-container', opts);
            } catch (e) {
                window.hcaptchaError = (e && e.message) || "Failed to render captcha";
                return { ok: false, error: window.hcaptchaError };
            }
            try {
                // CRITICAL: rqdata MUST be passed to execute(), not to render().
                // hcaptcha.render() accepts an `rqdata` key and then silently
                // discards it -- it never reaches /getcaptcha, so the token comes
                // back perfectly valid but bound to NOTHING. Discord then refuses
                // it with `invalid-response` on every single attempt, no matter
                // how cleanly the challenge was solved. Verified by request
                // inspection: render({rqdata}) puts nothing in the getcaptcha
                // body, while execute(id, {rqdata}) validates it (a malformed
                // value raises `invalid-data`).
                if (rqdata) {
                    hcaptcha.execute(window.hcaptchaWidgetId, { rqdata: rqdata });
                    window.hcaptchaRqdataApplied = true;
                } else {
                    hcaptcha.execute(window.hcaptchaWidgetId);
                    window.hcaptchaRqdataApplied = false;
                }
                return { ok: true, widgetId: String(window.hcaptchaWidgetId) };
            } catch (e) {
                window.hcaptchaError = (e && e.message) || "Failed to execute captcha";
                return { ok: false, error: window.hcaptchaError };
            }
        };
    </script>
</body>
</html>"""

tasks = {}
tasks_lock = threading.Lock()

# Each solve launches a full headful Chromium with the extension loaded
# (~300-500 MB each). With 10 joiner threads, simultaneous captchas would open
# 10 browsers at once and thrash the machine. Queue them instead — the client
# polls /result and simply waits its turn.
_browser_slots = None
_browser_slots_lock = threading.Lock()


def _get_browser_slots():
    global _browser_slots
    with _browser_slots_lock:
        if _browser_slots is None:
            limit = max(1, int(load_config().get("max_concurrent_solves", 3)))
            _browser_slots = threading.BoundedSemaphore(limit)
            print(f"Solver concurrency limit: {limit} simultaneous browser(s).")
        return _browser_slots


def load_config():
    default_config = {
        "extension": "nopecha",
        "port": 5001,
        "host": "127.0.0.1",
        "timeout": 90,
    }
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                default_config.update(data)
        except Exception as e:
            print(f"Warning: Failed to load config.json: {e}")
    return default_config


def _resolve_proxy(proxy_str):
    if not proxy_str:
        return None
    clean = proxy_str.strip()
    scheme = "http"
    if "://" in clean:
        scheme, clean = clean.split("://", 1)
    auth_dict = {}
    if "@" in clean:
        auth, hostport = clean.split("@", 1)
        if ":" in auth:
            u, p = auth.split(":", 1)
            auth_dict = {"username": u, "password": p}
        clean = hostport
    elif clean.count(":") == 3:
        # host:port:user:pass or user:pass:host:port
        parts = clean.split(":")
        if parts[1].isdigit():
            clean = f"{parts[0]}:{parts[1]}"
            auth_dict = {"username": parts[2], "password": parts[3]}
        elif parts[3].isdigit():
            clean = f"{parts[2]}:{parts[3]}"
            auth_dict = {"username": parts[0], "password": parts[1]}
        else:
            clean = f"{parts[0]}:{parts[1]}"
            auth_dict = {"username": parts[2], "password": parts[3]}

    if ":" in clean:
        h, pt = clean.split(":", 1)
        try:
            pt_int = int(pt)
        except ValueError:
            pt_int = 80
        res = {"server": f"{scheme}://{h}:{pt_int}"}
        res.update(auth_dict)
        return res
    return {"server": f"{scheme}://{clean}"}


def _worker_solve(task_id, payload):
    slots = _get_browser_slots()
    with slots:
        _worker_solve_inner(task_id, payload)


def _worker_solve_inner(task_id, payload):
    sitekey = payload.get("sitekey", "a9b5fb07-92ff-493f-86fe-352a2803b3df")
    rqdata = payload.get("rqdata", "")
    proxy_str = payload.get("proxy")
    pw_proxy = _resolve_proxy(proxy_str)

    user_agent = payload.get("userAgent")
    platform = payload.get("platform")
    platform_version = payload.get("platformVersion")
    timezone_id = payload.get("timezone")
    locale = payload.get("locale")

    # If no profile/userAgent is given, generate an authentic, self-consistent profile automatically
    if not user_agent:
        dyn_prof = generate_dynamic_profile(platform_hint=platform, proxy=proxy_str)
        user_agent = dyn_prof["user_agent"]
        platform = dyn_prof["platform"]
        platform_version = dyn_prof["platform_version"]
        if not timezone_id:
            timezone_id = dyn_prof["timezone"]
        if not locale:
            locale = dyn_prof["locale"]
        ident = dyn_prof["ident"]
        print(
            f"[{task_id[:8]}] Auto-generated profile: {platform} | Chrome {ident['full_version']} "
            f"| tz={timezone_id} | hw_concurrency={dyn_prof['hardware_concurrency']}"
        )
    else:
        ident = parse_user_agent(
            user_agent,
            platform_hint=platform,
            platform_version_hint=platform_version,
        )
        if not locale:
            locale = "en-US"
        if not timezone_id and proxy_str:
            try:
                from utils.proxy import detect_timezone
                timezone_id = detect_timezone(proxy_str, user_agent=user_agent)
            except Exception:
                pass

    cfg = load_config()
    provider = (
        payload.get("extension")
        or payload.get("provider")
        or cfg.get("extension")
        or "nopecha"
    ).lower()

    if provider in ("captchasonic", "captchasonic_solver", "captchas"):
        ext_path = CAPTCHASONIC_EXT_PATH
        ext_name = "CaptchaSonic"
    else:
        ext_path = NOPECHA_EXT_PATH
        ext_name = "Bit Solver"

    print(
        f"[{task_id[:8]}] Worker starting Playwright solve via {ext_name} "
        f"(identity: Chrome {ident['full_version']} on {ident['platform']}"
        f"{', tz=' + timezone_id if timezone_id else ''})..."
    )

    with tempfile.TemporaryDirectory() as user_data_dir:
        context = None
        pw_instance = None
        try:
            if USE_CLOAKBROWSER:
                try:
                    cloak_kwargs = {
                        "user_data_dir": user_data_dir,
                        "headless": False,
                        "user_agent": user_agent,
                        "locale": locale,
                        "extension_paths": [ext_path],
                        "humanize": True,
                        "args": [
                            "--no-sandbox",
                            "--disable-setuid-sandbox",
                            f"--lang={locale}",
                        ]
                        + stealth_launch_args(),
                    }
                    if timezone_id:
                        cloak_kwargs["timezone"] = timezone_id
                    if pw_proxy:
                        cloak_kwargs["proxy"] = pw_proxy

                    context = cloakbrowser.launch_persistent_context(**cloak_kwargs)
                except Exception as ce:
                    print(f"[{task_id[:8]}] CloakBrowser launch note: {ce}. Falling back to standard Playwright...")
                    context = None

            if not context:
                pw_instance = sync_playwright().start()
                launch_kwargs = {
                    "user_data_dir": user_data_dir,
                    "headless": False,
                    "user_agent": user_agent,
                    "locale": locale,
                    "args": [
                        f"--disable-extensions-except={ext_path}",
                        f"--load-extension={ext_path}",
                        "--no-sandbox",
                        "--disable-setuid-sandbox",
                        f"--lang={locale}",
                    ]
                    + stealth_launch_args(),
                }
                if timezone_id:
                    launch_kwargs["timezone_id"] = timezone_id
                if pw_proxy:
                    launch_kwargs["proxy"] = pw_proxy

                context = pw_instance.chromium.launch_persistent_context(**launch_kwargs)

            # Patch the JS surfaces CDP cannot reach, before any page loads.
            context.add_init_script(build_init_script(ident, locale))

            # Render hCaptcha challenge on domain context
            page = context.pages[0] if context.pages else context.new_page()

            # Rewrite client hints + navigator.platform to agree with the UA.
            try:
                apply_user_agent_override(context, page, ident, locale)
            except Exception as ua_err:
                print(
                    f"[{task_id[:8]}] Warning: client-hint override failed "
                    f"({type(ua_err).__name__}: {ua_err}). Token score may suffer."
                )

            # Track how many challenges hCaptcha serves for this widget.
            #
            # An rqdata-bound challenge is single-use. If the extension
            # answers the images WRONG, hCaptcha discards that challenge and
            # issues a fresh one (visible as "new pictures loading"). The
            # extension then solves the replacement and we DO get a token --
            # but that token is no longer bound to the rqdata Discord issued,
            # so Discord's siteverify rejects it with `invalid-response`.
            #
            # Every new challenge means another /getcaptcha call, so counting
            # them tells us the original binding is gone and the token would
            # be worthless. Only requests are inspected (never response
            # bodies) to avoid blocking the sync event loop.
            challenge_state = {"getcaptcha": 0, "checkcaptcha": 0}

            def _on_request(request):
                try:
                    url = request.url
                    if "/getcaptcha" in url:
                        challenge_state["getcaptcha"] += 1
                    elif "/checkcaptcha" in url:
                        challenge_state["checkcaptcha"] += 1
                except Exception:
                    pass

            page.on("request", _on_request)

            # ---------------------------------------------------------
            # CORS fix for proxied hCaptcha API calls.
            #
            # hCaptcha's challenge iframe (newassets.hcaptcha.com) makes
            # cross-origin XHR POSTs to api.hcaptcha.com/getcaptcha and
            # /checkcaptcha.  Without a proxy the response carries the
            # correct `Access-Control-Allow-Origin` header and Chrome
            # lets the iframe read it.  With many ISP/residential proxies
            # the CONNECT tunnel interferes with the response framing and
            # Chrome drops the CORS headers, causing net::ERR_FAILED on
            # every /getcaptcha call — the challenge never loads.
            #
            # The workaround: intercept those responses through
            # Playwright's route API, re-fetch them (Playwright's fetch
            # goes through the same proxy but handles the tunnel itself),
            # and fulfill with the CORS headers explicitly set.
            # ---------------------------------------------------------
            if pw_proxy:
                _CORS_HEADERS = {
                    "access-control-allow-origin": "https://newassets.hcaptcha.com",
                    "access-control-allow-credentials": "true",
                    "access-control-allow-methods": "GET, HEAD, POST, OPTIONS",
                    "access-control-allow-headers": (
                        "Cache-Control, Content-Type, DNT, Referer, User-Agent"
                    ),
                }

                def _cors_fix(route):
                    try:
                        resp = route.fetch()
                        headers = dict(resp.headers)
                        headers.update(_CORS_HEADERS)
                        route.fulfill(
                            status=resp.status,
                            headers=headers,
                            body=resp.body(),
                        )
                    except Exception:
                        # Context already closing — let the request through.
                        try:
                            route.continue_()
                        except Exception:
                            pass

                page.route("**/api.hcaptcha.com/checksiteconfig/**", _cors_fix)
                page.route("**/api2.hcaptcha.com/checksiteconfig/**", _cors_fix)
                page.route("**/hcaptcha.com/checksiteconfig/**", _cors_fix)
                page.route("**/api.hcaptcha.com/getcaptcha/**", _cors_fix)
                page.route("**/api2.hcaptcha.com/getcaptcha/**", _cors_fix)
                page.route("**/hcaptcha.com/getcaptcha/**", _cors_fix)
                page.route("**/api.hcaptcha.com/checkcaptcha/**", _cors_fix)
                page.route("**/api2.hcaptcha.com/checkcaptcha/**", _cors_fix)
                page.route("**/hcaptcha.com/checkcaptcha/**", _cors_fix)

            host_val = payload.get("host", "discord.com")
            if host_val.startswith("http://") or host_val.startswith("https://"):
                target_url = host_val
            else:
                target_url = f"https://{host_val}/captcha_render"

            if target_url.endswith("/captcha_render"):
                page.route(
                    target_url,
                    lambda route: route.fulfill(
                        status=200,
                        content_type="text/html",
                        body=HCAPTCHA_WRAPPER_HTML,
                    ),
                )

            page.goto(target_url)
            if target_url.endswith("/captcha_render"):
                # Wait for js.hcaptcha.com to finish loading. The api.js tag
                # is async/defer, so page load does not imply `hcaptcha`
                # exists yet.
                if not page.evaluate("() => window.hcaptchaReady(30000)"):
                    raise Exception(
                        "hCaptcha api.js failed to load (blocked proxy or network?)"
                    )

                # Pass sitekey/rqdata as real JS arguments. Interpolating
                # them into the source risks breaking the expression on any
                # quote/backslash in the rqdata blob, which would silently
                # render the widget WITHOUT the enterprise binding.
                render_result = page.evaluate(
                    "([k, r]) => window.initCaptcha(k, r)", [sitekey, rqdata]
                )
                if not (render_result or {}).get("ok"):
                    raise Exception(
                        f"hcaptcha.render failed: {(render_result or {}).get('error')}"
                    )
                if rqdata and not page.evaluate("() => !!window.hcaptchaRqdataApplied"):
                    raise Exception("rqdata was not applied to the widget")

            print(
                f"[{task_id[:8]}] Captcha rendered at {target_url} "
                f"(rqdata={'yes' if rqdata else 'no'}). "
                f"Waiting for {ext_name} extension to solve..."
            )

            start_time = time.time()
            timeout_seconds = float(cfg.get("timeout", 90.0))
            # How many challenges may be served before we treat the rqdata
            # binding as burned. Multi-step hCaptcha challenges serve 2+ pages.
            max_challenges = int(cfg.get("max_challenges", 4))

            while time.time() - start_time < timeout_seconds:
                err = page.evaluate("window.hcaptchaError || null")
                if err:
                    # `invalid-data` is hCaptcha rejecting the rqdata itself
                    # (malformed, expired, or already consumed) rather than a
                    # proxy/network problem. Retrying the same rqdata cannot
                    # help — the caller needs a fresh challenge from Discord.
                    if "invalid-data" in str(err):
                        print(
                            f"[{task_id[:8]}] hCaptcha rejected the rqdata ({err}). "
                            f"It is malformed, expired or already used — a fresh "
                            f"challenge is required."
                        )
                        with tasks_lock:
                            tasks[task_id] = {
                                "status": "failed",
                                "error": f"rqdata rejected by hCaptcha: {err}",
                                "error_code": "challenge_burned",
                            }
                        context.close()
                        return
                    print(f"[{task_id[:8]}] Captcha error / rate-limit detected: {err}")
                    with tasks_lock:
                        tasks[task_id] = {
                            "status": "failed",
                            "error": f"Proxy / Captcha error: {err}",
                        }
                    context.close()
                    return

                token = page.evaluate("window.hcaptchaToken || null")
                if not token:
                    try:
                        textarea_val = page.locator(
                            "[name=h-captcha-response]"
                        ).input_value(timeout=500)
                        if textarea_val and len(textarea_val) > 20:
                            token = textarea_val
                    except Exception:
                        pass

                if not token:
                    try:
                        g_val = page.locator(
                            "[name=g-recaptcha-response]"
                        ).input_value(timeout=500)
                        if g_val and len(g_val) > 20:
                            token = g_val
                    except Exception:
                        pass

                if not token:
                    try:
                        cf_val = page.locator(
                            "[name=cf-turnstile-response]"
                        ).input_value(timeout=500)
                        if cf_val and len(cf_val) > 20:
                            token = cf_val
                    except Exception:
                        pass

                # A replacement challenge means the extension got the images
                # wrong and the rqdata binding died with the original
                # challenge. Returning this token would guarantee an
                # `invalid-response` from Discord, and the caller would keep
                # resubmitting against the same dead rqdata. Fail instead, so
                # the caller fetches a FRESH challenge from Discord.
                if rqdata and (challenge_state["getcaptcha"] > 1 and challenge_state["checkcaptcha"] >= 1):
                    print(
                        f"[{task_id[:8]}] Extension answered incorrectly: hCaptcha served "
                        f"{challenge_state['getcaptcha']} challenges "
                        f"({challenge_state['checkcaptcha']} submissions). The rqdata-bound "
                        f"challenge is burned -- a token from the replacement would be "
                        f"rejected. Failing so a fresh challenge is requested."
                    )
                    with tasks_lock:
                        tasks[task_id] = {
                            "status": "failed",
                            "error": "challenge_burned: wrong answer replaced the "
                                     "rqdata-bound challenge",
                            "error_code": "challenge_burned",
                            "challenges": challenge_state["getcaptcha"],
                        }
                    context.close()
                    return

                if token:
                    print(
                        f"[{task_id[:8]}] Captcha solved successfully via {ext_name}! "
                        f"Token len={len(token)} (challenges={challenge_state['getcaptcha']}, "
                        f"submissions={challenge_state['checkcaptcha']})"
                    )
                    with tasks_lock:
                        tasks[task_id] = {
                            "status": "completed",
                            "token": token,
                        }
                    context.close()
                    return

                # An expired challenge yields a token Discord will always
                # reject. Fail fast so the caller re-solves instead of
                # submitting a dead token and getting a fresh challenge back.
                if page.evaluate("window.hcaptchaExpired || null"):
                    print(f"[{task_id[:8]}] Challenge expired before a token was captured.")
                    with tasks_lock:
                        tasks[task_id] = {
                            "status": "failed",
                            "error": "hCaptcha challenge expired before solve completed",
                        }
                    context.close()
                    return

                time.sleep(1.5)

            print(f"[{task_id[:8]}] Captcha solve timed out ({timeout_seconds}s limit).")
            with tasks_lock:
                tasks[task_id] = {
                    "status": "failed",
                    "error": f"Captcha solving timed out ({timeout_seconds}s) with {ext_name}",
                }
            context.close()

        except Exception as e:
            print(f"[{task_id[:8]}] Worker error: {e}")
            with tasks_lock:
                tasks[task_id] = {"status": "failed", "error": str(e)}


class ReuseAddressHTTPServer(ThreadingHTTPServer):
    # Threaded, not plain HTTPServer: with N joiner threads each polling
    # /result every 2s, a single-threaded server serialises every request and
    # one slow client stalls all of them.
    allow_reuse_address = True
    daemon_threads = True


class CaptchasonicRequestHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # Quiet logging

    def _send_json(self, data, status_code=200):
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode("utf-8"))

    def do_POST(self):
        if self.path == "/solve":
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)
            try:
                payload = json.loads(body.decode("utf-8")) if body else {}
            except Exception:
                payload = {}

            task_id = str(uuid.uuid4())
            with tasks_lock:
                tasks[task_id] = {"status": "processing"}

            t = threading.Thread(
                target=_worker_solve, args=(task_id, payload), daemon=True
            )
            t.start()

            self._send_json({"task_id": task_id, "status": "processing"})
        else:
            self._send_json({"error": "Not Found"}, 404)

    def do_GET(self):
        if self.path.startswith("/result/"):
            task_id = self.path.replace("/result/", "").strip()
            with tasks_lock:
                res = tasks.get(task_id)

            if not res:
                self._send_json({"status": "failed", "error": "Task not found"}, 404)
            else:
                self._send_json(res)
        elif self.path == "/health":
            self._send_json({"status": "ok"})
        else:
            self._send_json({"error": "Not Found"}, 404)


def run_server():
    cfg = load_config()
    host = cfg.get("host", "127.0.0.1")
    port = int(cfg.get("port", 5001))
    server_address = (host, port)
    httpd = ReuseAddressHTTPServer(server_address, CaptchasonicRequestHandler)
    print(f"Standalone Playwright Captcha Solver API server running on http://{host}:{port} (Extension: {cfg.get('extension', 'nopecha')})...")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("Server stopping...")
        httpd.server_close()


if __name__ == "__main__":
    run_server()

