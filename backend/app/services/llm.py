from langchain_google_genai import ChatGoogleGenerativeAI
from app.core.config import get_settings

# Load environment settings
settings = get_settings()


def get_llm() -> ChatGoogleGenerativeAI:
    """
    Returns a configured instance of Gemini (Google Generative AI)
    This can be safely reused across multiple requests.
    """

    llm = ChatGoogleGenerativeAI(
        model=settings.GEMINI_MODEL,           # e.g., "gemini-1.5-pro" or "gemini-1.5-flash"
        google_api_key=settings.GEMINI_API_KEY,
        temperature=0.7,                       # balance between creativity & precision
        convert_system_message_to_human=True,  # ensures system prompts are interpreted properly
        max_retries=1,                         # fail fast on 429 instead of ~67s of backoff
    )

    return llm


def get_lead_context_llm() -> ChatGoogleGenerativeAI:
    """
    Fast, low-temperature model for lead-context extraction during enrichment.
    Extraction is a structured-output task (not creative), so we prefer Flash, a low
    temperature for determinism, and a small output cap for speed.
    Override with APP_GEMINI_LEAD_CONTEXT_MODEL; else the main APP_GEMINI_MODEL; else Flash.
    """
    name = (getattr(settings, "GEMINI_LEAD_CONTEXT_MODEL", None) or "").strip()
    if not name:
        # Follow the main model: a hardcoded gemini-2.5-flash 404s on newly created
        # API keys ("no longer available to new users").
        name = (settings.GEMINI_MODEL or "").strip()
    if not name:
        name = "gemini-2.5-flash"
    return ChatGoogleGenerativeAI(
        model=name,
        google_api_key=settings.GEMINI_API_KEY,
        temperature=0.1,
        convert_system_message_to_human=True,
        # gemini-2.5-flash is a "thinking" model: reasoning tokens count against this
        # budget, so a tight cap (e.g. 512) truncates the JSON output. Keep headroom.
        max_output_tokens=2048,
    )


def get_campaign_draft_llm() -> ChatGoogleGenerativeAI:
    """
    Faster model + capped output for campaign email drafts (Generate with AI).
    Override with APP_GEMINI_CAMPAIGN_DRAFT_MODEL; else use APP_GEMINI_MODEL; else Flash.
    """
    name = (getattr(settings, "GEMINI_CAMPAIGN_DRAFT_MODEL", None) or "").strip()
    if not name:
        name = (getattr(settings, "GEMINI_MODEL", None) or "").strip()
    if not name:
        name = "gemini-2.5-flash"
    return ChatGoogleGenerativeAI(
        model=name,
        google_api_key=settings.GEMINI_API_KEY,
        temperature=0.55,
        convert_system_message_to_human=True,
        # Room for ~200-word HTML + subject; avoids mid-sentence cutoffs on some Gemini builds.
        max_output_tokens=4096,
    )
