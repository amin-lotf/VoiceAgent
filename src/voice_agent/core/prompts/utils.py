

def _enum_values(enum_cls) -> str:
    return ", ".join(e.value for e in enum_cls)