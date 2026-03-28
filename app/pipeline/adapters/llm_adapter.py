import google.generativeai as genai
from app.pipeline.interfaces import LLMInterface
from app.pipeline.exceptions import LLMServiceError

class GeminiAdapter(LLMInterface):
    """
    Interface wrapper around the Google Generative AI (Gemini) API.
    Used exclusively for summarizing news articles.
    """
    def __init__(self, api_key: str, model_name: str = 'gemini-2.5-flash'):
        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel(model_name)
        
    def generate_summary(self, headline: str, content: str) -> str:
        prompt = f"""You are a news summarisation assistant.

Article title: {headline}
Article content: {content}

Task: Write a 2-3 sentence neutral summary of this article.
Return only the summary. No preamble, no labels."""
        try:
            response = self.model.generate_content(prompt)
            return response.text.strip()
        except Exception as e:
            raise LLMServiceError(f"Gemini API error: {str(e)}") from e
