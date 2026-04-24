import os
from dotenv import load_dotenv

load_dotenv()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
NAVER_CLIENT_ID = os.getenv("NAVER_CLIENT_ID", "")
NAVER_CLIENT_SECRET = os.getenv("NAVER_CLIENT_SECRET", "")

CLAUDE_MODEL = "claude-sonnet-4-6"

SUPPORTED_CATEGORIES = [
    "문구류",
    "애완용품",
    "뷰티/잡화",
    "생활용품",
    "인테리어소품",
    "패션잡화",
    "스포츠/레저용품",
    "취미/DIY",
]
