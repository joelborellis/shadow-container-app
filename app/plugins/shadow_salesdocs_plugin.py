from typing import Annotated
from semantic_kernel.functions.kernel_function_decorator import kernel_function
from ..tools.searchshadow import SearchShadow



class ShadowSalesDocsPlugin:

    def __init__(
        self,
        search_shadow_client: SearchShadow,
    ):
        """
        :param search_shadow_client: A SearchShadow client used for shadow index searches.
        :param search_customer_client: A SearchCustomer client used for customer index searches.
        """
        self.search_shadow_client = search_shadow_client

    @kernel_function(
        name="get_sales_docs",
        description="Given a user query determine if the users request involves sales strategy or methodology.",
    )
    async def get_sales_docs(
        self, query: Annotated[str, "The query from the user."]
    ) -> Annotated[str, "Returns documents from the sales index."]:
        try:
            # Ensure query is valid
            if not isinstance(query, str) or not query.strip():
                raise ValueError("The query must be a non-empty string.")

            # Perform the search
            docs = await self.search_shadow_client.search_hybrid(query)
            if not docs:
                return "No relevant documents found in the sales index."
            return docs
        except ValueError as ve:
            return f"Input error: {ve}"
        except Exception as e:
            return f"An error occurred while retrieving documents from the sales index: {e}"
