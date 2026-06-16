"""Smoke-test the AI image reader on a local image.

  ANTHROPIC_API_KEY=sk-ant-... python scripts/test_vision.py path/to/bol.jpg

Prints the structured extraction (doc type, gallons, BOL/Veeder discrepancy,
needs_review). Use this to validate vision before wiring it into ingest.
"""
import mimetypes
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import vision


def main():
    if len(sys.argv) < 2:
        print(__doc__); sys.exit(1)
    if not vision.enabled():
        print("ANTHROPIC_API_KEY not set — export it first."); sys.exit(1)
    path = sys.argv[1]
    media_type = mimetypes.guess_type(path)[0] or "image/jpeg"
    with open(path, "rb") as f:
        data = vision.analyze_image(f.read(), media_type=media_type,
                                    context=" ".join(sys.argv[2:]))
    import json
    print(json.dumps(data, indent=2))


if __name__ == "__main__":
    main()
