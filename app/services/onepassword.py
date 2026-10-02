from __future__ import annotations

import shutil
import subprocess


class OnePasswordError(RuntimeError):
    pass


def validate_op_ref(ref: str) -> str:
    ref = (ref or "").strip()
    if not ref.startswith("op://"):
        raise ValueError("1Password references must start with op://")
    return ref


def read_secret(ref: str, *, timeout: int = 60) -> str:
    ref = validate_op_ref(ref)
    if shutil.which("op") is None:
        raise OnePasswordError("1Password CLI `op` is not installed or not on PATH")

    try:
        result = subprocess.run(
            ["op", "read", ref],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise OnePasswordError("Timed out waiting for 1Password CLI") from exc

    if result.returncode != 0:
        stderr = (result.stderr or "").strip()
        raise OnePasswordError(stderr or "1Password CLI could not read the requested reference")

    value = result.stdout.rstrip("\n")
    if not value:
        raise OnePasswordError("1Password returned an empty value")
    return value
