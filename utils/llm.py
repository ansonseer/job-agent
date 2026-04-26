"""
LLM Utility - Wrapper for Claude API calls
Handles all LLM interactions with error handling and cost tracking.
"""

import anthropic
import json
import time
from config import ANTHROPIC_API_KEY, LLM_CONFIG


def create_client():
    """Create Anthropic client."""
    return anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


# Simple token/cost tracker
_usage_log = {"total_input_tokens": 0, "total_output_tokens": 0, "calls": 0}


def call_llm(prompt: str, system: str = "", model: str = None, 
             max_tokens: int = None, temperature: float = None,
             expect_json: bool = False) -> str:
    """
    Call Claude API with error handling and retry logic.
    
    Args:
        prompt: User message
        system: System prompt
        model: Model to use (defaults to config)
        max_tokens: Max output tokens
        temperature: Sampling temperature
        expect_json: If True, strips markdown fences from response
    
    Returns:
        Response text (str) or parsed JSON (dict) if expect_json=True
    """
    client = create_client()
    model = model or LLM_CONFIG["intel_model"]
    max_tokens = max_tokens or LLM_CONFIG["max_tokens"]
    temperature = temperature if temperature is not None else LLM_CONFIG["temperature"]
    
    for attempt in range(3):
        try:
            message = client.messages.create(
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                system=system if system else "You are a helpful assistant.",
                messages=[{"role": "user", "content": prompt}]
            )
            
            response_text = message.content[0].text
            
            # Track usage
            _usage_log["total_input_tokens"] += message.usage.input_tokens
            _usage_log["total_output_tokens"] += message.usage.output_tokens
            _usage_log["calls"] += 1
            
            if expect_json:
                # Clean markdown fences if present
                cleaned = response_text.strip()
                if cleaned.startswith("```json"):
                    cleaned = cleaned[7:]
                if cleaned.startswith("```"):
                    cleaned = cleaned[3:]
                if cleaned.endswith("```"):
                    cleaned = cleaned[:-3]
                return json.loads(cleaned.strip())
            
            return response_text
            
        except anthropic.RateLimitError:
            print(f"  ⚠️ Rate limited, waiting 30s... (attempt {attempt+1}/3)")
            time.sleep(30)
        except anthropic.APIError as e:
            print(f"  ❌ API Error: {e}")
            if attempt == 2:
                raise
            time.sleep(5)
        except json.JSONDecodeError as e:
            if expect_json:
                print(f"  ⚠️ JSON parse failed, retrying... (attempt {attempt+1}/3)")
                if attempt == 2:
                    print(f"  Raw response: {response_text[:500]}")
                    raise
            else:
                return response_text
    
    return None


def get_usage_report() -> dict:
    """Return cumulative API usage stats."""
    input_cost = _usage_log["total_input_tokens"] / 1_000_000 * 3    # Sonnet pricing
    output_cost = _usage_log["total_output_tokens"] / 1_000_000 * 15  # Sonnet pricing
    return {
        **_usage_log,
        "estimated_cost_usd": round(input_cost + output_cost, 4),
    }


def print_usage():
    """Print current usage stats."""
    report = get_usage_report()
    print(f"\n📊 API Usage: {report['calls']} calls | "
          f"{report['total_input_tokens']:,} in / {report['total_output_tokens']:,} out | "
          f"~${report['estimated_cost_usd']:.4f} USD")
