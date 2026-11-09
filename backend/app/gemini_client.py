import logging
import random
from typing import List, Dict, Any, AsyncGenerator
from google import genai
from google.genai import types
from backend.app.config import settings

logger = logging.getLogger("amnesia.gemini")

def get_client() -> genai.Client:
    return genai.Client(
        api_key=settings.gemini_api_key,
        http_options=types.HttpOptions(api_version="v1beta")
    )

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

async def get_embedding(text: str, task_type: str = "RETRIEVAL_DOCUMENT") -> List[float]:
    """
    Generates a 768-dimensional embedding using Gemini's gemini-embedding-2 model.
    Supports asymmetric task_type ('RETRIEVAL_DOCUMENT' vs 'RETRIEVAL_QUERY') for sharper RAG separation.
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
                config=types.EmbedContentConfig(
                    output_dimensionality=768,
                    task_type=task_type,
                )
            )
            return response.embeddings[0].values
        except Exception as e:
            err_str = str(e)
            if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str or "quota" in err_str.lower():
                logger.warning(f"Gemini Embedding API rate limit hit. Retrying in {delay} seconds (Attempt {attempt+1}/{retries})... Error: {e}")
                import asyncio
                await asyncio.sleep(delay)
                delay *= 2
            elif any(k in err_str for k in ("SSL", "EOF", "Connection", "Timeout", "timeout", "503", "502", "500")) and attempt < retries - 1:
                logger.warning(f"Transient error calling Gemini Embedding API. Retrying in 1.5s (Attempt {attempt+1}/{retries})... Error: {e}")
                import asyncio
                await asyncio.sleep(1.5)
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

async def _gemini_chat_fallback(
    messages: List[Dict[str, str]],
    temperature: float = 0.7,
    max_tokens: int = 1000,
) -> str:
    if not is_api_configured():
        return f"[Mock Groq Response] Groq/Gemini API Key not configured. Prompt details: {messages[-1]['content'][:100]}..."
    try:
        client = get_client()
        contents, system_instruction = format_messages(messages)
        config = types.GenerateContentConfig(
            temperature=temperature,
            max_output_tokens=max_tokens,
            system_instruction=system_instruction,
        )
        resp = await client.aio.models.generate_content(
            model=settings.gemini_model,
            contents=contents,
            config=config,
        )
        return resp.text or ""
    except Exception as e:
        logger.error(f"Gemini fallback also failed: {e}")
        return f"[Mock Groq Response - Fallback] I received your message. (Error: {e}). Prompt details: {messages[-1]['content'][:100]}..."

GROQ_FALLBACK_MODELS = ["qwen/qwen3.8-27b", "openai/gpt-oss-120b", "llama-3.3-70b-versatile"]

async def _groq_create_with_model_fallback(client, messages, temperature, max_tokens, stream=False):
    """
    Tries the configured model first; if 404/model_not_found, tries known alternative Groq models.
    """
    models_to_try = [settings.groq_model] + [m for m in GROQ_FALLBACK_MODELS if m != settings.groq_model]
    last_err = None
    for model_name in models_to_try:
        try:
            return await client.chat.completions.create(
                model=model_name,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                stream=stream
            )
        except Exception as e:
            err_str = str(e)
            if "404" in err_str or "model_not_found" in err_str or "does not exist" in err_str:
                logger.warning(f"Groq model '{model_name}' not available on this account. Trying next fallback...")
                last_err = e
                continue
            raise e
    raise last_err

async def get_chat_completion(
    messages: List[Dict[str, str]], 
    temperature: float = 0.7,
    max_tokens: int = 1000
) -> str:
    """
    Queries Groq for non-streaming response, falling back to Gemini if Groq is unconfigured or errors.
    """
    if not is_groq_configured():
        logger.warning("GROQ_API_KEY not configured. Falling back to Gemini.")
        return await _gemini_chat_fallback(messages, temperature=temperature, max_tokens=max_tokens)

    retries = 3
    delay = 15
    for attempt in range(retries):
        try:
            client = get_groq_client()
            response = await _groq_create_with_model_fallback(
                client=client,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                stream=False
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
                logger.warning(f"Error calling Groq API ({e}). Falling back to Gemini.")
                return await _gemini_chat_fallback(messages, temperature=temperature, max_tokens=max_tokens)
                
    logger.warning("Groq API rate limit exceeded. Falling back to Gemini.")
    return await _gemini_chat_fallback(messages, temperature=temperature, max_tokens=max_tokens)

async def get_chat_completion_stream(
    messages: List[Dict[str, str]], 
    temperature: float = 0.7,
    max_tokens: int = 1000
) -> AsyncGenerator[str, None]:
    """
    Queries Groq for streaming response, falling back to Gemini if Groq is unconfigured or errors.
    """
    if not is_groq_configured():
        logger.warning("GROQ_API_KEY not configured. Falling back to Gemini for stream.")
        text = await _gemini_chat_fallback(messages, temperature=temperature, max_tokens=max_tokens)
        for word in text.split(" "):
            yield word + " "
            import asyncio
            await asyncio.sleep(0.02)
        return

    retries = 3
    delay = 15
    for attempt in range(retries):
        try:
            client = get_groq_client()
            response_stream = await _groq_create_with_model_fallback(
                client=client,
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
                    logger.warning("Groq API stream rate limit exceeded. Falling back to Gemini.")
                    text = await _gemini_chat_fallback(messages, temperature=temperature, max_tokens=max_tokens)
                    for word in text.split(" "):
                        yield word + " "
                        import asyncio
                        await asyncio.sleep(0.02)
                    return
            else:
                logger.warning(f"Error calling Groq API Stream ({e}). Falling back to Gemini.")
                text = await _gemini_chat_fallback(messages, temperature=temperature, max_tokens=max_tokens)
                for word in text.split(" "):
                    yield word + " "
                    import asyncio
                    await asyncio.sleep(0.02)
                return


