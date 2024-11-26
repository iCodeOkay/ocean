import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import httpx
from typing import AsyncGenerator
from port_ocean.context.event import event
from port_ocean.context.event import event_context
from port_ocean.exceptions.context import PortOceanContextAlreadyInitializedError
from port_ocean.context.ocean import initialize_port_ocean_context
from snyk.client import SnykClient
from aiolimiter import AsyncLimiter


@pytest.fixture(autouse=True)
def mock_ocean_context() -> None:
    try:
        mock_ocean_app = MagicMock()
        mock_ocean_app.config.integration.config = {
            "organization_url": "https://test.com",
            "token": "test-token",
        }
        mock_ocean_app.integration_router = MagicMock()
        mock_ocean_app.port_client = MagicMock()
        initialize_port_ocean_context(mock_ocean_app)
    except PortOceanContextAlreadyInitializedError:
        pass


class TestSnykClientUserDetails:
    @pytest.fixture
    async def snyk_client(self) -> AsyncGenerator[SnykClient, None]:
        mock_send_api_request = AsyncMock()

        with patch.object(SnykClient, "_send_api_request", mock_send_api_request):
            client = SnykClient(
                token="test-token",
                api_url="https://api.test.com",
                app_host=None,
                organization_ids=["org123"],
                group_ids=None,
                webhook_secret=None,
                rate_limiter=AsyncLimiter(5, 1),
            )

            client._send_api_request = mock_send_api_request  # type: ignore
            yield client

    @pytest.fixture
    async def mock_event_context(self) -> AsyncGenerator[MagicMock, None]:
        """Create a mock event context for tests"""
        mock_event = MagicMock()
        mock_event.attributes = {}

        with patch("port_ocean.context.event.event", mock_event):
            yield mock_event

    @pytest.mark.asyncio
    async def test_none_user_reference(
        self, snyk_client: SnykClient, mock_event_context: MagicMock
    ) -> None:
        """Test handling of None user reference"""
        async with event_context("test_event"):
            result = await snyk_client._get_user_details(None)
            assert result == {}
            snyk_client._send_api_request.assert_not_called()  # Changed from .called

    @pytest.mark.asyncio
    async def test_user_from_different_org(
        self, snyk_client: SnykClient, mock_event_context: MagicMock
    ) -> None:
        """Test handling of user from non-configured organization"""
        async with event_context("test_event"):
            # Arrange
            user_reference = "/rest/orgs/different_org/users/user123"

            # Act
            result = await snyk_client._get_user_details(user_reference)

            # Assert
            assert result == {}
            snyk_client._send_api_request.assert_not_called()

    @pytest.mark.asyncio
    async def test_cached_user_details(
        self, snyk_client: SnykClient, mock_event_context: MagicMock
    ) -> None:
        """Test retrieval of cached user details"""
        async with event_context("test_event"):
            # Arrange
            user_id = "user123"
            user_reference = f"/rest/orgs/org123/users/{user_id}"
            cached_data = {"data": {"id": user_id, "name": "Test User"}}
            event.attributes[f"user-{user_id}"] = cached_data

            # Act
            result = await snyk_client._get_user_details(user_reference)

            # Assert
            assert result == cached_data
            snyk_client._send_api_request.assert_not_called()

    @pytest.mark.asyncio
    async def test_successful_user_details_fetch(
        self, snyk_client: SnykClient, mock_event_context: MagicMock
    ) -> None:
        async with event_context("test_event"):
            # Arrange
            user_id = "user123"
            user_reference = f"/rest/orgs/org123/users/{user_id}"
            api_response = {"data": {"id": user_id, "name": "Test User"}}
            snyk_client._send_api_request.return_value = api_response

            # Act
            result = await snyk_client._get_user_details(user_reference)

            # Assert
            assert result == api_response["data"]
            snyk_client._send_api_request.assert_called_once_with(
                url=f"https://api.test.com/rest/orgs/org123/users/{user_id}",
                query_params={"version": "2024-06-21~beta"},
            )
            assert event.attributes[f"user-{user_id}"] == api_response

    @pytest.mark.asyncio
    async def test_404_error_handling(
        self, snyk_client: SnykClient, mock_event_context: MagicMock
    ) -> None:
        async with event_context("test_event"):
            # Arrange
            user_reference = "/rest/orgs/org123/users/user123"
            mock_response = MagicMock(spec=httpx.Response)
            mock_response.status_code = 404
            error = httpx.HTTPStatusError(
                "Not Found",
                request=MagicMock(spec=httpx.Request),
                response=mock_response,
            )
            snyk_client._send_api_request.side_effect = error

            # Act
            result = await snyk_client._get_user_details(user_reference)

            # Assert
            assert result == {}

    @pytest.mark.asyncio
    async def test_non_404_error_handling(
        self, snyk_client: SnykClient, mock_event_context: MagicMock
    ) -> None:
        async with event_context("test_event"):
            # Arrange
            user_reference = "/rest/orgs/org123/users/user123"
            mock_response = MagicMock(spec=httpx.Response)
            mock_response.status_code = 500
            error = httpx.HTTPStatusError(
                "Server Error",
                request=MagicMock(spec=httpx.Request),
                response=mock_response,
            )
            snyk_client._send_api_request.side_effect = error

            # Act/Assert
            with pytest.raises(httpx.HTTPStatusError):
                await snyk_client._get_user_details(user_reference)

    @pytest.mark.asyncio
    async def test_empty_api_response(
        self, snyk_client: SnykClient, mock_event_context: MagicMock
    ) -> None:
        async with event_context("test_event"):
            # Arrange
            user_reference = "/rest/orgs/org123/users/user123"
            snyk_client._send_api_request.return_value = None

            # Act
            result = await snyk_client._get_user_details(user_reference)

            # Assert
            assert result == {}
