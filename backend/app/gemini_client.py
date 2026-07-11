import logging
import random
from typing import List, Dict, Any, AsyncGenerator
from google import genai
from google.genai import types
from backend.app.config import settings

logger = logging.getLogger("amnesia.gemini")

def get_client() -> genai.Client:
    return genai.Client(api_key=settings.gemini_api_key)

def is_api_configured() -> bool:
    key = settings.gemini_api_key
    return bool(key and not key.startswith("your_") and len(key) > 5)

def format_messages(messages: List[Dict[str, str]]):
    """
    Translates OpenAI-style role/content message dictionary to Gemini contents list
    and system_instruction.
    """
    contents = []
    system_instruction = None
    
    for msg in messages:
        role = msg.get("role")
        content = msg.get("content")
        if role == "system":
            system_instruction = content
        else:
            # Map roles: user -> user, assistant -> model
            gemini_role = "user" if role == "user" else "model"
            contents.append(
                types.Content(
                    role=gemini_role,
                    parts=[types.Part.from_text(text=content)]
                )
            )
            
    return contents, system_instruction

async def get_embedding(text: str) -> List[float]:
    """
    Generates a 768-dimensional embedding using Gemini's gemini-embedding-2 model.
    Falls back to mock embeddings if API key is not configured.
    """
    if not is_api_configured():
        logger.warning("GEMINI_API_KEY not configured. Generating mock 768-dim embedding.")
        random.seed(hash(text))
        return [random.uniform(-0.1, 0.1) for _ in range(768)]
    
    retries = 3
    delay = 15
    for attempt in range(retries):
        try:
            client = get_client()
            response = await client.aio.models.embed_content(
                model="gemini-embedding-2",
                contents=text,
                config=types.EmbedContentConfig(output_dimensionality=768)
            )
            return response.embeddings[0].values
        except Exception as e:
            err_str = str(e)
            if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str or "quota" in err_str.lower():
                logger.warning(f"Gemini Embedding API rate limit hit. Retrying in {delay} seconds (Attempt {attempt+1}/{retries})... Error: {e}")
                import asyncio
                await asyncio.sleep(delay)
                delay *= 2
            else:
                logger.error(f"Error calling Gemini Embedding API: {e}. Falling back to mock.")
                random.seed(hash(text))
                return [random.uniform(-0.1, 0.1) for _ in range(768)]
                
    logger.error("Gemini Embedding API rate limit exceeded after retries. Falling back to mock.")
    random.seed(hash(text))
    return [random.uniform(-0.1, 0.1) for _ in range(768)]

def is_groq_configured() -> bool:
    key = settings.groq_api_key
    return bool(key and not key.startswith("your_") and len(key) > 5)

def get_groq_client():
    from openai import AsyncOpenAI
    return AsyncOpenAI(
        api_key=settings.groq_api_key,
        base_url="https://api.groq.com/openai/v1"
    )

async def get_chat_completion(
    messages: List[Dict[str, str]], 
    temperature: float = 0.7,
    max_tokens: int = 1000
) -> str:
    """
    Queries Groq for non-streaming response.
    """
    if not is_groq_configured():
        logger.warning("GROQ_API_KEY not configured. Returning mock response.")
        return f"[Mock Groq Response] Groq API Key not configured. Prompt details: {messages[-1]['content'][:100]}..."

    retries = 3
    delay = 15
    for attempt in range(retries):
        try:
            client = get_groq_client()
            response = await client.chat.completions.create(
                model=settings.groq_model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens
            )
            return response.choices[0].message.content or ""
        except Exception as e:
            err_str = str(e)
            if "429" in err_str or "rate limit" in err_str.lower():
                logger.warning(f"Groq API rate limit hit. Retrying in {delay} seconds (Attempt {attempt+1}/{retries})... Error: {e}")
                import asyncio
                await asyncio.sleep(delay)
                delay *= 2
            else:
                logger.error(f"Error calling Groq API: {e}. Falling back to mock response.")
                return f"[Mock Groq Response - Fallback] I received your message. (Error: {e}). Prompt details: {messages[-1]['content'][:100]}..."
                
    logger.warning("Groq API rate limit exceeded. Falling back to mock response.")
    return f"[Mock Groq Response - Rate Limit Fallback] Groq API rate limit exceeded. Prompt details: {messages[-1]['content'][:100]}..."

async def get_chat_completion_stream(
    messages: List[Dict[str, str]], 
    temperature: float = 0.7,
    max_tokens: int = 1000
) -> AsyncGenerator[str, None]:
    """
    Queries Groq for streaming response.
    """
    if not is_groq_configured():
        logger.warning("GROQ_API_KEY not configured. Streaming mock response.")
        mock_resp = f"[Mock Groq Stream] Hello! Since your GROQ_API_KEY is not configured in .env, I am responding in offline mock mode."
        for word in mock_resp.split(" "):
            yield word + " "
            import asyncio
            await asyncio.sleep(0.05)
        return

    retries = 3
    delay = 15
    for attempt in range(retries):
        try:
            client = get_groq_client()
            response_stream = await client.chat.completions.create(
                model=settings.groq_model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                stream=True
            )
            async for chunk in response_stream:
                content = chunk.choices[0].delta.content
                if content:
                    yield content
            return
        except Exception as e:
            err_str = str(e)
            if "429" in err_str or "rate limit" in err_str.lower():
                if attempt < retries - 1:
                    logger.warning(f"Groq API stream rate limit hit. Retrying in {delay} seconds (Attempt {attempt+1}/{retries})... Error: {e}")
                    import asyncio
                    await asyncio.sleep(delay)
                    delay *= 2
                    continue
                else:
                    logger.warning("Groq API stream rate limit exceeded. Falling back to mock streaming.")
                    mock_resp = f"[Mock Groq Stream - Rate Limit Fallback] Hello! Since your Groq API key has exceeded its quota, I am responding in offline mock mode."
                    for word in mock_resp.split(" "):
                        yield word + " "
                        import asyncio
                        await asyncio.sleep(0.05)
                    return
            else:
                logger.error(f"Error calling Groq API Stream: {e}. Falling back to mock streaming.")
                mock_resp = f"[Mock Groq Stream - Fallback] Hello! Since there was an error calling the Groq API ({e}), I am responding in offline mock mode."
                for word in mock_resp.split(" "):
                    yield word + " "
                    import asyncio
                    await asyncio.sleep(0.05)
                return


