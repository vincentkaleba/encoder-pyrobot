from pyrogram import Client, filters
from pyrogram.types import Message
from pyrogram.filters import video, document
from isocode.utils.isoutils.encoder import encoder_flow
from isocode.utils.isoutils.progress import stylize_value

async def handle_video(client: Client, message: Message):
    if not message.video and not (
        message.document and
        message.document.mime_type and
        message.document.mime_type.startswith("video/")
    ):
        return await message.reply(stylize_value("❌ Veuillez envoyer un fichier vidéo."))

    msg = await message.reply(stylize_value("⏳ Traitement du fichier vidéo en cours..."))

    try:
        from isocode.utils.telegram.clients import clients
        userbot = clients.get_client("userbot")

        await encoder_flow(message=message, msg=msg, userbot=userbot, client=client)

    except Exception as e:
        await msg.edit(f"❌ Une erreur est survenue : `{e}`")
