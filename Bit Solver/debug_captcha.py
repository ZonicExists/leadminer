"""Deep debug: launch the EXACT same browser config as server.py, with and
without proxy, capture screenshots + all network traffic + DOM state + frame
tree.  Produces side-by-side evidence of exactly where hCaptcha diverges."""

import os, sys, time, tempfile, json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from playwright.sync_api import sync_playwright
from stealth import apply_user_agent_override, build_init_script, parse_user_agent, stealth_launch_args

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
NOPECHA_EXT_PATH = os.path.join(BASE_DIR, "extensions", "nopecha")
CAPTCHASONIC_EXT_PATH = os.path.join(BASE_DIR, "extensions", "captchasonic")

HCAPTCHA_WRAPPER_HTML = open(os.devnull, "r")  # we'll grab it from server.py
# Actually re-import from server
import importlib.util
spec = importlib.util.spec_from_file_location("server", os.path.join(BASE_DIR, "server.py"))
server_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server_mod)
HCAPTCHA_WRAPPER_HTML = server_mod.HCAPTCHA_WRAPPER_HTML

SITEKEY = "a9b5fb07-92ff-493f-86fe-352a2803b3df"
PROXY_STR = "http://user-spxcng7zgx-ip-48.45.206.205:i1ZscjU8uhz61d~OgB@isp.decodo.com:10002"
OUTPUT_DIR = os.path.join(BASE_DIR, "debug_output")
os.makedirs(OUTPUT_DIR, exist_ok=True)

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"


def run_debug(label, use_proxy):
    print(f"\n{'='*70}")
    print(f"  TEST: {label}  (proxy={'YES' if use_proxy else 'NO'})")
    print(f"{'='*70}\n")

    ident = parse_user_agent(UA)
    locale = "en-US"
    pw_proxy = server_mod._resolve_proxy(PROXY_STR) if use_proxy else None
    ext_path = NOPECHA_EXT_PATH  # match current config

    requests_log = []
    responses_log = []
    failed_log = []
    console_log = []

    with tempfile.TemporaryDirectory() as user_data_dir:
        with sync_playwright() as p:
            launch_kwargs = {
                "user_data_dir": user_data_dir,
                # HEADFUL, exactly like server.py line 263
                "headless": False,
                "user_agent": UA,
                "locale": locale,
                "args": [
                    f"--disable-extensions-except={ext_path}",
                    f"--load-extension={ext_path}",
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    f"--lang={locale}",
                ] + stealth_launch_args(),
            }
            if pw_proxy:
                launch_kwargs["proxy"] = pw_proxy

            context = p.chromium.launch_persistent_context(**launch_kwargs)
            context.add_init_script(build_init_script(ident, locale))
            page = context.pages[0] if context.pages else context.new_page()

            try:
                apply_user_agent_override(context, page, ident, locale)
            except Exception as e:
                print(f"  [WARN] UA override failed: {e}")

            # ---------- listeners ----------
            def _on_request(req):
                entry = {"url": req.url, "method": req.method, "resourceType": req.resource_type}
                requests_log.append(entry)

            def _on_response(res):
                entry = {"url": res.url, "status": res.status, "ok": res.ok}
                responses_log.append(entry)
                # Print hcaptcha API responses inline
                if "hcaptcha.com" in res.url:
                    suffix = ""
                    if "checksiteconfig" in res.url or "getcaptcha" in res.url or "checkcaptcha" in res.url:
                        try:
                            body = res.text()[:500]
                            suffix = f" body={body}"
                        except:
                            pass
                    print(f"  [RESP {res.status}] {res.url[:90]}{suffix}")

            def _on_failed(req):
                entry = {"url": req.url, "failure": str(req.failure)}
                failed_log.append(entry)
                print(f"  [FAILED] {req.url[:90]}  reason={req.failure}")

            def _on_console(msg):
                entry = {"type": msg.type, "text": msg.text}
                console_log.append(entry)
                if msg.type in ("error", "warning"):
                    print(f"  [CONSOLE {msg.type}] {msg.text[:120]}")

            page.on("request", _on_request)
            page.on("response", _on_response)
            page.on("requestfailed", _on_failed)
            page.on("console", _on_console)

            # ---------- navigate + render captcha ----------
            target_url = "https://discord.com/captcha_render"
            page.route(target_url, lambda route: route.fulfill(
                status=200, content_type="text/html", body=HCAPTCHA_WRAPPER_HTML
            ))
            page.goto(target_url, wait_until="domcontentloaded")
            print(f"  Page loaded: {page.url}")

            # Screenshot: initial page
            page.screenshot(path=os.path.join(OUTPUT_DIR, f"{label}_01_initial.png"))
            print(f"  Screenshot: {label}_01_initial.png")

            # Wait for hcaptcha JS
            ready = page.evaluate("() => window.hcaptchaReady(15000)")
            print(f"  hcaptchaReady: {ready}")
            if not ready:
                print("  *** hCaptcha api.js FAILED TO LOAD ***")
                page.screenshot(path=os.path.join(OUTPUT_DIR, f"{label}_FAILED_hcaptcha_load.png"))
                # dump what requests we got
                hcap_reqs = [r for r in requests_log if "hcaptcha" in r["url"]]
                print(f"  hCaptcha requests so far: {len(hcap_reqs)}")
                for r in hcap_reqs:
                    print(f"    {r['method']} {r['url'][:90]}")
                hcap_fails = [r for r in failed_log if "hcaptcha" in r["url"]]
                print(f"  hCaptcha FAILED requests: {len(hcap_fails)}")
                for r in hcap_fails:
                    print(f"    {r['url'][:90]} => {r['failure']}")
                context.close()
                return

            # Render the widget
            render_result = page.evaluate("([k, r]) => window.initCaptcha(k, r)", [SITEKEY, ""])
            print(f"  initCaptcha result: {render_result}")

            page.screenshot(path=os.path.join(OUTPUT_DIR, f"{label}_02_after_render.png"))
            print(f"  Screenshot: {label}_02_after_render.png")

            # Wait and observe
            print(f"\n  Monitoring for 20 seconds...")
            for tick in range(20):
                time.sleep(1)

                token = page.evaluate("window.hcaptchaToken || null")
                err = page.evaluate("window.hcaptchaError || null")
                expired = page.evaluate("window.hcaptchaExpired || null")

                if err:
                    print(f"  [{tick+1}s] ERROR: {err}")
                    page.screenshot(path=os.path.join(OUTPUT_DIR, f"{label}_ERROR_{tick+1}s.png"))
                    break
                if token:
                    print(f"  [{tick+1}s] TOKEN RECEIVED! len={len(token)}")
                    break
                if expired:
                    print(f"  [{tick+1}s] EXPIRED")
                    break

                # At 3s, 10s, 15s take intermediate screenshots and frame dumps
                if tick + 1 in (3, 10, 15):
                    page.screenshot(path=os.path.join(OUTPUT_DIR, f"{label}_03_tick_{tick+1}s.png"))
                    print(f"  [{tick+1}s] Screenshot saved. Frames:")
                    for fi, frame in enumerate(page.frames):
                        print(f"    frame[{fi}]: url={frame.url[:90]} name={frame.name}")

                    # Check for challenge overlay iframe
                    challenge_iframes = [f for f in page.frames if "frame=challenge" in f.url]
                    if challenge_iframes:
                        print(f"  [{tick+1}s] Challenge iframe FOUND")
                        try:
                            loc = page.locator('iframe[title="hCaptcha challenge"]')
                            box = loc.bounding_box(timeout=1000)
                            vis = loc.is_visible()
                            print(f"    bounding_box={box}  visible={vis}")
                        except Exception as e:
                            print(f"    Could not get bbox: {e}")
                    else:
                        print(f"  [{tick+1}s] NO challenge iframe yet")

                    # Check for checkbox iframe
                    checkbox_iframes = [f for f in page.frames if "frame=checkbox" in f.url]
                    if checkbox_iframes:
                        print(f"  [{tick+1}s] Checkbox iframe FOUND")
                    else:
                        print(f"  [{tick+1}s] NO checkbox iframe")

            # Final screenshot
            page.screenshot(path=os.path.join(OUTPUT_DIR, f"{label}_FINAL.png"))

            # ---------- dump summary ----------
            print(f"\n  --- SUMMARY for {label} ---")
            hcap_responses = [r for r in responses_log if "hcaptcha.com" in r["url"]]
            print(f"  Total requests: {len(requests_log)}")
            print(f"  hCaptcha responses: {len(hcap_responses)}")
            for r in hcap_responses:
                print(f"    [{r['status']}] {r['url'][:100]}")
            hcap_fails = [r for r in failed_log if "hcaptcha" in r["url"]]
            print(f"  hCaptcha FAILED: {len(hcap_fails)}")
            for r in hcap_fails:
                print(f"    {r['url'][:100]} => {r['failure']}")
            print(f"  Final frames:")
            for fi, frame in enumerate(page.frames):
                print(f"    frame[{fi}]: {frame.url[:100]}")
            print(f"  hcaptchaToken: {page.evaluate('window.hcaptchaToken || null')}")
            print(f"  hcaptchaError: {page.evaluate('window.hcaptchaError || null')}")

            # Dump all console errors
            console_errors = [c for c in console_log if c["type"] in ("error", "warning")]
            if console_errors:
                print(f"  Console errors/warnings:")
                for c in console_errors:
                    print(f"    [{c['type']}] {c['text'][:150]}")

            # Write full request log to file
            log_path = os.path.join(OUTPUT_DIR, f"{label}_requests.json")
            with open(log_path, "w") as f:
                json.dump({"requests": requests_log, "responses": responses_log, "failed": failed_log, "console": console_log}, f, indent=2)
            print(f"  Full log: {log_path}")

            context.close()


if __name__ == "__main__":
    # Run DIRECT first, then PROXY
    run_debug("DIRECT", use_proxy=False)
    run_debug("PROXY", use_proxy=True)
    print(f"\n\nAll debug output in: {OUTPUT_DIR}")
    print("Compare screenshots side by side!")
