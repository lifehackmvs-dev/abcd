from dishka import Provider, Scope, provide
from httpx import AsyncClient, Timeout
from loguru import logger
from remnapy import RemnawaveSDK

from src.core.config import AppConfig


class RemnawaveProvider(Provider):
    scope = Scope.APP

    @provide
    def get_remnawave(self, config: AppConfig) -> RemnawaveSDK:
        logger.debug("Initializing RemnawaveSDK")

        headers = {}
        headers["Authorization"] = f"Bearer {config.keystonewave.token.get_secret_value()}"
        headers["X-Api-Key"] = config.keystonewave.caddy_token.get_secret_value()

        if not config.keystonewave.is_external:
            headers["x-forwarded-proto"] = "https"
            headers["x-forwarded-for"] = "127.0.0.1"

        client = AsyncClient(
            base_url=f"{config.keystonewave.url.get_secret_value()}/api",
            headers=headers,
            cookies=config.keystonewave.cookies,
            verify=True,
            timeout=Timeout(connect=15.0, read=25.0, write=10.0, pool=5.0),
        )

        return RemnawaveSDK(client)
