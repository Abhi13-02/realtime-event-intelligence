import os
from groq import Groq
from app.pipeline.interfaces import LLMInterface
from app.pipeline.exceptions import LLMServiceError


class GroqAdapter(LLMInterface):
    """
    LLM adapter for article summarisation using Groq's inference API.
    Replaces the Cohere adapter — same LLMInterface, drop-in swap.

    Model: llama-3.1-8b-instant
      - Free tier: 30 req/min, 14,400 req/day
      - Fast and accurate enough for 2-3 sentence news summaries
    """

    def __init__(self, model_name: str = "llama-3.1-8b-instant"):
        api_key = os.environ.get("GROQ_API_KEY")
        if not api_key:
            raise ValueError("GROQ_API_KEY environment variable not set")
        self._client = Groq(api_key=api_key)
        self._model = model_name

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
