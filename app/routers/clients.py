from fastapi import APIRouter, Depends, Path

from app.auth import require_api_key
from app.data import CLIENTS, CLIENTS_BY_ID
from app.errors import APIError
from app.models import Client, ClientList
from app.routers.common import v1_responses

router = APIRouter(prefix="/v1/clients", tags=["clients"], dependencies=[Depends(require_api_key)])


def get_client_or_404(client_id: str) -> dict:
    client = CLIENTS_BY_ID.get(client_id)
    if client is None:
        raise APIError(404, "client_not_found", f"No client with id {client_id}")
    return client


@router.get(
    "",
    response_model=ClientList,
    summary="List clients",
    description="Returns every client account. This list is short, so it is not paginated.",
    responses=v1_responses(),
)
async def list_clients():
    return {"data": CLIENTS}


@router.get(
    "/{client_id}",
    response_model=Client,
    summary="Get one client",
    description="Returns a single client by id. An unknown id returns 404 `client_not_found`.",
    responses=v1_responses(404),
)
async def get_client(client_id: str = Path(description="Client id.", examples=["CL-001"])):
    return get_client_or_404(client_id)
