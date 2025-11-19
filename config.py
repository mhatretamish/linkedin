from typing import List
import random


class Config:
    # API Configuration
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    API_PREFIX: str = "/api/v1"
    DEBUG: bool = True

    # Cache Configuration
    CACHE_TTL_SECONDS: int = 1800  # 30 minutes default
    CACHE_MAX_SIZE: int = 1000     # Maximum number of cached items

    # Rate Limiting
    MAX_REQUESTS_PER_MINUTE: int = 30
    REQUEST_DELAY_MIN: float = 0.5   # Minimum delay between requests (reduced for better performance)
    REQUEST_DELAY_MAX: float = 1.5   # Maximum delay between requests (reduced for better performance)

    # Retry Configuration
    MAX_RETRIES: int = 1  # Reduced for faster response times
    RETRY_DELAY: float = 2.0  # Reduced from 5.0 seconds
    BACKOFF_FACTOR: float = 2.0

    # Session Configuration
    SESSION_TIMEOUT: int = 300      # 5 minutes
    SESSION_POOL_SIZE: int = 5      # Number of concurrent sessions

    # Threading Configuration
    MAX_WORKERS: int = 10           # Maximum worker threads for concurrent processing
    MAX_QUEUE_SIZE: int = 100       # Maximum queue size for pending requests
    BATCH_MAX_SIZE: int = 50        # Maximum URLs in a single batch request
    STREAM_BUFFER_SIZE: int = 20    # Buffer size for streaming requests
    REQUEST_TIMEOUT: int = 30       # Timeout per request in seconds

    # LinkedIn Configuration
    LINKEDIN_BASE_URL: str = "https://www.linkedin.com"
    COOKIES_FILE: str = "cookies.json"

    # Proxy Configuration
    PROXY_ENABLED: bool = False  # Disabled for better performance
    PROXY_URL: str = "http://priyanshujhawar03-6f9c1fa0:GMOVF_w1rzRcij8G1F_JSfovPHG5rSnmUC81b7BODog@15.237.177.183:3000"
    PROXY_ROTATION: bool = False


    # TLS Client Identifiers
    TLS_CLIENT_IDENTIFIERS: List[str] = [
        "chrome_140"
    ]

    @classmethod
    def get_random_user_agent(cls) -> str:
        from fake_useragent import UserAgent
        ua = UserAgent()
        return ua.random

    @classmethod
    def get_random_tls_identifier(cls) -> str:
        return random.choice(cls.TLS_CLIENT_IDENTIFIERS)

    @classmethod
    def get_random_delay(cls) -> float:
        return random.uniform(cls.REQUEST_DELAY_MIN, cls.REQUEST_DELAY_MAX)


# Global config instance
config = Config()