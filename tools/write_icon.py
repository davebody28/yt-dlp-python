"""Utility to generate app.ico from embedded base64 icon data."""
from pathlib import Path
import base64
from icon_data import ICO_BASE64

OUTPUT = Path("app.ico")

if __name__ == "__main__":
    data = base64.b64decode(ICO_BASE64)
    OUTPUT.write_bytes(data)
    print(f"Wrote {OUTPUT}")
