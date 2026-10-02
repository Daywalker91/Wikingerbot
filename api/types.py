"""Gemeinsame Typen fuer die API-Modelle."""

from typing import Annotated

from pydantic import PlainSerializer

# Discord-IDs (Snowflakes) sind bis zu 19 Stellen lang - JavaScript kann Zahlen
# nur bis 2^53 exakt darstellen und rundet sie sonst (1523404561895784448 wird zu
# ...400). Darum gehen sie als Text raus; rein kommen Text oder Zahl.
Snowflake = Annotated[int, PlainSerializer(lambda value: str(value), return_type=str, when_used="json")]
