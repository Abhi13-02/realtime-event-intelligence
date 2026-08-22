from app.adapters.ai.groq_client import get_groq_client
from app.core.config import get_settings
from app.pipeline.interfaces import LLMInterface

# LLMServiceError stays in the pipeline package: it is a PipelineError subclass
# and the orchestrator's error handling keys off that hierarchy. Importing it
# here is the one edge from adapters back into pipeline, kept deliberately
# rather than duplicating the exception or adding a translation layer.
from app.pipeline.exceptions import LLMServiceError


class GroqAdapter(LLMInterface):
    """
    LLM adapter for article summarisation using Groq's inference API.
    Replaces the Cohere adapter — same LLMInterface, drop-in swap.

    The model comes from settings.groq_model (GROQ_MODEL) rather than being
    named here, so a provider decommission is one env change instead of an
    edit in every file that talks to Groq.
    """

    def __init__(self, model_name: str | None = None):
        self._client = get_groq_client()
        self._model = model_name or get_settings().groq_model

    def generate_summary(self, headline: str, content: str) -> str:
        prompt = f"""You are a news summarisation assistant.

Article title: {headline}
Article content: {content}

Task: Write a 2-3 sentence neutral summary of this article.
Return only the summary. No preamble, no labels."""
        try:
            response = self._client.chat.completions.create(
                model=self._model,
                messages=[{"role": "user", "content": prompt}],
            )
            return response.choices[0].message.content.strip()
        except Exception as exc:
            raise LLMServiceError(f"Groq API error: {exc}") from exc
