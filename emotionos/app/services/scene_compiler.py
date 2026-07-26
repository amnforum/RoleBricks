from __future__ import annotations

import json
import re
from typing import Any, Protocol

from emotionos.app.core.config import Settings
from emotionos.app.domain.scene_manifest import (
    CharacterAction,
    PreparedCharacter,
    PreparedScene,
    SceneCharacterDraft,
    SceneManifest,
    SceneSpeechProfile,
    SceneUserRole,
    SceneVoiceProfile,
)
from emotionos.app.providers.databricks_provider import DatabricksFoundationModelClient


class SceneCompiler(Protocol):
    provider_name: str

    async def compile(self, prompt: str, *, locale: str) -> tuple[SceneManifest, dict[str, int]]: ...

    async def prepare(
        self,
        manifest: SceneManifest,
        *,
        research_packet: dict[str, Any],
    ) -> tuple[PreparedScene, dict[str, int]]: ...

    async def decide(
        self,
        *,
        manifest: SceneManifest,
        character: SceneCharacterDraft,
        runtime_state: dict[str, Any],
        recent_turns: list[dict[str, Any]],
        memories: list[dict[str, Any]],
        sources: list[dict[str, Any]],
    ) -> tuple[CharacterAction, dict[str, int]]: ...


class DatabricksSceneCompiler:
    provider_name = "databricks"

    def __init__(self, settings: Settings) -> None:
        self.client = DatabricksFoundationModelClient(settings)

    async def compile(self, prompt: str, *, locale: str) -> tuple[SceneManifest, dict[str, int]]:
        schema = json.dumps(SceneManifest.model_json_schema(), separators=(",", ":"))
        system = (
            "You are the EmotionOS Scene Compiler. Convert any requested real, fictional, educational, social, "
            "professional, or unexpected situation into an editable Scene Manifest. Do not assume a courtroom, "
            "interview, or any other fixed genre. Infer the user's role and objective. Create every useful AI role "
            "as a separate candidate, up to eight candidates. Mark at most three as selected. If more than three "
            "would help, keep the additional candidates with selected=false and explain why, so the user chooses; "
            "never silently merge or remove roles. Public and private knowledge must be role-appropriate. Keep "
            "language, region, accent, dialect, and code-mixing independent. Mark every real public person as "
            "identity_kind=public_figure, require a visible portrayal_notice, and always use a distinct synthetic "
            "voice. Never request, imply, or promise voice imitation. Set metadata.reuse_key to a stable, short key "
            "for the selected counterpart, language, and scene type. Use only supportive, realistic, or "
            "high_pressure for pressure. "
            "Return JSON only and satisfy this JSON Schema exactly:\n"
            f"{schema}"
        )
        data, usage = await self.client.generate_json(
            system_prompt=system,
            user_prompt=f"User locale: {locale}\nScenario request:\n{prompt}",
            max_tokens=3600,
        )
        data["version"] = 1
        return SceneManifest.model_validate(data), usage

    async def prepare(
        self,
        manifest: SceneManifest,
        *,
        research_packet: dict[str, Any],
    ) -> tuple[PreparedScene, dict[str, int]]:
        schema = json.dumps(PreparedScene.model_json_schema(), separators=(",", ":"))
        system = (
            "Prepare only the selected characters in the confirmed Scene Manifest. Build one scene-specific "
            "Persona per selected character. Separate stable facts from current facts, retain uncertainty, avoid "
            "inventing facts absent from the research packet, and extract broad conversational mannerisms without "
            "copying quotations, catchphrases, or a real person's vocal identity. Opening lines must begin the "
            "requested situation naturally in one or two short sentences. For Hinglish, write Hindi words in "
            "Devanagari and English words in Latin script so the speech engine pronounces both naturally. Return JSON "
            "only and satisfy this JSON Schema exactly:\n"
            f"{schema}"
        )
        payload = {
            "manifest": manifest.model_dump(mode="json"),
            "research_packet": research_packet,
        }
        data, usage = await self.client.generate_json(
            system_prompt=system,
            user_prompt=json.dumps(payload, ensure_ascii=False),
            max_tokens=3600,
        )
        prepared = PreparedScene.model_validate(data)
        expected = {character.key for character in manifest.selected_characters}
        actual = {character.key for character in prepared.characters}
        if expected != actual:
            raise ValueError("Prepared character keys do not match the confirmed cast")
        return prepared, usage

    async def decide(
        self,
        *,
        manifest: SceneManifest,
        character: SceneCharacterDraft,
        runtime_state: dict[str, Any],
        recent_turns: list[dict[str, Any]],
        memories: list[dict[str, Any]],
        sources: list[dict[str, Any]],
    ) -> tuple[CharacterAction, dict[str, int]]:
        schema = json.dumps(CharacterAction.model_json_schema(), separators=(",", ":"))
        system = (
            "You are the action policy and voice of one living character inside an active EmotionOS scene. "
            "First choose exactly one action based on role, objective, authority, patience, mood, relationship, "
            "contradictions, scene pressure, private knowledge, and relevant memory. Then write only what that "
            "character would actually say. Be direct or confrontational when the scene requires it, but never use "
            "random abuse. Do not leak private knowledge unless the chosen strategy reveals it. Cite only supplied "
            "source IDs. Follow the character's exact language, accent, dialect, and code-mixing profile. Keep the "
            "spoken response to one to three short conversational sentences, allow interruption only at a phrase "
            "boundary, and avoid formal assistant language. For Hinglish, write Hindi words in Devanagari and English "
            "words in Latin script. A public figure is always a clearly labelled public-information simulation: "
            "never claim to be the real person, copy catchphrases, or imitate their voice. Return JSON only and "
            "satisfy this JSON Schema exactly:\n"
            f"{schema}"
        )
        payload = {
            "scene": {
                "title": manifest.title,
                "setting": manifest.setting,
                "stakes": manifest.stakes,
                "objective": manifest.objective,
                "pressure": manifest.pressure,
                "user_role": manifest.user_role.model_dump(mode="json"),
            },
            "character": character.model_dump(mode="json"),
            "runtime_state": runtime_state,
            "recent_turns": recent_turns[-12:],
            "relevant_memories": memories[:8],
            "available_sources": sources[:10],
        }
        data, usage = await self.client.generate_json(
            system_prompt=system,
            user_prompt=json.dumps(payload, ensure_ascii=False),
            max_tokens=700,
        )
        data["character_key"] = character.key
        return CharacterAction.model_validate(data), usage


class RuleBasedSceneCompiler:
    """Deterministic compiler for tests and explicitly selected local development."""

    provider_name = "rules"

    async def compile(self, prompt: str, *, locale: str) -> tuple[SceneManifest, dict[str, int]]:
        user_role = self._infer_user_role(prompt)
        counterpart = self._infer_counterpart(prompt)
        title_words = re.findall(r"[A-Za-z0-9']+", prompt)[:7]
        title = " ".join(title_words).strip().title() or "New Scene"
        language = (
            "Hinglish"
            if re.search(r"\b(hinglish|code[- ]?mix(?:ed|ing)?)\b", prompt, re.IGNORECASE)
            else "Hindi"
            if re.search(r"\bhindi\b", prompt, re.IGNORECASE)
            else "English"
        )
        region = "India" if locale.lower().endswith("in") else "Global"
        identity_kind = self._infer_identity_kind(prompt)
        candidates = [
            SceneCharacterDraft(
                key="primary-counterpart",
                name=counterpart,
                role="Primary counterpart",
                identity=counterpart if counterpart != "Primary counterpart" else "",
                identity_kind=identity_kind,
                summary="The central person the user must engage with to move the situation forward.",
                objective="Pursue their own credible objective and test the user's decisions.",
                goals=["Advance their position", "Respond consistently to evidence"],
                fears=["Losing control of the situation"],
                strategies=["Probe", "Challenge", "Redirect"],
                authority=65,
                selected=True,
                selection_reason="The scenario needs a primary counterpart.",
                speech=SceneSpeechProfile(
                    language=language,
                    region=region,
                    accent="Indian" if region == "India" else "Neutral",
                    code_mixing="natural conversational Hinglish" if language == "Hinglish" else "natural",
                ),
                voice=SceneVoiceProfile(),
            ),
            SceneCharacterDraft(
                key="independent-perspective",
                name="Independent perspective",
                role="A second participant with a different stake",
                summary="Adds tension, evidence, or a competing interpretation without duplicating the primary role.",
                objective="Protect a distinct interest and reveal useful complications.",
                goals=["Keep the situation realistic"],
                fears=["Being ignored"],
                strategies=["Correct", "Probe", "Concede"],
                authority=48,
                selected=True,
                selection_reason="A second perspective makes the interaction less scripted.",
                speech=SceneSpeechProfile(language=language, region=region, accent="Indian" if region == "India" else "Neutral"),
                voice=SceneVoiceProfile(),
            ),
            SceneCharacterDraft(
                key="optional-observer",
                name="Optional observer",
                role="Observer or facilitator",
                summary="Can regulate the interaction when the user decides the scene benefits from a third role.",
                objective="Keep the scene coherent without taking over.",
                goals=["Track progress"],
                fears=["Derailing the central exchange"],
                strategies=["Redirect", "End"],
                authority=35,
                selected=False,
                selection_reason="Recommended only when a third point of view is useful.",
                speech=SceneSpeechProfile(language=language, region=region, accent="Indian" if region == "India" else "Neutral"),
                voice=SceneVoiceProfile(),
            ),
        ]
        manifest = SceneManifest(
            title=title[:180],
            scenario_summary=prompt,
            setting="The place and moment described by the user.",
            stakes="The user must handle the situation credibly and live with the other participants' reactions.",
            tone="Natural, responsive, and grounded in the requested situation.",
            objective=user_role.objective,
            end_conditions=["The user's objective is resolved", "A participant credibly ends the interaction"],
            user_role=user_role,
            ai_characters=candidates,
            pressure="realistic",
            required_fresh_searches=[],
            assumptions=["This deterministic compiler is active only because SCENE_COMPILER_PROVIDER=rules was selected."],
            metadata={
                "compiler": "rules",
                "locale": locale,
                "reuse_key": f"{counterpart.casefold()}|{language.casefold()}|{region.casefold()}",
            },
        )
        return manifest, {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

    async def prepare(
        self,
        manifest: SceneManifest,
        *,
        research_packet: dict[str, Any],
    ) -> tuple[PreparedScene, dict[str, int]]:
        prepared = [
            PreparedCharacter(
                key=character.key,
                persona_summary=character.summary,
                stable_facts=character.public_knowledge,
                mannerisms=["Responds from their own objective", "Uses concise conversational phrasing"],
                opening_line=f"Let's begin. {character.objective}",
            )
            for character in manifest.selected_characters
        ]
        return (
            PreparedScene(
                characters=prepared,
                opening_character_key=prepared[0].key,
                evidence_summary=[],
            ),
            {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        )

    async def decide(
        self,
        *,
        manifest: SceneManifest,
        character: SceneCharacterDraft,
        runtime_state: dict[str, Any],
        recent_turns: list[dict[str, Any]],
        memories: list[dict[str, Any]],
        sources: list[dict[str, Any]],
    ) -> tuple[CharacterAction, dict[str, int]]:
        user_text = recent_turns[-1]["text"] if recent_turns else ""
        action = "challenge" if manifest.pressure == "high_pressure" else "probe"
        response = (
            f"{character.name}: I heard your position. What is the strongest reason I should accept it"
            f"{' after what you just said' if user_text else ''}?"
        )
        return (
            CharacterAction(
                character_key=character.key,
                action=action,
                spoken_response=response,
                private_reason="Keep the user active and test the stated objective.",
                mood="attentive",
            ),
            {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        )

    @staticmethod
    def _infer_identity_kind(prompt: str) -> str:
        public_markers = (
            r"\b(public figure|celebrity|bollywood|actor|actress|film star|politician|"
            r"cricketer|singer|famous personality)\b"
        )
        return "public_figure" if re.search(public_markers, prompt, re.IGNORECASE) else "original"

    @staticmethod
    def _infer_user_role(prompt: str) -> SceneUserRole:
        match = re.search(
            r"\b(?:i want to be|i will be|i am|as)\s+(?:an?\s+)?([^,.;]{2,80})",
            prompt,
            re.IGNORECASE,
        )
        role = match.group(1).strip() if match else "Active participant"
        return SceneUserRole(
            role=role,
            objective=f"Practice and succeed in this situation: {prompt[:420]}",
        )

    @staticmethod
    def _infer_counterpart(prompt: str) -> str:
        match = re.search(r"\bwith\s+([A-Z][A-Za-z.' -]{2,80})", prompt)
        if not match:
            return "Primary counterpart"
        value = re.split(r"\b(?:for|about|tomorrow|where|who)\b", match.group(1), maxsplit=1, flags=re.IGNORECASE)[0]
        return value.strip(" ,.-")[:120] or "Primary counterpart"


def build_scene_compiler(settings: Settings) -> SceneCompiler:
    if settings.scene_compiler_provider == "rules":
        if not (settings.test_mode or settings.app_env.strip().lower() == "development"):
            raise RuntimeError("The rules scene compiler is limited to test and development environments")
        return RuleBasedSceneCompiler()
    return DatabricksSceneCompiler(settings)

