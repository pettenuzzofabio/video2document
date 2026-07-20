"""The page-transcription prompt and the sidecar JSON schema (PLAN.md §4).

The prompt is engine-agnostic: it describes the task and the required output
format. Each engine adapter is responsible for making the page image available
to the model (Claude/Codex read it from a path, `llm` attaches it).
"""

from __future__ import annotations

MARKDOWN_SENTINEL = "===V2D_MARKDOWN==="
JSON_SENTINEL = "===V2D_JSON==="
FIGURE_PLACEHOLDER_PREFIX = "FIGURE:"

#: jsonschema for the per-page sidecar the model must emit (types, no strict enums,
#: to avoid spurious retries on minor wording).
PAGE_SIDECAR_SCHEMA = {
    "type": "object",
    "required": [
        "page", "language", "figures", "unclear",
        "continues_from_prev", "continues_to_next",
    ],
    "properties": {
        "page": {"type": "integer"},
        "language": {"type": "string"},
        "confidence": {"type": "string"},
        "figures": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["id", "bbox_pct", "kind"],
                "properties": {
                    "id": {"type": "string"},
                    "bbox_pct": {
                        "type": "array",
                        "items": {"type": "number"},
                        "minItems": 4,
                        "maxItems": 4,
                    },
                    "caption": {"type": ["string", "null"]},
                    "kind": {"type": "string"},
                },
            },
        },
        "header": {"type": ["string", "null"]},
        "footer": {"type": ["string", "null"]},
        "page_number": {"type": ["string", "null"]},
        "unclear": {"type": "array", "items": {"type": "string"}},
        "continues_from_prev": {"type": "boolean"},
        "continues_to_next": {"type": "boolean"},
    },
}

_TEMPLATE = """\
You transcribe ONE page of a document from a screenshot. Reproduce the page's \
content faithfully. Do NOT summarize, translate, rephrase, improve, or complete \
anything — transcribe what is actually there.

Output EXACTLY these two sections, each introduced by its sentinel on its own \
line, in this order, with nothing before or after:

{md_sentinel}
<the page content as GitHub-flavored Markdown>
{json_sentinel}
<a single JSON object matching the schema below>

Do NOT wrap the sections in code fences. (The Markdown itself may contain ``` fences.)

MARKDOWN rules:
- Transcribe the visible text verbatim, keeping its original language (Italian or \
English — never translate).
- Use heading levels (#, ##, ...) that match the visual hierarchy; use lists for lists.
- Reproduce tables as GitHub Markdown tables. If a table is too complex or irregular \
to represent faithfully, do NOT drop any content: instead declare it as a figure \
(below) so it is embedded as an image.
- For every chart, diagram, image, photo, or logo, put a placeholder at its position \
in the reading order: ![<short caption>]({fig_prefix}figN) with figN = fig1, fig2, ... \
Every such figN MUST have a matching entry in "figures".
- Do NOT put running headers, running footers, or the page number in the Markdown \
body — put them in the JSON fields instead.
- Mark any unreadable or ambiguous span inline as [unclear: <what you can tell>]. \
NEVER guess numbers, names, amounts, or dates.

JSON object schema:
{{
  "page": {page_no},
  "language": "it" or "en",
  "confidence": "high" | "medium" | "low",
  "figures": [
    {{"id": "figN", "bbox_pct": [x1, y1, x2, y2], "caption": "<text>",
      "kind": "chart|diagram|image|photo|logo|table|other"}}
  ],
  "header": <string or null>,
  "footer": <string or null>,
  "page_number": <string or null>,
  "unclear": ["<short note>", ...],
  "continues_from_prev": <true if the page starts mid-sentence or mid-table>,
  "continues_to_next": <true if the page ends mid-sentence or mid-table>
}}

"bbox_pct" = [x1, y1, x2, y2] as PERCENTAGES (0-100) of the page width and height, \
where (x1, y1) is the top-left and (x2, y2) the bottom-right of the figure's bounding \
box. Prefer a slightly generous box over a tight one.

This is page {page_no}; set "page" to {page_no}.
"""


#: Prompt for extracting a supplied high-resolution diagram photo into Markdown.
DETAIL_EXTRACTION_PROMPT = (
    "This is a high-resolution image of a single diagram from a document page. "
    "Extract its content faithfully as GitHub-flavored Markdown: the diagram title "
    "(if any), every visible text label, and the relationships/connections between "
    "elements (as a bullet list or a table). Transcribe verbatim in the original "
    "language; do not translate, summarize, or invent anything. Mark anything you "
    "cannot read as [unclear]. Output ONLY the Markdown, with no preamble or sentinels."
)


def build_transcription_prompt(page_no: int) -> str:
    return _TEMPLATE.format(
        md_sentinel=MARKDOWN_SENTINEL,
        json_sentinel=JSON_SENTINEL,
        fig_prefix=FIGURE_PLACEHOLDER_PREFIX,
        page_no=page_no,
    )
