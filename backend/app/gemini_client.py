import logging
import random
from typing import List, Dict, Any, AsyncGenerator
from google import genai
from google.genai import types
from backend.app.config import settings

logger = logging.getLogger("mnemo.gemini")

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
    Generates a 768-dimensional embedding using Gemini's text-embedding-004 model.
    Falls back to mock embeddings if API key is not configured.
    """
    if not is_api_configured():
        logger.warning("GEMINI_API_KEY not configured. Generating mock 768-dim embedding.")
        random.seed(hash(text))
        return [random.uniform(-0.1, 0.1) for _ in range(768)]
    
    try:
        client = get_client()
        response = await client.aio.models.embed_content(
            model="text-embedding-004",
            contents=text
        )
        return response.embeddings[0].values
    except Exception as e:
        logger.error(f"Error calling Gemini Embedding API: {e}. Falling back to mock.")
        random.seed(hash(text))
        return [random.uniform(-0.1, 0.1) for _ in range(768)]

async def get_chat_completion(
    messages: List[Dict[str, str]], 
    temperature: float = 0.7,
    max_tokens: int = 1000
) -> str:
    """
    Queries gemini-2.5-flash for non-streaming response.
    """
    if not is_api_configured():
        logger.warning("GEMINI_API_KEY not configured. Returning mock assistant response.")
        return f"[Mock Gemini Response] I received your message. (API Key not configured in .env). System Prompt details: {messages[0]['content'][:100]}..."

    try:
        client = get_client()
        contents, system_instruction = format_messages(messages)
        config = types.GenerateContentConfig(
            temperature=temperature,
            max_output_tokens=max_tokens,
            system_instruction=system_instruction
        )
        
        response = await client.aio.models.generate_content(
            model="gemini-2.5-flash",
            contents=contents,
            config=config
        )
        return response.text or ""
    except Exception as e:
        logger.error(f"Error calling Gemini Chat API: {e}")
        return f"[Error from Gemini API: {e}]"

async def get_chat_completion_stream(
    messages: List[Dict[str, str]], 
    temperature: float = 0.7,
    max_tokens: int = 1000
) -> AsyncGenerator[str, None]:
    """
    Queries gemini-2.5-flash for streaming response.
    """
    if not is_api_configured():
        logger.warning("GEMINI_API_KEY not configured. Streaming mock response.")
        mock_resp = f"[Mock Gemini Stream] Hello! Since your GEMINI_API_KEY is not configured in .env, I am responding in offline mock mode. The context injected includes your Core Profile and retrieved episodic memories (if any)."
        for word in mock_resp.split(" "):
            yield word + " "
            import asyncio
            await asyncio.sleep(0.05)
        return

    try:
        client = get_client()
        contents, system_instruction = format_messages(messages)
        config = types.GenerateContentConfig(
            temperature=temperature,
            max_output_tokens=max_tokens,
            system_instruction=system_instruction
        )
        
        response_stream = await client.aio.models.generate_content_stream(
            model="gemini-2.5-flash",
            contents=contents,
            config=config
        )
        async for chunk in response_stream:
            if chunk.text:
                yield chunk.text
    except Exception as e:
        logger.error(f"Error calling Gemini Chat API Stream: {e}")
        yield f"\n[Error from Gemini API: {e}]"
