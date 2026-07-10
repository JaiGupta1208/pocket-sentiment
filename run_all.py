"""Run the whole pipeline end to end: collect -> classify.
Usage: python run_all.py
Each collector is independent; a failure in one doesn't stop the others."""
import importlib
import store
import classify

COLLECTORS = ["collectors.appstore", "collectors.play", "collectors.reddit",
              "collectors.youtube", "collectors.mock_sources"]


def main():
    conn = store.connect()
    for mod_name in COLLECTORS:
        try:
            mod = importlib.import_module(mod_name)
            rows = mod.fetch() if hasattr(mod, "fetch") else []
            if isinstance(rows, tuple):  # youtube returns (rows, titles)
                rows = rows[0]
            n = store.upsert(conn, rows)
            print(f"{mod_name}: +{n} new ({len(rows)} fetched)")
        except Exception as e:
            print(f"{mod_name}: FAILED — {e}")
    classify.run(only_unclassified=True)


if __name__ == "__main__":
    main()
