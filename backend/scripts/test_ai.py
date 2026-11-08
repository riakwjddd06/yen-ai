# backend/scripts/test_ai.py
import os
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

client = OpenAI(
    api_key=os.getenv("OPENAI_API_KEY"),
    base_url=os.getenv("OPENAI_BASE_URL"),
)

resp = client.chat.completions.create(
    model=os.getenv("OPENAI_MODEL"),
    messages=[{"role": "user", "content": "한 문장으로 인사해줘"}],
    max_completion_tokens=500,
)

print("답변:", resp.choices[0].message.content)
print("사용량:", resp.usage)