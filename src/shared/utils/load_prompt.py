from pathlib import Path

def load_prompt(prompt_name: str) -> str:
    """Load prompt content from a file."""
    prompt_path = Path(__file__).parent.parent.parent / "prompts" / f"{prompt_name}.txt"
    try:
        loaded = prompt_path.read_text(encoding="utf-8").strip()
        return loaded
    except FileNotFoundError:
        raise FileNotFoundError(f"Prompt file not found: {prompt_path}")
    

if __name__ == "__main__":
    loaded = load_prompt("clarifier")
    print(loaded)