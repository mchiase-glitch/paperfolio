import json
from datetime import date, datetime, timezone
from decimal import Decimal

from fastapi.encoders import ENCODERS_BY_TYPE
from fastapi.responses import JSONResponse

# FastAPI di serie trasforma i Decimal in float prima della risposta: li vogliamo come stringhe esatte
ENCODERS_BY_TYPE[Decimal] = str


def _default(value):
    if isinstance(value, Decimal):
        return str(value)  # stringa: nessuna perdita di precisione verso il browser
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    raise TypeError(f"Tipo non serializzabile: {type(value)}")


class DecimalJSONResponse(JSONResponse):
    def render(self, content) -> bytes:
        return json.dumps(content, default=_default, ensure_ascii=False).encode("utf-8")
