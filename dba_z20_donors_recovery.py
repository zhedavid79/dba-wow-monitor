from __future__ import annotations

import asyncio
import re

import dba_z20_donors as donors

# Tight motherboard-form-factor context. A PSU phrase such as
# "ATX strømforsyning ... motherboard unknown" must not be interpreted as
# evidence that the motherboard itself is ATX.
STRICT_ATX_BOARD_CONTEXT = re.compile(
    r"\b(?:atx|e[- ]?atx|extended[- ]?atx)\b\s*(?:form\s*factor\s*)?\b(?:bundkort|motherboard|mainboard)\b|"
    r"\b(?:bundkort|motherboard|mainboard)\b\s*(?:form\s*factor\s*)?\b(?:atx|e[- ]?atx|extended[- ]?atx)\b",
    re.I,
)


def strict_motherboard_evidence(text: str) -> tuple[str, str | None]:
    model = donors.BOARD_MODEL.search(text)
    model_text = re.sub(r"\s+", " ", model.group(0)).strip() if model else None
    if donors.ITX.search(text):
        return "COMPATIBLE", model_text
    if donors.MATX.search(text):
        return "COMPATIBLE", model_text
    if donors.KNOWN_FULL_ATX_BOARD.search(text) or STRICT_ATX_BOARD_CONTEXT.search(text):
        return "INCOMPATIBLE", model_text
    return "UNVERIFIED", model_text


# Keep all donor selection, T1 retrieval, output and publication semantics unchanged.
donors.motherboard_evidence = strict_motherboard_evidence


if __name__ == "__main__":
    asyncio.run(donors.main())
