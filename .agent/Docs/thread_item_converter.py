"""
Extend ThreadItemConverter when your integration supports:

Attachments
@-mentions (entity tagging)
HiddenContextItem
Custom thread item formats
"""

from agents import Message, Runner, ResponseInputTextParam
from chatkit.agents import AgentContext, ThreadItemConverter, stream_agent_response
from chatkit.types import Attachment, HiddenContextItem, ThreadMetadata, UserMessageItem


class MyThreadConverter(ThreadItemConverter):
    async def attachment_to_message_content(
        self, attachment: Attachment
    ) -> ResponseInputTextParam:
        content = await attachment_store.get_attachment_contents(attachment.id)
        data_url = "data:%s;base64,%s" % (mime, base64.b64encode(raw).decode("utf-8"))
        if isinstance(attachment, ImageAttachment):
            return ResponseInputImageParam(
                type="input_image",
                detail="auto",
                image_url=data_url,
            )

        # ..handle other attachment types

    def hidden_context_to_input(self, item: HiddenContextItem) -> Message:
        return Message(
            type="message",
            role="system",
            content=[
                ResponseInputTextParam(
                    type="input_text",
                    text=f"<HIDDEN_CONTEXT>{item.content}</HIDDEN_CONTEXT>",
                )
            ],
        )

    def tag_to_message_content(self, tag: UserMessageTagContent):
        tag_context = await retrieve_context_for_tag(tag.id)
        return ResponseInputTextParam(
            type="input_text",
            text=f"<TAG>Name:{tag.data.name}\nType:{tag.data.type}\nDetails:{tag_context}</TAG>"
        )

        # ..handle other @-mentions

    # ..override defaults for other methods
