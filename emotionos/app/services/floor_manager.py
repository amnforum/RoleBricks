from __future__ import annotations

from dataclasses import dataclass

from emotionos.app.domain.scene_manifest import SceneCharacterDraft, SceneManifest


@dataclass(frozen=True)
class FloorDecision:
    character_key: str
    score: float
    reason: str


class FloorManager:
    """Deterministic floor ownership shared by every text and voice provider."""

    contradiction_markers = {"but", "however", "no", "not", "wrong", "false", "actually"}
    urgency_markers = {"now", "immediately", "urgent", "answer", "why", "how"}

    def choose(
        self,
        *,
        manifest: SceneManifest,
        user_text: str,
        turn_count: int,
        last_character_key: str | None,
        runtime_states: dict[str, dict],
    ) -> FloorDecision:
        cast = manifest.selected_characters
        if not cast:
            raise ValueError("A live scene requires at least one selected AI character")

        if len(cast) == 1:
            selected = cast[0]
            return FloorDecision(
                character_key=selected.key,
                score=100.0,
                reason="single_agent_lock",
            )

        words = {word.strip(".,!?;:").casefold() for word in user_text.split()}
        contradiction = len(words & self.contradiction_markers)
        urgency = len(words & self.urgency_markers)
        scored: list[tuple[float, SceneCharacterDraft, str]] = []
        for index, character in enumerate(cast):
            state = runtime_states.get(character.key) or {}
            patience = int(state.get("patience", character.patience))
            authority = int(state.get("authority", character.authority))
            score = authority * 0.42
            score += character.interruption_tendency * min(2, contradiction) * 0.08
            score += min(2, urgency) * 6
            score += max(0, 50 - patience) * 0.12
            score += 5 if index == turn_count % len(cast) else 0
            if len(cast) > 1 and character.key == last_character_key:
                score -= 12
            reason = (
                f"authority={authority}, patience={patience}, "
                f"contradiction={contradiction}, urgency={urgency}"
            )
            scored.append((score, character, reason))

        score, selected, reason = max(scored, key=lambda item: (item[0], item[1].key))
        return FloorDecision(character_key=selected.key, score=round(score, 2), reason=reason)

