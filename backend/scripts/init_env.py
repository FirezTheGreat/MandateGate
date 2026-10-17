"""Create or repair the repo-root .env: copy .env.example if missing, then replace any
placeholder key with a fresh 32-byte hex secret. Existing real keys are left untouched.

    python backend/scripts/init_env.py      (stdlib only; run from the repo root)
"""

import re
import secrets
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
KEY_NAMES = ("MANDATE_KEY", "ROOT_KEY", "PASS_KEY")


def main() -> int:
    env, example = ROOT / ".env", ROOT / ".env.example"
    if not env.exists():
        shutil.copyfile(example, env)
        print("created .env from .env.example")
    text = env.read_text(encoding="utf-8")
    for name in KEY_NAMES:
        pattern = re.compile(rf"^{name}=(.*)$", re.MULTILINE)
        match = pattern.search(text)
        value = match.group(1).split("#", 1)[0].strip() if match else ""
        if value and not value.startswith("change-me") and len(value) >= 32:
            continue
        line = f"{name}={secrets.token_hex(32)}"
        text = pattern.sub(line, text) if match else text.rstrip("\n") + f"\n{line}\n"
        print(f"generated {name}")
    env.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
