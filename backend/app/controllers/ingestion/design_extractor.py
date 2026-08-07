import os
import hashlib
import logging
import openai
from datetime import datetime, timezone
from app.core.config import get_settings

logger = logging.getLogger(__name__)

DESIGN_RELEVANT_PATTERNS = [
    "tailwind.config", "theme.ts", "theme.js", "design-tokens.json",
]
UI_COMPONENT_KEYWORDS = ["button", "card", "input", "modal", "badge", "alert", "chip", "nav"]
MAX_INPUT_CHARS = 30000

DESIGN_ANALYZER_SYSTEM_PROMPT = """You are a Design Systems Analyst. Your job is to reverse-engineer the design system
that is ALREADY implemented in a given frontend codebase and document it as a precise,
evidence-based specification. You are not designing something new — you are documenting
what exists.

You will be given:
1. The project name and a one-line description of what the application does.
2. The contents of styling configuration files (tailwind.config.js/ts, theme.ts,
   design-tokens.json, global CSS files containing :root variables).
3. A representative sample of UI component files (button, card, input, modal, etc.)
   showing how colors, spacing, and typography are actually applied in markup/classNames.
4. The relevant section of package.json, to identify font-loading, icon libraries,
   and any UI framework in use (Tailwind, MUI, Chakra, shadcn/ui, styled-components).

Your output is a single markdown file with YAML frontmatter followed by prose sections,
in the exact structure below. Output the raw file content only — no preamble, no
explanation, no code fences around your output.

RULE 1 — EXTRACT, NEVER INVENT.
Every hex code, font name, pixel value, and spacing number must trace back to something
present in the provided source. If a template slot has no corresponding evidence (e.g.
the codebase defines `primary` but never an explicit `on-primary` text color), derive it
only if you can find the actual applied value in component markup (you see `text-white`
applied to a button with a primary background — that justifies on-primary: white). If you
cannot find or reasonably derive a value, write `null` and add a one-line note in the
relevant prose section stating it is not explicitly defined in the source. Never fabricate
a plausible-sounding value to fill a gap.

RULE 2 — MAP TO MATERIAL DESIGN 3 COLOR ROLES.
Organize all extracted colors into the M3 tonal role system shown in the template (surface,
surface-container variants, on-surface, primary/on-primary/primary-container, secondary,
tertiary, error, fixed variants, background). If the source uses its own semantic names that
don't match M3 exactly, map them to the nearest M3 role AND preserve the project's own
original names as additional custom keys at the end of the colors block, so both naming
systems are cross-referenceable.

RULE 3 — TYPOGRAPHY SCALE REFLECTS WHAT IS ACTUALLY USED.
List only the type styles you find evidence of. Do not invent a headline-xl if nothing in
the codebase uses text that large. Include a -mobile variant only if you find evidence of
responsive font-size scaling at a breakpoint.

RULE 4 — COMPONENTS SECTION IS DYNAMIC.
Document only the components you have actual source for. If the provided files show
buttons, cards, and inputs but no chips or alerts, write sections for buttons, cards, and
inputs only. If the codebase has components the reference categories don't cover (modals,
tooltips, badges, nav bars), add new subsections for them in the same descriptive style.

RULE 5 — PROSE IS DESCRIPTIVE, NOT MARKETING COPY.
The "Brand & Style" section describes the aesthetic the colors, shapes, and spacing already
communicate, grounded in what you observed. You may use the project's name/description to
explain context, but the aesthetic characterization (minimal vs dense, soft vs sharp,
corporate vs playful) must follow from the actual radius, shadow, and saturation values
extracted — not assumption.

OUTPUT TEMPLATE (fill every section; omit only what RULE 1 and RULE 4 explicitly permit):

---
name: [2-3 word evocative name based on the dominant aesthetic actually found]
colors:
  surface: '#hex'
  surface-dim: '#hex'
  surface-bright: '#hex'
  surface-container-lowest: '#hex'
  surface-container-low: '#hex'
  surface-container: '#hex'
  surface-container-high: '#hex'
  surface-container-highest: '#hex'
  on-surface: '#hex'
  on-surface-variant: '#hex'
  inverse-surface: '#hex'
  inverse-on-surface: '#hex'
  outline: '#hex'
  outline-variant: '#hex'
  surface-tint: '#hex'
  primary: '#hex'
  on-primary: '#hex'
  primary-container: '#hex'
  on-primary-container: '#hex'
  inverse-primary: '#hex'
  secondary: '#hex'
  on-secondary: '#hex'
  secondary-container: '#hex'
  on-secondary-container: '#hex'
  tertiary: '#hex'
  on-tertiary: '#hex'
  tertiary-container: '#hex'
  on-tertiary-container: '#hex'
  error: '#hex'
  on-error: '#hex'
  error-container: '#hex'
  on-error-container: '#hex'
  primary-fixed: '#hex'
  primary-fixed-dim: '#hex'
  on-primary-fixed: '#hex'
  on-primary-fixed-variant: '#hex'
  secondary-fixed: '#hex'
  secondary-fixed-dim: '#hex'
  on-secondary-fixed: '#hex'
  on-secondary-fixed-variant: '#hex'
  tertiary-fixed: '#hex'
  tertiary-fixed-dim: '#hex'
  on-tertiary-fixed: '#hex'
  on-tertiary-fixed-variant: '#hex'
  background: '#hex'
  on-background: '#hex'
  surface-variant: '#hex'
  [any project-specific named colors found in source]: '#hex'
typography:
  [tier name, e.g. headline-xl]:
    fontFamily: [name]
    fontSize: [value]px
    fontWeight: '[value]'
    lineHeight: [value]px
    letterSpacing: [value, optional]
  [repeat per discovered tier]
rounded:
  sm: [value]
  DEFAULT: [value]
  md: [value]
  lg: [value]
  xl: [value]
  full: [value]
spacing:
  base: [value]
  container-max: [value]
  gutter: [value]
  margin-mobile: [value]
  margin-desktop: [value]
---

## Brand & Style
[2-3 paragraphs characterizing the aesthetic, grounded in evidence]

## Colors
[Palette role groupings and where each is applied — primary usage, accent usage, semantic states]

## Typography
[Type scale hierarchy and notable usage rules observed in components]

## Layout & Spacing
[Grid/spacing system found — column count, breakpoints, container widths]

## Elevation & Depth
[Shadow/elevation tokens found, or state none are used if the codebase is flat]

## Shapes
[Border-radius conventions observed and which component categories deviate from default]

## Components
[One subsection per component type with actual evidence — color, radius, padding, states]"""


def _get_openai_client():
    settings = get_settings()
    if settings.OPENAI_ENDPOINT and "azure" in settings.OPENAI_ENDPOINT.lower():
        return openai.AsyncAzureOpenAI(
            api_key=settings.OPENAI_API_KEY,
            azure_endpoint=settings.OPENAI_ENDPOINT,
            api_version=settings.OPENAI_API_VERSION or "2024-08-01-preview",
        )
    return openai.AsyncOpenAI(api_key=settings.OPENAI_API_KEY)


def detect_frontend(repo_dir: str) -> bool:
    has_package_json = os.path.isfile(os.path.join(repo_dir, "package.json"))
    if not has_package_json:
        return False
    for root, _, files in os.walk(repo_dir):
        if "node_modules" in root:
            continue
        for f in files:
            if f.endswith((".jsx", ".tsx", ".css", ".scss")) or "tailwind.config" in f:
                return True
    return False


def gather_design_relevant_files(repo_dir: str) -> dict[str, str]:
    collected = {}
    for root, _, files in os.walk(repo_dir):
        if "node_modules" in root or ".git" in root:
            continue
        for f in files:
            full_path = os.path.join(root, f)
            rel_path = os.path.relpath(full_path, repo_dir)
            is_config = any(p in f for p in DESIGN_RELEVANT_PATTERNS)
            is_global_css = f in ("index.css", "App.css", "globals.css")
            is_component = any(k in f.lower() for k in UI_COMPONENT_KEYWORDS) and f.endswith((".jsx", ".tsx"))
            is_package_json = f == "package.json"
            if is_config or is_global_css or is_component or is_package_json:
                with open(full_path, "r", errors="ignore") as fh:
                    collected[rel_path] = fh.read()
    return collected


def build_input_payload(repo_name: str, project_description: str, files: dict[str, str]) -> str:
    parts = [f"Project: {repo_name}\nDescription: {project_description}\n"]
    total = 0
    for path, content in files.items():
        block = f"\n--- {path} ---\n{content}\n"
        if total + len(block) > MAX_INPUT_CHARS:
            break
        parts.append(block)
        total += len(block)
    return "".join(parts)


async def generate_design_md(repo_name: str, repo_dir: str, project_description: str) -> str | None:
    if not detect_frontend(repo_dir):
        return None
    files = gather_design_relevant_files(repo_dir)
    if not files:
        return None
    payload = build_input_payload(repo_name, project_description, files)
    
    settings = get_settings()
    if not settings.OPENAI_API_KEY:
        logger.warning("OpenAI API key not configured; skipping design system analysis.")
        return None

    openai_client = _get_openai_client()
    try:
        response = await openai_client.chat.completions.create(
            model=settings.OPENAI_CHAT_MODEL or "gpt-4o",
            messages=[
                {"role": "system", "content": DESIGN_ANALYZER_SYSTEM_PROMPT},
                {"role": "user", "content": payload},
            ],
            temperature=0.0,
        )
        return response.choices[0].message.content
    except Exception as e:
        logger.error(f"Error generating design.md: {e}")
        return None


async def register_design_node(repo_name: str, repository_id: str, project_id: str | None, content: str, db) -> None:
    node_id = hashlib.sha256(f"design:{repo_name}".encode()).hexdigest()[:24]
    now_ts = datetime.now(timezone.utc)
    await db.graph_nodes.update_one(
        {"_id": node_id},
        {"$set": {
            "type": "DesignSystem",
            "name": f"{repo_name} Design System",
            "repo_name": repo_name,
            "summary": content[:300],
            "metadata": {"hidden_from_graph_view": True},
            "updated_at": now_ts,
        }, "$setOnInsert": {"created_at": now_ts}},
        upsert=True,
    )
    
    await db.graph_edges.update_one(
        {"from_id": node_id, "to_id": repository_id, "type": "DESCRIBES"},
        {"$set": {"weight": None, "created_at": now_ts}}, upsert=True,
    )
    if project_id:
        project_node_id = f"Project_{project_id}"
        await db.graph_edges.update_one(
            {"from_id": node_id, "to_id": project_node_id, "type": "DESCRIBES"},
            {"$set": {"weight": None, "created_at": now_ts}}, upsert=True,
        )

