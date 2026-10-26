import re


DEFAULT_CONTENT_BUDGET = 512
MIN_CONTENT_BUDGET = 64

SPLIT_PATTERN = re.compile(r"(?<=[.!?])\s+|\n+")
SPACE_PATTERN = re.compile(r"\s+")

NOISE_UNITS = {
    "ага",
    "да",
    "ок",
    "окей",
    "понял",
    "понятно",
    "привет",
    "спасибо",
    "хорошо",
    "hello",
    "hi",
    "ok",
    "okay",
    "thanks",
    "thank you",
}

SUPERSESSION_MARKERS = (
    "вместо",
    "заменили",
    "instead",
    "replaced",
)

PRIORITY_RULES = (
    (
        5,
        "decision",
        (
            "решили",
            "решение",
            "выбрали",
            "выбираем",
            "принято",
            "используем",
            "будем использовать",
            "decision",
            "decided",
            "selected",
            "choose",
            "chosen",
            "will use",
        ),
    ),
    (
        5,
        "outcome",
        (
            "результат",
            "получилось",
            "работает",
            "не работает",
            "прошел",
            "прошла",
            "прошли",
            "ошибка",
            "result",
            "outcome",
            "passed",
            "failed",
            "works",
            "does not work",
            "error",
        ),
    ),
    (
        5,
        "change",
        (
            "теперь",
            "раньше",
            "вместо",
            "изменили",
            "заменили",
            "changed",
            "previously",
            "instead",
            "replaced",
        ),
    ),
    (
        4,
        "constraint",
        (
            "огранич",
            "условие",
            "нельзя",
            "требуется",
            "должен",
            "должна",
            "constraint",
            "limitation",
            "must",
            "requires",
            "cannot",
        ),
    ),
    (
        4,
        "reason",
        (
            "потому что",
            "так как",
            "причина",
            "поэтому",
            "because",
            "reason",
            "therefore",
        ),
    ),
    (
        4,
        "question",
        (
            "открытый вопрос",
            "неясно",
            "нужно проверить",
            "неизвестно",
            "open question",
            "unclear",
            "unknown",
            "need to verify",
        ),
    ),
)


class RuleBasedComposer:
    """Deterministic size-bounded Memory.content composer."""

    def __init__(self, max_chars=DEFAULT_CONTENT_BUDGET):
        if (
            not isinstance(max_chars, int)
            or isinstance(max_chars, bool)
            or max_chars < MIN_CONTENT_BUDGET
        ):
            raise ValueError(
                f"Composer max_chars must be an integer >= {MIN_CONTENT_BUDGET}"
            )

        self.max_chars = max_chars

    def compose_create(self, text):
        return self._compose([], self._units(text, origin="new"))

    def compose_update(self, existing_content, new_text):
        existing = self._units(existing_content, origin="existing")
        new = self._units(new_text, origin="new")
        return self._compose(existing, new)

    def _compose(self, existing_units, new_units):
        units = self._revise(existing_units, new_units)
        meaningful = [unit for unit in units if not unit["noise"]]

        if meaningful:
            units = meaningful

        full_content = self._render(units)
        if len(full_content) <= self.max_chars:
            return self._result(
                full_content,
                kept=len(units),
                dropped=0,
                truncated=False,
                categories=units,
            )

        ranked = sorted(
            units,
            key=lambda unit: (
                unit["priority"],
                1 if unit["origin"] == "new" else 0,
                unit["index"],
            ),
            reverse=True,
        )

        selected = []
        for unit in ranked:
            candidate = selected + [unit]
            rendered = self._render(
                sorted(candidate, key=lambda item: item["index"])
            )
            if len(rendered) <= self.max_chars:
                selected.append(unit)

        if not selected:
            selected = [ranked[0]]
            content = self._truncate_unit(selected[0]["text"])
        else:
            selected.sort(key=lambda item: item["index"])
            content = self._render(selected)

        return self._result(
            content,
            kept=len(selected),
            dropped=len(units) - len(selected),
            truncated=True,
            categories=selected,
        )

    def _units(self, text, *, origin):
        if not isinstance(text, str) or not text.strip():
            raise ValueError("Composer input must be a non-empty string")

        cleaned = SPACE_PATTERN.sub(" ", text.strip())
        parts = [
            SPACE_PATTERN.sub(" ", part.strip())
            for part in SPLIT_PATTERN.split(cleaned)
            if part.strip()
        ]

        units = []
        for local_index, part in enumerate(parts):
            priority, category = self._priority(part)
            units.append(
                {
                    "text": part,
                    "origin": origin,
                    "local_index": local_index,
                    "priority": priority,
                    "category": category,
                    "noise": self._normalize(part) in NOISE_UNITS,
                }
            )

        return units

    def _revise(self, existing_units, new_units):
        result = []

        for unit in existing_units:
            self._append_unique(result, unit)

        for unit in new_units:
            key = self._normalize(unit["text"])

            if any(marker in key for marker in SUPERSESSION_MARKERS):
                result = [
                    current
                    for current in result
                    if not (
                        current["origin"] == "existing"
                        and current["category"] == "decision"
                    )
                ]

            replacement_indexes = []
            adds_information = True

            for index, current in enumerate(result):
                current_key = self._normalize(current["text"])

                if current_key == key:
                    adds_information = False
                    break

                if (
                    current["origin"] == "existing"
                    and len(current_key) >= 12
                    and current_key in key
                ):
                    replacement_indexes.append(index)
                    continue

                if (
                    current["origin"] == "existing"
                    and len(key) >= 12
                    and key in current_key
                ):
                    adds_information = False
                    break

            if not adds_information:
                continue

            for index in reversed(replacement_indexes):
                result.pop(index)

            self._append_unique(result, unit)

        for global_index, unit in enumerate(result):
            unit["index"] = global_index

        return result

    def _append_unique(self, result, unit):
        key = self._normalize(unit["text"])
        if any(self._normalize(item["text"]) == key for item in result):
            return
        result.append(dict(unit))

    @staticmethod
    def _normalize(text):
        return SPACE_PATTERN.sub(" ", text.strip()).casefold()

    @staticmethod
    def _render(units):
        return " ".join(unit["text"] for unit in units).strip()

    def _truncate_unit(self, text):
        if len(text) <= self.max_chars:
            return text
        return text[: self.max_chars - 1].rstrip() + "…"

    @classmethod
    def _priority(cls, text):
        normalized = cls._normalize(text)

        if text.rstrip().endswith("?"):
            return 4, "question"

        for priority, category, markers in PRIORITY_RULES:
            if any(marker in normalized for marker in markers):
                return priority, category

        return 1, "detail"

    def _result(
        self,
        content,
        *,
        kept,
        dropped,
        truncated,
        categories,
    ):
        if not content:
            raise ValueError("Composer produced empty content")
        if len(content) > self.max_chars:
            raise ValueError("Composer exceeded content budget")

        return {
            "content": content,
            "truncated": truncated,
            "kept_units": kept,
            "dropped_units": dropped,
            "max_chars": self.max_chars,
            "categories": [unit["category"] for unit in categories],
        }
