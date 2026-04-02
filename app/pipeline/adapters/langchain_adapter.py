import os
from langchain_cohere import ChatCohere
from app.pipeline.interfaces import LLMInterface
from app.pipeline.exceptions import LLMServiceError

class LangchainCohereAdapter(LLMInterface):
    """
    Interface wrapper around Langchain's ChatCohere.
    Used for summarizing news articles using Cohere models.
    """
    def __init__(self, model_name: str = 'command-r-08-2024'):
        # Assumes COHERE_API_KEY is in os.environ
        api_key = os.environ.get("COHERE_API_KEY")
        if not api_key:
            raise ValueError("COHERE_API_KEY environment variable not set")
            
        self.model = ChatCohere(
            model=model_name,
            cohere_api_key=api_key
        )
        
    def generate_summary(self, headline: str, content: str) -> str:
        prompt = f"""You are a news summarisation assistant.

Article title: {headline}
Article content: {content}

Task: Write a 2-3 sentence neutral summary of this article.
Return only the summary. No preamble, no labels."""
        try:
            response = self.model.invoke(prompt)
            # Response may be AIMessage which has a content property
            if hasattr(response, 'content'):
                return response.content.strip()
            return str(response).strip()
        except Exception as e:
            raise LLMServiceError(f"Langchain Cohere API error: {str(e)}") from e
