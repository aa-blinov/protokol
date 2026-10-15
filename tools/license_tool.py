#!/usr/bin/env python3
"""Vendor-side licence tool: makes the signing key and issues licence files.

The signing key never goes into the repository. It is a 32-byte seed kept in a
file with owner-only permissions, by default in ~/.config/protokol/. Lose it and
no licence can be issued again, so keep a copy somewhere safe.

  python3 tools/license_tool.py keygen
  python3 tools/license_tool.py public
  python3 tools/license_tool.py issue --customer "ООО Ромашка" --edition team \\
      --seats 25 --expires 2027-10-14 --out romashka.license.json

keygen prints the public key; put it in api/licensing.py as PUBLIC_KEY_HEX.
The app checks only the signature, so a licence file can be handed to the
customer as it is. Standard library only, plus the app's own api/ed25519.py.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))

import ed25519  # noqa: E402

DEFAULT_KEY = Path.home() / ".config" / "protokol" / "license-signing.key"
EDITIONS = ("personal", "team", "enterprise")


def _read_seed(path: Path) -> bytes:
    if not path.is_file():
        raise SystemExit(f"Нет ключа подписи: {path}. Сначала запустите keygen.")
    seed = bytes.fromhex(path.read_text(encoding="utf-8").strip())
    if len(seed) != 32:
        raise SystemExit("Ключ подписи повреждён: нужно 32 байта.")
    return seed


def keygen(args: argparse.Namespace) -> int:
    path = Path(args.key)
    if path.exists() and not args.force:
        raise SystemExit(
            f"{path} уже есть. Не перезаписываем: потеря ключа закроет выдачу лицензий. "
            "--force только сознательно."
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    seed = os.urandom(32)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(seed.hex() + "\n")
    os.chmod(path, 0o600)
    print(f"Ключ создан: {path} (права 0600). Сохраните копию в надёжном месте.")
    print("Открытый ключ для api/licensing.py (PUBLIC_KEY_HEX):")
    print(ed25519.public_key(seed).hex())
    return 0


def public(args: argparse.Namespace) -> int:
    print(ed25519.public_key(_read_seed(Path(args.key))).hex())
    return 0


def issue(args: argparse.Namespace) -> int:
    seed = _read_seed(Path(args.key))
    if args.edition not in EDITIONS:
        raise SystemExit(f"Издание: одно из {', '.join(EDITIONS)}.")
    if args.seats < 1:
        raise SystemExit("Число мест: не меньше 1.")
    expires = None
    if args.expires:
        try:
            expires = dt.date.fromisoformat(args.expires).isoformat()
        except ValueError as error:
            raise SystemExit("Срок: дата в формате ГГГГ-ММ-ДД.") from error
    payload = {
        "customer": args.customer.strip(),
        "edition": args.edition,
        "seats": args.seats,
        "issued": dt.date.today().isoformat(),
        "expires": expires,
    }
    payload_text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    signature = ed25519.sign(seed, payload_text.encode("utf-8")).hex()
    document = {"payload": payload_text, "signature": signature}
    Path(args.out).write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Лицензия записана: {args.out}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)

    key_option = {"default": str(DEFAULT_KEY), "help": "файл с закрытым ключом"}
    keys = commands.add_parser("keygen", help="создать ключ подписи и показать открытый")
    keys.add_argument("--key", **key_option)
    keys.add_argument("--force", action="store_true")
    keys.set_defaults(run=keygen)

    public_key = commands.add_parser("public", help="показать открытый ключ")
    public_key.add_argument("--key", **key_option)
    public_key.set_defaults(run=public)

    make = commands.add_parser("issue", help="выдать лицензию")
    make.add_argument("--key", **key_option)
    make.add_argument("--customer", required=True)
    make.add_argument("--edition", required=True, choices=EDITIONS)
    make.add_argument("--seats", type=int, required=True)
    make.add_argument("--expires", default="", help="ГГГГ-ММ-ДД; пусто — бессрочно")
    make.add_argument("--out", required=True)
    make.set_defaults(run=issue)

    args = parser.parse_args()
    return args.run(args)


if __name__ == "__main__":
    raise SystemExit(main())
