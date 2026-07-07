#!/usr/bin/env python
import os

from dotenv import load_dotenv
from openai import OpenAI


def main():
    load_dotenv()

    api_key = os.getenv("TRIPPILOT_LLM_API_KEY")
    model = os.getenv("TRIPPILOT_LLM_MODEL", "Pro/deepseek-ai/DeepSeek-R1")
    base_url = os.getenv("TRIPPILOT_LLM_BASE_URL", "https://api.siliconflow.cn/v1")

    if not api_key:
        raise SystemExit("Missing TRIPPILOT_LLM_API_KEY. Please fill it in .env first.")

    client = OpenAI(api_key=api_key, base_url=base_url)
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": "请用一句话回答：你是谁？"}],
        stream=True,
        max_tokens=256,
    )

    for chunk in response:
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta
        reasoning = getattr(delta, "reasoning_content", None)
        if reasoning:
            print(reasoning, end="", flush=True)
        if delta.content:
            print(delta.content, end="", flush=True)
    print()


if __name__ == "__main__":
    main()
