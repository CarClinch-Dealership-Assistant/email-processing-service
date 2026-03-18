from .providers.smtp import GmailProvider
from .providers.acs import AcsProvider
from .providers.graph import GraphProvider
from .protocol import EmailProvider

class EmailFactory:
    _map = {
        "gmail": GmailProvider,
        "acs": AcsProvider,
        "graph": GraphProvider
    }

    @classmethod
    def get_provider(cls, name: str) -> EmailProvider:
        return cls._map.get(name.lower())()