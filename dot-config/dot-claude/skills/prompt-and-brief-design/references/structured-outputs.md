# prompt-and-brief-design — structured outputs (reference)
Read when asking a model for JSON or schema-bound output. Parent: `prompt-and-brief-design` SKILL.md.

## 5. Structured outputs
- Claude: `output_config={"format": {"type": "json_schema", "schema": S}}`, or strict tools (`"strict": true`) with `tool_choice` `any`/`tool`. Schema subset: objects need `"additionalProperties": false`; no recursive schemas; no numeric bounds or string length limits (the Python/TypeScript SDKs strip unsupported keywords into descriptions and validate client-side); `enum` of primitives only; required properties are emitted first, in schema order. A `refusal` or `max_tokens` stop can still yield non-conforming output.
- OpenAI-compatible: `response_format={"type": "json_schema", "json_schema": {"name": "...", "schema": S, "strict": True}}`; vLLM also accepts `extra_body={"structured_outputs": {"json" | "regex" | "choice" | "grammar": ...}}` (the `guided_*` fields were removed in v0.12); llama-server enforces `response_format` and takes `json_schema`/`grammar` on `/completion`. Some servers accept a schema without enforcing it — test with invalid-bait inputs.
- Without constrained decoding: JSON mode or plain prompting with the schema in the prompt, then validate.
- Schema design: descriptive field names and descriptions, enums for closed sets (include `unsure`/`other` when real), evidence or rationale fields placed before the answer when order matters (mark them required), flat over deeply nested, ids instead of free text for references.
```python
from typing import Literal
from pydantic import BaseModel, ValidationError

class Verdict(BaseModel):
    evidence: list[str]
    label: Literal["pass", "fail", "unsure"]

def structured(call, prompt: str, retries: int = 2) -> Verdict:
    msg = prompt
    for _ in range(retries + 1):
        raw = call(msg)                               # provider call, schema-enforced where supported
        try:
            return Verdict.model_validate_json(raw)
        except ValidationError as err:
            msg = f"{prompt}\n\nThe previous output failed validation:\n{err}\nReturn only JSON matching the schema."
    raise ValueError("no valid structured output after retries")
```
