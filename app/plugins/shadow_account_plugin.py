from typing import Annotated
from semantic_kernel.functions.kernel_function_decorator import kernel_function
from ..tools.searchshadow import SearchShadow
from ..tools.searchcustomer import SearchCustomer
from ..tools.searchclient import SearchUser


class ShadowAccountPlugin:

    def __init__(
        self,
        search_customer_client: SearchCustomer,
    ):
        """
        :param search_shadow_client: A SearchShadow client used for shadow index searches.
        :param search_customer_client: A SearchCustomer client used for customer index searches.
        """
        self.search_customer_client = search_customer_client


    @kernel_function(
        name="get_customer_docs",
        description="Given a user query determine the users request involves a target account [target_account]",
    )
    async def get_customer_docs(
        self,
        query: Annotated[
            str,
            "The query and the target account [target_account] name provided by the user.",
        ],
        AccountName: Annotated[str, "The name [AccountName] of the target account."],
    ) -> Annotated[str, "Returns documents from the pursuit index."]:
        try:
            # Ensure query is valid
            if not isinstance(query, str) or not query.strip():
                raise ValueError("The query must be a non-empty string.")

            # Perform the search
            docs = await self.search_customer_client.search_hybrid(query, AccountName)
            if not docs:
                return "No relevant documents found in the pursuit index."
            return docs
        except ValueError as ve:
            return f"Input error: {ve}"
        except Exception as e:
            return f"An error occurred while retrieving documents from the pursuit index: {e}"
