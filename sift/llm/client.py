from __future__ import annotations

import base64
import json
import logging
from pathlib import Path
from typing import Any, Literal, Protocol

import anthropic
from anthropic.types import ImageBlockParam, Message, OutputConfigParam, TextBlockParam
from pydantic import BaseModel, ValidationError

from sift.config import Effort
from sift.domain import FailureKind, ProcessingError
from sift.llm.prompts import Prompt
from sift.llm.schemas import (
    BriefDraft,
    BriefInput,
    DigestDraft,
    DigestInput,
    ExtractInput,
    ExtractOutput,
    OutlineDraft,
    OutlineInput,
    ScoreInput,
    ScoreOutput,
    SetupDraft,
    SetupInput,
    TopicFitDraft,
    TopicFitInput,
    TopicPlanDraft,
    TopicPlanInput,
    TopicRebuildDraft,
    TopicRebuildInput,
)
from sift.media import ImageFormat, image_format

log = logging.getLogger(__name__)

_OUTPUT_TOOL = "record_output"


class LLM(Protocol):
    def extract(self, inp: ExtractInput) -> tuple[ExtractOutput, str]: ...

    def score(self, inp: ScoreInput) -> tuple[ScoreOutput, str]: ...

    def compose_digest(self, inp: DigestInput) -> tuple[DigestDraft, str]: ...

    def outline(self, inp: OutlineInput) -> tuple[OutlineDraft, str]: ...

    def compose_brief(self, inp: BriefInput) -> tuple[BriefDraft, str]: ...

    def plan_topics(self, inp: TopicPlanInput) -> tuple[TopicPlanDraft, str]: ...

    def draft_setup(self, inp: SetupInput) -> tuple[SetupDraft, str]: ...

    def rebuild_topics(self, inp: TopicRebuildInput) -> tuple[TopicRebuildDraft, str]: ...

    def fit_topic(self, inp: TopicFitInput) -> tuple[TopicFitDraft, str]: ...


def extract_prompt(inp: ExtractInput) -> str:
    return Prompt.extract_user.render(**inp.model_dump(), frame_count=len(inp.frames))


def score_prompts(inp: ScoreInput) -> tuple[str, str]:
    system = Prompt.score_system.render(
        values_text=inp.values_text,
        goals=[g.model_dump() for g in inp.goals],
        examples=[e.model_dump() for e in inp.examples],
        threshold=inp.threshold,
    )
    return system, Prompt.score_user.render(card_json=inp.card.model_dump_json(indent=2))


def digest_prompts(inp: DigestInput) -> tuple[str, str]:
    system = Prompt.digest_system.render(values_text=inp.values_text, goals=[g.model_dump() for g in inp.goals])
    items = json.dumps([i.model_dump(mode="json") for i in inp.items], indent=2)
    return system, Prompt.digest_user.render(items_json=items)


def outline_prompts(inp: OutlineInput) -> tuple[str, str]:
    system = Prompt.outline_system.render(
        topics=[t.model_dump() for t in inp.topics],
        may_create_topic=inp.may_create_topic,
        label_vocabulary=inp.label_vocabulary,
        moves=[m.model_dump() for m in inp.moves],
    )
    user = Prompt.outline_user.render(
        source=inp.source,
        card_json=inp.card.model_dump_json(indent=2),
        caption=inp.caption,
        on_screen_text=inp.on_screen_text,
        transcript_excerpt=inp.transcript_excerpt,
    )
    return system, user


def brief_prompts(inp: BriefInput) -> tuple[str, str]:
    system = Prompt.brief_system.render(goals=[g.model_dump() for g in inp.goals])
    user = Prompt.brief_user.render(
        topic=inp.topic,
        topic_description=inp.topic_description,
        previous_points=inp.previous_points,
        sources_json=json.dumps([s.model_dump(mode="json") for s in inp.sources], indent=1),
    )
    return system, user


def plan_prompts(inp: TopicPlanInput) -> tuple[str, str]:
    system = Prompt.topics_system.render(goals=[g.model_dump() for g in inp.goals], retired=inp.retired)
    posts = json.dumps([p.model_dump(mode="json") for p in inp.posts], indent=1) if inp.posts else ""
    user = Prompt.topics_user.render(topics=[t.model_dump() for t in inp.topics], posts=inp.posts, posts_json=posts)
    return system, user


def setup_prompts(inp: SetupInput) -> tuple[str, str]:
    system = Prompt.setup_system.render(
        current_goals=[g.model_dump() for g in inp.current_goals], current_values=inp.current_values
    )
    user = Prompt.setup_user.render(
        answers=[a.model_dump() for a in inp.answers], kept_anyway=[k.model_dump() for k in inp.kept_anyway]
    )
    return system, user


def rebuild_prompts(inp: TopicRebuildInput) -> tuple[str, str]:
    system = Prompt.rebuild_system.render(goals=[g.model_dump() for g in inp.goals])
    posts = json.dumps([p.model_dump(mode="json") for p in inp.posts], indent=1)
    user = Prompt.rebuild_user.render(topics=[t.model_dump() for t in inp.topics], posts_json=posts)
    return system, user


def fit_prompts(inp: TopicFitInput) -> tuple[str, str]:
    posts = json.dumps([p.model_dump(mode="json") for p in inp.posts], indent=1)
    user = Prompt.fit_user.render(topic=inp.topic, description=inp.description, posts_json=posts)
    return Prompt.fit_system.render(), user


_MEDIA_TYPES: dict[ImageFormat | None, Literal["image/jpeg", "image/png", "image/webp", "image/gif"]] = {
    "jpg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
    "gif": "image/gif",
}


def _image_blocks(paths: list[Path]) -> list[ImageBlockParam | TextBlockParam]:
    blocks: list[ImageBlockParam | TextBlockParam] = []
    for path in paths:
        data = path.read_bytes() if path.is_file() else b""
        if media_type := _MEDIA_TYPES.get(image_format(data)):
            encoded = base64.standard_b64encode(data).decode("ascii")
            blocks.append({"type": "image", "source": {"type": "base64", "media_type": media_type, "data": encoded}})
    return blocks


class AnthropicLLM:
    def __init__(
        self,
        client: anthropic.Anthropic,
        *,
        extract_model: str,
        score_model: str,
        digest_model: str,
        outline_model: str,
        brief_model: str,
        effort: Effort,
    ) -> None:
        self._client = client
        self._extract_model = extract_model
        self._score_model = score_model
        self._digest_model = digest_model
        self._outline_model = outline_model
        self._brief_model = brief_model
        self._effort: Effort = effort

    def extract(self, inp: ExtractInput) -> tuple[ExtractOutput, str]:
        content = _image_blocks([Path(f) for f in inp.frames])
        content.append({"type": "text", "text": extract_prompt(inp)})
        # Five or more card variants exceed the API's compiled-grammar limit, so the card is validated here.
        out = self._parse(self._extract_model, Prompt.extract_system.render(), content, ExtractOutput, strict=False)
        return out, self._extract_model

    def score(self, inp: ScoreInput) -> tuple[ScoreOutput, str]:
        system, user = score_prompts(inp)
        out = self._parse(self._score_model, system, [{"type": "text", "text": user}], ScoreOutput)
        return out, self._score_model

    def compose_digest(self, inp: DigestInput) -> tuple[DigestDraft, str]:
        system, user = digest_prompts(inp)
        out = self._parse(self._digest_model, system, [{"type": "text", "text": user}], DigestDraft)
        return out, self._digest_model

    def outline(self, inp: OutlineInput) -> tuple[OutlineDraft, str]:
        system, user = outline_prompts(inp)
        out = self._parse(self._outline_model, system, [{"type": "text", "text": user}], OutlineDraft)
        return out, self._outline_model

    def compose_brief(self, inp: BriefInput) -> tuple[BriefDraft, str]:
        system, user = brief_prompts(inp)
        out = self._parse(self._brief_model, system, [{"type": "text", "text": user}], BriefDraft)
        return out, self._brief_model

    def plan_topics(self, inp: TopicPlanInput) -> tuple[TopicPlanDraft, str]:
        system, user = plan_prompts(inp)
        out = self._parse(self._outline_model, system, [{"type": "text", "text": user}], TopicPlanDraft)
        return out, self._outline_model

    def draft_setup(self, inp: SetupInput) -> tuple[SetupDraft, str]:
        system, user = setup_prompts(inp)
        out = self._parse(self._digest_model, system, [{"type": "text", "text": user}], SetupDraft)
        return out, self._digest_model

    def rebuild_topics(self, inp: TopicRebuildInput) -> tuple[TopicRebuildDraft, str]:
        system, user = rebuild_prompts(inp)
        out = self._parse(self._digest_model, system, [{"type": "text", "text": user}], TopicRebuildDraft)
        return out, self._digest_model

    def fit_topic(self, inp: TopicFitInput) -> tuple[TopicFitDraft, str]:
        system, user = fit_prompts(inp)
        out = self._parse(self._digest_model, system, [{"type": "text", "text": user}], TopicFitDraft)
        return out, self._digest_model

    def _parse[T: BaseModel](
        self,
        model: str,
        system: str,
        content: list[ImageBlockParam | TextBlockParam],
        schema: type[T],
        *,
        strict: bool = True,
    ) -> T:
        for attempt in (1, 2):
            try:
                if strict:
                    resp = self._client.messages.parse(
                        model=model,
                        max_tokens=16000,
                        system=system,
                        messages=[{"role": "user", "content": content}],
                        output_format=schema,
                        output_config=OutputConfigParam(effort=self._effort),
                    )
                    _check_stop(model, resp)
                    parsed = resp.parsed_output
                else:
                    # Sonnet 5.5 and Opus 5.5 reject a forced tool_choice, so a missing call is retried instead.
                    resp = self._client.messages.create(
                        model=model,
                        max_tokens=16000,
                        system=f"{system}\n\nCall the {_OUTPUT_TOOL} tool once with your result.",
                        messages=[{"role": "user", "content": content}],
                        tools=[{"name": _OUTPUT_TOOL, "input_schema": schema.model_json_schema()}],
                        output_config=OutputConfigParam(effort=self._effort),
                    )
                    _check_stop(model, resp)
                    tool_input = next((b.input for b in resp.content if b.type == "tool_use"), None)
                    if tool_input is None:
                        raise ValueError(f"no {_OUTPUT_TOOL} call")
                    parsed = _validate_tool_input(schema, tool_input)
            except (ValidationError, ValueError) as e:
                if attempt == 2:
                    raise ProcessingError(
                        FailureKind.llm_failed, "The model returned invalid output twice.", retryable=True
                    ) from e
                log.info("invalid structured output from %s, retrying once: %s", model, e)
                continue
            except (anthropic.AuthenticationError, anthropic.PermissionDeniedError) as e:
                raise ProcessingError(FailureKind.llm_failed, "Anthropic rejected the API key.", retryable=False) from e
            except anthropic.NotFoundError as e:
                raise ProcessingError(FailureKind.llm_failed, f"Unknown model {model!r}.", retryable=False) from e
            except anthropic.BadRequestError as e:
                raise ProcessingError(FailureKind.llm_failed, f"Bad request: {e.message}"[:300], retryable=False) from e
            except (anthropic.APIStatusError, anthropic.APIConnectionError) as e:
                raise ProcessingError(
                    FailureKind.llm_failed, f"Anthropic API: {type(e).__name__}", retryable=True
                ) from e

            if parsed is None:
                raise ProcessingError(
                    FailureKind.llm_failed, "The model returned no structured output.", retryable=True
                )
            return parsed
        raise AssertionError("unreachable")


_CONTAINER_ERRORS = {"model_attributes_type", "model_type", "dict_type", "list_type"}


def _validate_tool_input[T: BaseModel](schema: type[T], data: object) -> T:
    """Without strict tool use the model sometimes sends a nested object or list as a JSON string."""
    while True:
        try:
            return schema.model_validate(data)
        except ValidationError as e:
            stringified = [
                err["loc"] for err in e.errors() if err["type"] in _CONTAINER_ERRORS and isinstance(err["input"], str)
            ]
            if not stringified:
                raise
            decoded = data
            for loc in stringified:
                decoded = _decode_at(decoded, loc)
            if decoded == data:
                raise
            data = decoded


def _decode_at(data: Any, loc: tuple[int | str, ...]) -> Any:
    if not loc:
        return json.loads(data) if isinstance(data, str) else data
    head, rest = loc[0], loc[1:]
    if isinstance(data, dict) and head in data:
        if not rest and isinstance(data[head], str):
            return _decode_field(data, str(head))
        return {**data, head: _decode_at(data[head], rest)}
    if isinstance(data, list) and isinstance(head, int):
        return [_decode_at(v, rest) if i == head else v for i, v in enumerate(data)]
    # A discriminated union adds its tag to the error location; it is not a key in the data.
    return _decode_at(data, rest)


def _decode_field(parent: dict[str, Any], key: str) -> dict[str, Any]:
    text = parent[key]
    try:
        return {**parent, key: json.loads(text)}
    except json.JSONDecodeError:
        # The model sometimes keeps writing the rest of the parent object inside the string.
        whole = json.loads(f"{{{json.dumps(key)}: {text}")
        return {**whole, **{k: v for k, v in parent.items() if k != key}}


def _check_stop(model: str, resp: Message) -> None:
    log.info(
        "llm %s request_id=%s in=%s out=%s stop=%s",
        model,
        resp._request_id,
        resp.usage.input_tokens,
        resp.usage.output_tokens,
        resp.stop_reason,
    )
    if resp.stop_reason == "refusal":
        raise ProcessingError(FailureKind.llm_failed, "The model declined to process this post.", retryable=False)
    if resp.stop_reason == "max_tokens":
        raise ProcessingError(FailureKind.llm_failed, "The model output was cut off.", retryable=True)
