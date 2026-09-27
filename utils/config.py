import os
from dotenv import load_dotenv

load_dotenv()

API_BASE_URL = os.getenv("API_BASE_URL", "https://fixed-marita-invico-d13e43fa.koyeb.app")
