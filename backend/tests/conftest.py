import os
import tempfile

# API tests get their own throwaway database and never reach a live provider,
# whatever the developer's local .env says. Must run before app modules import.
_tmp_db = os.path.join(tempfile.mkdtemp(prefix="aslioffer-test-"), "test.db")
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp_db}"
os.environ["SERPAPI_API_KEY"] = ""
os.environ["GEMINI_API_KEY"] = ""
os.environ["GROQ_API_KEY"] = ""
os.environ["SEARCH_DEMO_MODE"] = "false"
