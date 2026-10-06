from uuid import UUID

from fastapi import APIRouter, Response

from ...application.models import ConversationDetail, ConversationSummary
from ..dependencies import ChatDep, PrincipalDep

router = APIRouter(prefix="/api/conversations", tags=["conversations"])


@router.get("", response_model=list[ConversationSummary], response_model_by_alias=True)
async def list_conversations(principal: PrincipalDep, service: ChatDep) -> list[ConversationSummary]:
    return await service.list_conversations(principal)


@router.get("/{conversation_id}", response_model=ConversationDetail, response_model_by_alias=True)
async def get_conversation(
    conversation_id: UUID, principal: PrincipalDep, service: ChatDep
) -> ConversationDetail:
    return await service.get_conversation(principal, conversation_id)


@router.delete("/{conversation_id}", status_code=204)
async def delete_conversation(conversation_id: UUID, principal: PrincipalDep, service: ChatDep) -> Response:
    await service.delete_conversation(principal, conversation_id)
    return Response(status_code=204)
