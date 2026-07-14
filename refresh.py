"""One-click refresh: pull new mentions, judge relevance, tag sentiment, rebuild weekly pulse.

Called by the dashboard's Refresh button (and usable from the CLI: python refresh.py).
Each step is isolated — one source failing doesn't stop the rest. Designed to run daily;
on the hosted snapshot it works when API keys are configured, and reports exactly what
it did either way.
"""
import os
import sys
import importlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import store


def run_refresh(log=print):
    """Runs the pipeline for NEW data only. Returns a list of (step, ok, detail)."""
    results = []
    conn = store.connect()

    # 1) collect — sources that work headless (Reddit needs the browser export, see collectors/reddit.py)
    for mod_name, label in [("collectors.appstore", "App Store"),
                            ("collectors.play", "Google Play"),
                            ("collectors.youtube", "YouTube")]:
        try:
            mod = importlib.import_module(mod_name)
            rows = mod.fetch()
            if isinstance(rows, tuple):
                rows = rows[0]
            n = store.upsert(conn, rows)
            results.append((f"Collect {label}", True, f"{n} new"))
            log(f"collect {label}: +{n}")
        except Exception as e:
            results.append((f"Collect {label}", False, str(e)[:120]))
            log(f"collect {label} FAILED: {e}")
    results.append(("Collect Reddit", False, "needs the browser-session export (blocked from servers)"))

    # 2) relevance for new rows
    try:
        import relevance
        relevance.run(only_new=True)
        results.append(("Relevance check (new rows)", True, "done"))
    except Exception as e:
        results.append(("Relevance check", False, str(e)[:120]))

    # 3) classify new rows
    try:
        import classify
        classify.run(only_unclassified=True)
        results.append(("Sentiment & themes (new rows)", True, "done"))
    except Exception as e:
        results.append(("Sentiment & themes", False, str(e)[:120]))

    # 4) weekly pulse
    try:
        import gen_weekly
        gen_weekly.run()
        results.append(("Weekly pulse", True, "updated"))
    except Exception as e:
        results.append(("Weekly pulse", False, str(e)[:120]))

    return results


if __name__ == "__main__":
    for step, ok, detail in run_refresh():
        print(f"{'OK ' if ok else 'ERR'} {step}: {detail}")
