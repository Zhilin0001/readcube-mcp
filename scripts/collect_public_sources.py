"""Download only JS chunk URLs explicitly referenced by the public app entry/chunks."""

import concurrent.futures
import hashlib
import json
import pathlib
import re
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "research/sources"


def fetch(name):
    path = OUT / name
    if not path.exists():
        with urllib.request.urlopen("https://app.readcube.com/" + name, timeout=45) as response:
            path.write_bytes(response.read())
    return name, path.read_text()


def main():
    seen = set()
    todo = {"main-UTNWQQUS.js"}
    while todo:
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(fetch, sorted(todo)))
        seen |= todo
        todo = set()
        for name, body in results:
            todo |= set(re.findall(r"chunk-[A-Z0-9]+\.js", body)) - seen
        print("downloaded", len(seen), "pending", len(todo), flush=True)
    manifest = [
        {
            "url": "https://app.readcube.com/" + name,
            "sha256": hashlib.sha256((OUT / name).read_bytes()).hexdigest(),
            "bytes": (OUT / name).stat().st_size,
        }
        for name in sorted(seen)
    ]
    (ROOT / "research/public-assets.json").write_text(json.dumps(manifest, indent=2) + "\n")


if __name__ == "__main__":
    main()
