import os
import aiohttp
from openai import AsyncOpenAI, OpenAIError
from dotenv import load_dotenv
from .utils.clean_text import clean_text

load_dotenv()


class SearchCustomer:
    def __init__(self):
        try:
            AZURE_SEARCH_ENDPOINT = os.environ.get("AZURE_SEARCH_ENDPOINT")
            AZURE_SEARCH_ADMIN_KEY = os.environ.get("AZURE_SEARCH_ADMIN_KEY")
            AZURE_SEARCH_INDEX_CUSTOMER = os.environ.get("AZURE_SEARCH_INDEX_CUSTOMER")
            OPENAI_EMBED_MODEL = os.environ.get("OPENAI_EMBED_MODEL")

            if (
                not AZURE_SEARCH_ENDPOINT
                or not AZURE_SEARCH_ADMIN_KEY
                or not AZURE_SEARCH_INDEX_CUSTOMER
                or not OPENAI_EMBED_MODEL
            ):
                raise EnvironmentError(
                    "Missing one or more environment variables required for initialization."
                )

            self.endpoint = AZURE_SEARCH_ENDPOINT
            self.index = AZURE_SEARCH_INDEX_CUSTOMER
            self.admin_key = AZURE_SEARCH_ADMIN_KEY
            self.model = OPENAI_EMBED_MODEL
            self.openai_client = AsyncOpenAI()

            print(
                f"[SearchCustomer]:  Init SearchCustomer for index - {AZURE_SEARCH_INDEX_CUSTOMER}"
            )
        except Exception as e:
            raise RuntimeError(f"Error initializing SearchCustomer: {e}")

    async def get_embedding(self, text, model):
        try:
            text = text.replace("\n", " ")
            resp = await self.openai_client.embeddings.create(input=[text], model=model)
            return resp.data[0].embedding
        except OpenAIError as ai_err:
            ai_response_msg = ai_err.body["message"]
            print(ai_response_msg)
            return None

    async def search_hybrid(self, query: str, AccountName: str) -> str:
        try:
            #print(f"[SearchCustomer] Searching hybrid for query: {query} and AccountName: {AccountName}")
            #print(f"[SearchCustomer] Using index: {self.index}")
            combined_text = f"{query} {AccountName}"
            vector = await self.get_embedding(combined_text, self.model)
            if not vector:
                return "No results found."
            url = f"{self.endpoint}/indexes/{self.index}/docs/search?api-version=2025-05-01-Preview"
            headers = {
                "Content-Type": "application/json",
                "api-key": self.admin_key,
            }
            payload = {
                "search": combined_text,
                "vectorQueries": [
                    {
                        "kind": "vector",
                        "vector": vector,
                        "k": 5,
                        "fields": "text_vector",
                    }
                ],
                "select": "title,chunk",
                "top": 5,
            }
            async with aiohttp.ClientSession() as session:
                async with session.post(url, headers=headers, json=payload) as resp:
                    if resp.status != 200:
                        error_body = await resp.text()
                        print(f"[AzureSearch] Request payload: {payload}")
                        print(f"[AzureSearch] Response body: {error_body}")
                        return f"Azure Search error: {resp.status}"
                    data = await resp.json()
                    docs = data.get("value", [])
                    if not docs:
                        return "No results found."
                    results = [f"{doc['title']}:  {clean_text(doc['chunk'])}" for doc in docs]
                    #print(f"[SearchCustomer] Found {results} results.")
                    return "\n".join(results)
        except Exception as e:
            return f"Error performing hybrid search: {e}"
