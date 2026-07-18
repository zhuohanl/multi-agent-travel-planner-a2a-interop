from pathlib import Path


PROMPT_ROOT = Path(__file__).parent / "prompts"


def load_prompt(name: str) -> str:
    path = PROMPT_ROOT / f"{name}.txt"
    prompt = path.read_text(encoding="utf-8").strip()
    if not prompt:
        raise RuntimeError(f"Prompt is empty: {path}")
    return prompt
