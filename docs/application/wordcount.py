"""Print word counts per section of docs/application/snorkel.md (Artifact counts the
VintageBench paragraph only; the ANLP-ESG alternative is counted separately)."""

import re
from pathlib import Path

TEXT = (Path(__file__).parent / "snorkel.md").read_text()


def sections() -> dict[str, str]:
    parts = re.split(r"^## (.+)$", TEXT, flags=re.M)
    return {parts[i].strip(): parts[i + 1] for i in range(1, len(parts), 2)}


def words(s: str) -> int:
    s = re.sub(r"[*#`]", " ", s)
    return len(re.findall(r"[A-Za-z0-9$][^\s]*", s))


if __name__ == "__main__":
    for name, body in sections().items():
        if name == "Artifact":
            main, alt = body.split("Alternative version:")
            print(f"Artifact (VintageBench version): {words(main)}")
            print(f"Artifact (ANLP-ESG alternative): {words('Alternative version:' + alt)}")
        else:
            print(f"{name}: {words(body)}")
