from mediawords.util.config import env_value


class CrawlerConfig(object):
    """Crawler configuration."""

    @staticmethod
    def univision_client_id() -> str:
        """"Univision API client ID."""
        return env_value('MC_UNIVISION_CLIENT_ID')

    @staticmethod
    def univision_client_secret() -> str:
        """Univision API client secret (secret key)."""
        return env_value('MC_UNIVISION_CLIENT_SECRET')
