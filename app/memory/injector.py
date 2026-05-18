def build_hint_block(hints: list[str]) -> str:
    if not hints:
        return ""
    numbered = "\n".join(f"{i+1}. {h}" for i, h in enumerate(hints))
    return f"\nLearned strategies (apply when relevant — still verify with real data):\n{numbered}\n"
