from __future__ import annotations

import argparse
from pathlib import Path

from huggingface_hub import HfApi, SpaceHardware
from huggingface_hub.errors import HfHubHTTPError

from emotionos.app.core.config import get_settings


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Publish the compact EmotionOS Gradio Space.")
    parser.add_argument("--repo-id", default="", help="Space id, defaults to <current-user>/emotionos-inference.")
    parser.add_argument("--skip-hardware", action="store_true", help="Upload files without requesting ZeroGPU.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    settings = get_settings()
    token = settings.hf_token.strip()
    if not token:
        raise SystemExit("Set HF_TOKEN in .env before deploying the Space.")

    api = HfApi(token=token)
    account = api.whoami(token=token)
    namespace = str(account.get("name") or "").strip()
    if not namespace:
        raise SystemExit("Hugging Face did not return an account namespace.")
    repo_id = args.repo_id.strip() or f"{namespace}/emotionos-inference"
    source = Path("hf_space").resolve()

    try:
        api.create_repo(
            repo_id=repo_id,
            repo_type="space",
            space_sdk="gradio",
            space_hardware=SpaceHardware.ZERO_A10G,
            private=False,
            exist_ok=True,
            token=token,
        )
    except HfHubHTTPError as exc:
        if exc.response is not None and exc.response.status_code == 403:
            raise SystemExit(
                "HF_TOKEN can read the account but cannot create repositories. "
                "Create a fine-grained token with repository write access and retry."
            ) from exc
        if exc.response is not None and exc.response.status_code == 402:
            raise SystemExit(
                "Hugging Face refused Space compute for this account. "
                "Confirm ZeroGPU hosting eligibility or activate PRO, then retry."
            ) from exc
        raise
    api.upload_folder(
        repo_id=repo_id,
        repo_type="space",
        folder_path=source,
        ignore_patterns=["**/__pycache__/**", "**/*.pyc", "**/.DS_Store"],
        commit_message="Deploy EmotionOS ZeroGPU inference service",
        token=token,
    )
    print(f"Uploaded: https://huggingface.co/spaces/{repo_id}")

    if args.skip_hardware:
        return 0
    try:
        runtime = api.request_space_hardware(
            repo_id=repo_id,
            hardware=SpaceHardware.ZERO_A10G,
            token=token,
        )
        print(f"ZeroGPU requested: {runtime.stage}")
    except Exception as exc:
        print(f"Space uploaded, but ZeroGPU must be selected in Settings: {exc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
