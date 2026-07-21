import subprocess, json, os, sys, time
from concurrent.futures import ThreadPoolExecutor, as_completed

BASE = "https://ddinter2.scbdd.com/server/inter-list/{}/"
MECH = json.load(open("out/ddi_mechanisms.json"))
GIDS = [g["group_id"] for g in MECH["groups"]]
CKPT = "out/pairs.jsonl"
LOG = "out/enrich.log"

done = set()
if os.path.exists(CKPT):
    for line in open(CKPT):
        try:
            done.add(json.loads(line)["gid"])
        except Exception:
            pass

def log(m):
    with open(LOG, "a") as f:
        f.write(m + "\n")

def fetch(gid):
    for attempt in range(4):
        try:
            out = subprocess.run(
                ["curl", "-s", "--max-time", "60", "-X", "POST", BASE.format(gid),
                 "-H", "X-Requested-With: XMLHttpRequest",
                 "--data", "draw=1&start=0&length=200000"],
                capture_output=True, text=True).stdout
            d = json.loads(out)
            pairs = [{
                "a": r["internalID_a"], "an": r["drug_a_name"], "adb": r.get("drugbankID_a"),
                "b": r["internalID_b"], "bn": r["drug_b_name"], "bdb": r.get("drugbankID_b"),
            } for r in d.get("data", [])]
            return gid, pairs, None
        except Exception as e:
            time.sleep(0.5 * (attempt + 1))
            last = str(e)
    return gid, None, last

todo = [g for g in GIDS if g not in done]
log(f"start: {len(todo)} groups to fetch ({len(done)} already done)")
n = 0
fh = open(CKPT, "a")
with ThreadPoolExecutor(max_workers=10) as ex:
    futs = {ex.submit(fetch, g): g for g in todo}
    for fut in as_completed(futs):
        gid, pairs, err = fut.result()
        if err is not None:
            log(f"FAIL gid={gid}: {err}")
            continue
        fh.write(json.dumps({"gid": gid, "pairs": pairs}) + "\n")
        n += 1
        if n % 500 == 0:
            fh.flush()
            log(f"progress: {n}/{len(todo)}")
fh.flush(); fh.close()
log(f"DONE fetching. records written this run: {n}")
print("FETCH_COMPLETE", n)
