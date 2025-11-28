import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class EmailAddress(BaseModel):
    name: Optional[str] = None
    address: str


class Recipient(BaseModel):
    emailAddress: EmailAddress


class Email(BaseModel):
    id: str
    receivedDateTime: datetime.datetime
    subject: str
    sender: Recipient
    from_address: Optional[Recipient] = Field(None, alias="from")
    bodyPreview: str
    body: dict  # OData 'body' is complex
    isRead: bool
    webLink: str


class MailQueryResponse(BaseModel):
    odata_context: str = Field(..., alias="@odata.context")
    value: List[Email]
    odata_nextLink: Optional[str] = Field(None, alias="@odata.nextLink")
