


def _enum_values(enum_cls) -> str:
    return ", ".join(e.value for e in enum_cls)

def extend_prompt_section(rules: list[str], title: str, items: list[str]) -> None:
    if not items:
        return
    rules.append(f"[{title}]")
    rules.extend(items)