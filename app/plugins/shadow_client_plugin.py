from typing import Annotated
from semantic_kernel.functions.kernel_function_decorator import kernel_function
from ..tools.searchclient import SearchUser


class ShadowClientPlugin:

    def __init__(
        self,
        search_user_client: SearchUser,
    ):
        """
        :param search_user_client: A SearchUser client used for client index searches.
        """
        self.search_user_client = search_user_client


    @kernel_function(
        name="get_client_docs",
        description="Given a user query determine if the users request involves the users company known as the client.",
    )
    async def get_client_docs(
        self,
        query: Annotated[
            str,
            "The query and the name of the company the user represents known as the client.",
        ],
        ClientId: Annotated[str, "The client ID [ClientId] of the client company."],
        ClientName: Annotated[str, "The name [ClientName] of the company the user represents."],
    ) -> Annotated[str, "Returns documents from the pursuit index."]:
        try:
            # Ensure query is valid
            if not isinstance(query, str) or not query.strip():
                raise ValueError("The query must be a non-empty string.")

            # Perform the search
            docs = await self.search_user_client.search_hybrid(query, ClientId, ClientName)
            if not docs:
                return "No relevant documents found in the user index."
            return docs
        except ValueError as ve:
            return f"Input error: {ve}"
        except Exception as e:
            return (
                f"An error occurred while retrieving documents from the user index: {e}"
            )
