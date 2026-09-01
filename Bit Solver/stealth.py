"""Fingerprint alignment helpers for the Playwright captcha solver.

The solver renders Discord's hCaptcha challenge in a Playwright Chromium
instance and is handed the *account session's* user-agent so the token it
produces looks like it came from the same browser that will submit it.

Playwright's `user_agent=` option only rewrites `navigator.userAgent` and the
`User-Agent` header. It does NOT rewrite:

  * `navigator.userAgentData.brands` / `fullVersionList`  (real engine version)
  * `navigator.userAgentData.platform`                    (real OS)
  * the `Sec-CH-UA*` client-hint request headers
  * `navigator.platform`, `navigator.oscpu`
  * `navigator.webdriver`                                 (automation flag)
  * WebGL vendor/renderer strings                         (real GPU/OS driver)

So a solver told "I am Chrome 152 on macOS" while actually running Chromium 149
on Linux advertises the contradiction to hCaptcha on every request. hCaptcha
still returns a token (the visual challenge was solved), which is why the solver
reports success -- but the token carries a bottom-tier risk score, and Discord's
enterprise verification rejects it and immediately issues a *fresh* challenge.
That is the "Secondary captcha challenge received" loop.

This module derives a self-consistent identity from the requested user-agent and
applies it via CDP + an init script, so every surface hCaptcha reads agrees.
"""

import re

# Modern Chrome 120-136+ GREASE brand format
_GREASE_BRAND = "Not)A;Brand"
_GREASE_VERSION = "24"
_NAV_PLATFORM = {"macOS": "MacIntel", "Windows": "Win32", "Linux": "Linux x86_64"}


def derive_dynamic_webgl_strings(platform="Windows", hw_profile=None):
    """Generate mathematically valid ANGLE WebGL vendor and renderer strings dynamically."""
    if not hw_profile:
        try:
            from utils.telemetry import generate_dynamic_hardware_profile
            hw_profile = generate_dynamic_hardware_profile(platform)
        except Exception:
            hw_profile = None

    if platform == "macOS":
        gpu_brand = hw_profile.get("gpu_brand", "Apple M2") if hw_profile else "Apple M2"
        return (
            "Google Inc. (Apple)",
            f"ANGLE (Apple, ANGLE Metal Renderer: {gpu_brand}, Unspecified Version)",
        )

    if platform == "Linux":
        gpu_brand = hw_profile.get("gpu_brand", "Mesa Intel(R) UHD Graphics 630 (CFL GT2)") if hw_profile else "Mesa Intel(R) UHD Graphics 630 (CFL GT2)"
        return (
            "Google Inc. (Mesa)",
            f"ANGLE (Mesa, {gpu_brand}, OpenGL 4.6)",
        )

    # Windows
    gpu_brand = hw_profile.get("gpu_brand", "NVIDIA GeForce RTX 3060") if hw_profile else "NVIDIA GeForce RTX 3060"
    dev_id = hw_profile.get("gpu_device_device_id", 9475) if hw_profile else 9475

    if "AMD" in gpu_brand or "Radeon" in gpu_brand:
        vendor = "Google Inc. (AMD)"
        renderer = f"ANGLE (AMD, {gpu_brand} (0x{dev_id:08X}) Direct3D11 vs_5_0 ps_5_0, D3D11)"
    elif "Intel" in gpu_brand or "Arc" in gpu_brand or "UHD" in gpu_brand:
        vendor = "Google Inc. (Intel)"
        renderer = f"ANGLE (Intel, {gpu_brand} (0x{dev_id:08X}) Direct3D11 vs_5_0 ps_5_0, D3D11)"
    else:
        vendor = "Google Inc. (NVIDIA)"
        renderer = f"ANGLE (NVIDIA, {gpu_brand} (0x{dev_id:08X}) Direct3D11 vs_5_0 ps_5_0, D3D11)"

    return vendor, renderer


def parse_user_agent(ua, platform_hint=None, platform_version_hint=None, hw_profile=None):
    """Derive a self-consistent browser identity from a Chrome user-agent string."""
    ua = ua or ""

    m = re.search(r"Chrome/(\d+)\.(\d+)\.(\d+)\.(\d+)", ua)
    if m:
        full_version = m.group(0).split("/", 1)[1]
        major = m.group(1)
    else:
        m2 = re.search(r"Chrome/(\d+)", ua)
        major = m2.group(1) if m2 else "131"
        full_version = f"{major}.0.0.0"

    if platform_hint:
        platform = platform_hint
    elif "Macintosh" in ua or "Mac OS X" in ua:
        platform = "macOS"
    elif "Windows" in ua:
        platform = "Windows"
    else:
        platform = "Linux"

    if platform_version_hint:
        platform_version = platform_version_hint
    elif platform == "macOS":
        mv = re.search(r"Mac OS X (\d+)[_.](\d+)(?:[_.](\d+))?", ua)
        if mv:
            platform_version = f"{mv.group(1)}.{mv.group(2)}.{mv.group(3) or '0'}"
        else:
            platform_version = "14.5.0"
    elif platform == "Windows":
        platform_version = "15.0.0"
    else:
        platform_version = "6.8.0"

    is_electron = "discord/" in ua.lower() or "electron/" in ua.lower()
    disc_m = re.search(r"discord/([\d.]+)", ua, re.IGNORECASE)
    disc_ver = disc_m.group(1) if disc_m else "1.0.9171"
    disc_major = disc_ver.split(".")[0] if disc_ver else "1"

    if is_electron:
        brands = [
            {"brand": _GREASE_BRAND, "version": _GREASE_VERSION},
            {"brand": "Discord", "version": disc_major},
            {"brand": "Chromium", "version": major},
        ]
        full_version_list = [
            {"brand": _GREASE_BRAND, "version": f"{_GREASE_VERSION}.0.0.0"},
            {"brand": "Discord", "version": disc_ver},
            {"brand": "Chromium", "version": full_version},
        ]
    else:
        brands = [
            {"brand": "Google Chrome", "version": major},
            {"brand": "Chromium", "version": major},
            {"brand": _GREASE_BRAND, "version": _GREASE_VERSION},
        ]
        full_version_list = [
            {"brand": "Google Chrome", "version": full_version},
            {"brand": "Chromium", "version": full_version},
            {"brand": _GREASE_BRAND, "version": f"{_GREASE_VERSION}.0.0.0"},
        ]

    sec_ch_ua = ", ".join(f'"{b["brand"]}";v="{b["version"]}"' for b in brands)

    concurrency = hw_profile.get("hardware_concurrency", 16) if hw_profile else 16
    device_mem = (hw_profile.get("system_memory_total", 16384) // 1024) if hw_profile else 16

    return {
        "user_agent": ua,
        "major": major,
        "full_version": full_version,
        "platform": platform,
        "platform_version": platform_version,
        "nav_platform": _NAV_PLATFORM.get(platform, "Win32"),
        "brands": brands,
        "full_version_list": full_version_list,
        "sec_ch_ua": sec_ch_ua,
        "sec_ch_ua_platform": f'"{platform}"',
        "webgl": derive_dynamic_webgl_strings(platform, hw_profile),
        "hardware_concurrency": concurrency,
        "device_memory": device_mem,
    }


def generate_dynamic_profile(platform_hint=None, proxy=None):
    """Generate an authentic, complete browser profile dynamically using live hardware and version APIs."""
    import random

    if platform_hint in ("Windows", "macOS", "Linux"):
        platform = platform_hint
    else:
        platform = random.choices(["Windows", "macOS", "Linux"], weights=[70, 20, 10])[0]

    plat_key = "win" if platform == "Windows" else ("mac" if platform == "macOS" else "linux")

    # 1. Dynamically fetch or synthesize Chrome version from Google's live API
    chrome_version = None
    try:
        from utils.build import _get_official_chrome_ver
        chrome_version = _get_official_chrome_ver(plat_key)
    except Exception:
        pass

    if not chrome_version:
        fallback_versions = [
            "136.0.7103.48",
            "135.0.7049.96",
            "134.0.6998.88",
            "133.0.6943.142",
            "132.0.6834.196",
            "131.0.6778.265",
        ]
        chrome_version = random.choice(fallback_versions)

    # 2. Dynamically fetch or synthesize GPU/RAM/CPU hardware profile
    hw_profile = None
    try:
        from utils.telemetry import generate_dynamic_hardware_profile
        hw_profile = generate_dynamic_hardware_profile(platform)
    except Exception:
        pass

    if hw_profile:
        concurrency = hw_profile.get("hardware_concurrency", 16)
        device_mem = max(8, hw_profile.get("system_memory_total", 16384) // 1024)
    else:
        concurrency = random.choice([8, 12, 16, 24, 32])
        device_mem = random.choice([8, 16, 32])
        hw_profile = {
            "hardware_concurrency": concurrency,
            "system_memory_total": device_mem * 1024,
        }

    # 3. Dynamically construct User-Agent and Platform Version
    if platform == "macOS":
        ua = f"Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{chrome_version} Safari/537.36"
        platform_version = random.choice(["15.3.1", "15.2.0", "14.7.2", "14.5.0"])
    elif platform == "Linux":
        ua = f"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{chrome_version} Safari/537.36"
        platform_version = random.choice(["6.12.10", "6.8.0", "6.6.75"])
    else:
        ua = f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{chrome_version} Safari/537.36"
        platform_version = "15.0.0"

    ident = parse_user_agent(
        ua,
        platform_hint=platform,
        platform_version_hint=platform_version,
        hw_profile=hw_profile,
    )

    # 4. Dynamically detect timezone from proxy or pick natural geographic timezone
    tz = None
    if proxy:
        try:
            from utils.proxy import detect_timezone
            tz = detect_timezone(proxy, user_agent=ua)
        except Exception:
            pass

    if not tz:
        fallback_tzs = [
            "America/New_York",
            "America/Chicago",
            "America/Los_Angeles",
            "America/Denver",
            "America/Toronto",
            "Europe/London",
            "Europe/Berlin",
        ]
        tz = random.choice(fallback_tzs)

    return {
        "user_agent": ua,
        "platform": platform,
        "platform_version": platform_version,
        "timezone": tz,
        "locale": "en-US",
        "hardware_concurrency": concurrency,
        "device_memory": device_mem,
        "hw_profile": hw_profile,
        "ident": ident,
    }


def apply_user_agent_override(context, page, ident, locale="en-US"):
    """Align client hints + navigator.platform with the requested user-agent."""
    cdp = context.new_cdp_session(page)
    cdp.send(
        "Emulation.setUserAgentOverride",
        {
            "userAgent": ident["user_agent"],
            "acceptLanguage": f"{locale},{locale.split('-')[0]};q=0.9",
            "platform": ident["nav_platform"],
            "userAgentMetadata": {
                "brands": ident["brands"],
                "fullVersionList": ident["full_version_list"],
                "fullVersion": ident["full_version"],
                "platform": ident["platform"],
                "platformVersion": ident["platform_version"],
                "architecture": "x86",
                "model": "",
                "mobile": False,
                "bitness": "64",
                "wow64": False,
            },
        },
    )
    return cdp


def build_init_script(ident, locale="en-US"):
    """JS patches for the surfaces CDP cannot reach with full native function toString masking."""
    vendor, renderer = ident["webgl"]
    concurrency = ident.get("hardware_concurrency", 16)
    device_mem = ident.get("device_memory", 16)
    oscpu = {
        "macOS": "Intel Mac OS X 10_15_7",
        "Windows": "Windows NT 10.0; Win64; x64",
        "Linux": "Linux x86_64",
    }.get(ident["platform"], "Windows NT 10.0; Win64; x64")

    return """
(() => {
  const NAV_PLATFORM = %(nav_platform)s;
  const OSCPU = %(oscpu)s;
  const LOCALE = %(locale)s;
  const GL_VENDOR = %(gl_vendor)s;
  const GL_RENDERER = %(gl_renderer)s;
  const HW_CONCURRENCY = %(concurrency)s;
  const DEV_MEMORY = %(device_mem)s;

  // Native function toString masking system
  const customToStringMap = new WeakMap();
  const nativeToString = Function.prototype.toString;

  function makeNative(fn, name) {
    customToStringMap.set(fn, 'function ' + name + '() { [native code] }');
    return fn;
  }

  try {
    Function.prototype.toString = function () {
      if (customToStringMap.has(this)) {
        return customToStringMap.get(this);
      }
      return nativeToString.apply(this, arguments);
    };
    customToStringMap.set(Function.prototype.toString, 'function toString() { [native code] }');
  } catch (e) {}

  const define = (obj, prop, value) => {
    try {
      Object.defineProperty(obj, prop, { get: makeNative(() => value, 'get ' + prop), configurable: true });
    } catch (e) {}
  };

  // Clean webdriver removal (AutomationControlled flag handles C++ level; remove JS leaks if any)
  try {
    if ('webdriver' in navigator && navigator.webdriver) {
      delete Object.getPrototypeOf(navigator).webdriver;
    }
  } catch (e) {}

  // Define properties on Navigator.prototype so navigator.hasOwnProperty(...) returns false (inherited prototype behavior)
  const targetProto = (typeof Navigator !== 'undefined' && Navigator.prototype) || navigator;

  define(targetProto, 'platform', NAV_PLATFORM);
  define(targetProto, 'oscpu', OSCPU);
  define(targetProto, 'language', LOCALE);
  define(targetProto, 'languages', Object.freeze([LOCALE, LOCALE.split('-')[0]]));
  define(targetProto, 'maxTouchPoints', 0);
  define(targetProto, 'hardwareConcurrency', HW_CONCURRENCY);
  define(targetProto, 'deviceMemory', DEV_MEMORY);

  // Headful Chromium exposes window.chrome
  if (!window.chrome) { window.chrome = {}; }
  if (!window.chrome.runtime) { window.chrome.runtime = {}; }

  // WebGL vendor/renderer spoofing with native getParameter toString masking
  const UNMASKED_VENDOR = 37445;
  const UNMASKED_RENDERER = 37446;
  for (const proto of [window.WebGLRenderingContext, window.WebGL2RenderingContext]) {
    if (!proto) continue;
    const originalGetParam = proto.prototype.getParameter;
    const patchedGetParam = function (parameter) {
      if (parameter === UNMASKED_VENDOR) return GL_VENDOR;
      if (parameter === UNMASKED_RENDERER) return GL_RENDERER;
      return originalGetParam.apply(this, arguments);
    };
    proto.prototype.getParameter = makeNative(patchedGetParam, 'getParameter');
  }
})();
""" % {
        "nav_platform": _js(ident["nav_platform"]),
        "oscpu": _js(oscpu),
        "locale": _js(locale),
        "gl_vendor": _js(vendor),
        "gl_renderer": _js(renderer),
        "concurrency": concurrency,
        "device_mem": device_mem,
    }


def _js(value):
    """Serialize a Python string as a JS string literal (proper escaping)."""
    import json

    return json.dumps(value)


def stealth_launch_args():
    """Chromium flags that remove automation tells from the browser itself while keeping it non-intrusive."""
    return [
        # Drops the `--enable-automation` blink feature that sets
        # navigator.webdriver and disables some Chrome behaviours.
        "--disable-blink-features=AutomationControlled",
        "--disable-features=IsolateOrigins,site-per-process,Translate",
        "--disable-infobars",
        "--no-default-browser-check",
        "--no-first-run",
        "--password-store=basic",
        "--use-mock-keychain",
        # Keep headful browser active at valid on-screen viewport coordinates
        "--window-position=50,50",
        "--window-size=1280,800",
        "--no-focus-on-map",
        "--disable-backgrounding-occluded-windows",
        "--disable-renderer-backgrounding",
        "--disable-background-timer-throttling",
        "--silent-debugger-extension-api",
        # Enable fake media devices so Discord has real audio input/output and doesn't force-mute
        "--use-fake-ui-for-media-stream",
        "--use-fake-device-for-media-stream",
    ]

