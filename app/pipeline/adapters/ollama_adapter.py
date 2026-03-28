import requests
from app.pipeline.interfaces import LLMInterface
from app.pipeline.exceptions import LLMServiceError


class OllamaAdapter(LLMInterface):
    """
    Local LLM adapter using Ollama.
    Run Ollama locally: https://ollama.com/
    Pull a model: `ollama pull llama3` or `ollama pull mistral`
    Then start: `ollama serve` (default: http://localhost:11434)
    """

    def __init__(self, model: str = "llama3", base_url: str = "http://localhost:11434"):
        self.model = model
        self.base_url = base_url.rstrip("/")

    def generate_summary(self, headline: str, content: str) -> str:
        prompt = (
            f"You are a news summarisation assistant.\n\n"
            f"Article title: {headline}\n"
            f"Article content: {content[:1500]}\n\n"
            f"Write a 2-3 sentence neutral factual summary. "
            f"Return ONLY the summary text, no labels or preamble."
        )
        try:
            response = requests.post(
                f"{self.base_url}/api/generate",
                json={"model": self.model, "prompt": prompt, "stream": False},
                timeout=60,
            )
            response.raise_for_status()
            return response.json()["response"].strip()
        except requests.exceptions.ConnectionError:
            raise LLMServiceError(
                f"Cannot connect to Ollama at {self.base_url}. "
                "Make sure Ollama is running: `ollama serve`"
            )
        except Exception as e:
            raise LLMServiceError(f"Ollama error: {str(e)}") from e
