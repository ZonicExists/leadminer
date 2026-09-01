import os
import sys
import json
import subprocess

def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    root_dir   = os.path.dirname(script_dir)

    # Add root to sys.path so utils.license is importable
    if root_dir not in sys.path:
        sys.path.insert(0, root_dir)

    # ── License Gate ─────────────────────────────────────────────
    print("\n🔐 Bit Solver — License Check")
    try:
        from utils.license import ensure_solver_license

        # Load Bit Solver config for saved license key
        solver_config_path = os.path.join(script_dir, "config.json")
        solver_cfg = {}
        try:
            with open(solver_config_path, "r", encoding="utf-8") as f:
                solver_cfg = json.load(f)
        except Exception:
            pass

        ensure_solver_license(solver_cfg)

    except SystemExit:
        raise
    except Exception as e:
        print(f"[!] License check failed with unexpected error: {e}")
        sys.exit(1)
    # ─────────────────────────────────────────────────────────────

    server_script = os.path.join(script_dir, "server.py")
    python_bin    = sys.executable

    print(f"\n[+] Launching Bit Solver Playwright API service...")
    proc = subprocess.Popen([python_bin, "-u", server_script])
    print(f"[+] Bit Solver Service PID: {proc.pid}")
    try:
        proc.wait()
    except KeyboardInterrupt:
        print("\n[*] Stopping Bit Solver Service...")
        proc.terminate()

if __name__ == "__main__":
    main()
