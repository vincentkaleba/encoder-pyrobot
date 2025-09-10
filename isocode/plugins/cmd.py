from pyrogram import Client, filters
from pyrogram.enums import ParseMode
from pyrogram import enums
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from isocode.utils.isoutils.progress import stylize_value
from isocode import settings, logger
from isocode.utils.telegram.keyboard import (
    create_web_kb,
    create_inline_kb,
    concat_kbs,
)
from isocode.utils.telegram.message import (
    send_msg,
    send_log,
)
from isocode.utils.telegram.media import (
    send_media,
    edit_media_caption,
)
from isocode.utils.telegram.clients import clients, shutdown_clients
from isocode.utils.isoutils.msg import BotMessage
from isocode.utils.isoutils.dbutils import (
    if_user_exist,
    add_user,
    set_admin_status,
    set_auth_chat,
    total_users_count,
    get_or_create_user
)
import time
import psutil
from datetime import datetime
import sys


# Filtres personnalisés
async def user_filter(_, __, message: Message):
    """Filtre pour les utilisateurs enregistrés"""
    return await if_user_exist(message.from_user.id)


def admin_filter(_, __, message: Message):
    """Filtre pour les administrateurs"""
    logger.debug(f"Admin: {message.from_user.id} - SUDO: {settings.SUDO_USERS}")
    return str(message.from_user.id) in settings.SUDO_USERS


def sudo_filter(_, __, message: Message):
    """Filtre pour les super-utilisateurs"""
    logger.debug(f"Admin: {message.from_user.id} - SUDO: {settings.SUDO_USERS}")
    return message.from_user.id in settings.SUDO_USERS


close_kb = create_inline_kb([[("↩ ʀᴇᴛᴏᴜʀ ", "start"), ("❌ ᴄʟᴏsᴇ", "close")]])

# Création des filtres
user = filters.create(user_filter)
admin = filters.create(admin_filter)
sudo = filters.create(sudo_filter)

BOT_CMD = [
    "start",
    "help",
    "settings",
    "status",
    "ping",
    "logs",
    "info",
    "about",
    "config",
    "users",
    "sudo",
    "sudo_add",
    "auth_chat",
    "remove_chat",
    "sudo_remove",
    "broadcast",
    "shutdown",
    "restart",
    "health",
    "encode",
    "compress",
    "merge",
    "split",
    "subs",
    "chapters",
    "convert",
    "leech",
    "encode_uri",
]

# Images pour les différentes sections
MEDIA_MAP = {
    "start": "https://telegra.ph/file/074cefa975f6141bbaa7a.jpg",
    "help": "https://telegra.ph/file/074cefa975f6141bbaa7a.jpg",
    "about": "https://telegra.ph/file/074cefa975f6141bbaa7a.jpg",
    "encode": "https://telegra.ph/file/074cefa975f6141bbaa7a.jpg",
    "compress": "https://telegra.ph/file/074cefa975f6141bbaa7a.jpg",
    "status": "https://telegra.ph/file/074cefa975f6141bbaa7a.jpg",
    "default": "https://telegra.ph/file/074cefa975f6141bbaa7a.jpg",
    "error": "https://telegra.ph/file/074cefa975f6141bbaa7a.jpg",
    "merge": "https://telegra.ph/file/074cefa975f6141bbaa7a.jpg",
    "warning": "https://telegra.ph/file/074cefa975f6141bbaa7a.jpg",
}

bot = clients.get_client("clientbot")
userbot = clients.get_client("userbot")


@Client.on_message(filters.command(BOT_CMD) & (filters.private | filters.group))
async def handle_bot_commands(client: Client, message: Message):
    cmd = message.command[0].lower()
    user_id = message.from_user.id
    if not user_id:
        await message.reply_text(stylize_value("Admin Inconnue identifiée vous !"))
        logger.warning("Message sans utilisateur identifié, commande ignorée.")
        return

    user = await get_or_create_user(user_id)
    if user is None:
        logger.error(f"Impossible de récupérer ou créer l'utilisateur {user_id}")
        await message.reply_text("Une erreur est survenue lors de votre enregistrement.")
        return

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # COMMANDE START
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    if cmd == "start":
        kb = create_inline_kb(
            [
                [("🛠️ ᴀɪᴅᴇ", "help"), ("❤️‍🩹 ᴀ ᴘʀᴏᴘᴏs", "about")],
                [("⚙️ ᴘᴀʀᴀᴍᴇ̀ᴛʀᴇs", "settings"), ("📊 sᴛᴀᴛᴜs", "status")],
            ]
        )

        kb1 = create_web_kb(
            {
                "📢 ᴍɪsᴇs ᴀ ᴊᴏᴜʀs": "https://t.me/hyoshcoder/",
                "💬 sᴜᴘᴘᴏʀᴛ": "https://t.me/hyoshassistantbot",
            }
        )

        kb2 = create_web_kb({"🧑‍💻 ᴅᴇᴠᴇʟᴏᴘᴇᴜʀ": "https://t.me/hyoshcoder/"})

        kbs = concat_kbs([kb1, kb, kb2, close_kb])

        await send_media(
            client=client,
            media_type="photo",
            chat_id=message.chat.id,
            media=MEDIA_MAP["start"],
            caption=BotMessage.HOMME.format(mention=message.from_user.mention),
            reply_markup=kbs,
            parse_mode=ParseMode.HTML,
            reply_to=message.id,
        )

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # COMMANDE HEALTH (Admin/Sudo seulement)
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    elif cmd == "health" and (
        admin_filter(None, None, message) or sudo_filter(None, None, message)
    ):
        health_report = await clients.check_health()
        report_text = "🩺 **ᴇ́ᴛᴀᴛ ᴅᴜ sʏsᴛᴇ̀ᴍᴇ**\n"
        report_text += "━━━━━━━━━━━━━━━━━━━━\n\n"

        for name, info in health_report.items():
            status_icon = "✅" if info["status"].lower() == "ok" else "⚠️"
            report_text += f"🔹 **{name}** : {status_icon} `{info['status']}`\n"

            if "user" in info:
                report_text += f"  👤 **ᴜᴛɪʟɪsᴀᴛᴇᴜʀ** : `{info['user']}`\n"
            if "latency" in info:
                report_text += f"  📶 **ʟᴀᴛᴇɴᴄᴇ** : `{info['latency']}s`\n"
            if "error" in info:
                report_text += f"  ❌ **ᴇʀʀᴇᴜʀ** : `{info['error']}`\n"

            report_text += "\n"

        await send_media(
            client=client,
            media_type="photo",
            chat_id=message.chat.id,
            media=MEDIA_MAP["status"],
            caption=report_text,
            parse_mode=ParseMode.MARKDOWN,
            reply_to=message.id,
            reply_markup=close_kb,
        )

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # COMMANDE HELP
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    elif cmd == "help":
        help_text = "📚 **ᴀɪᴅᴇ ᴇᴛ ᴄᴏᴍᴍᴀɴᴅᴇs**\n\n"
        help_text += "➻ ` /encode ` : ᴇɴᴄᴏᴅᴀɢᴇ ᴠɪᴅᴇ́ᴏ\n"
        help_text += "➻ ` /compress ` : ᴄᴏᴍᴘʀᴇssɪᴏɴ ᴠɪᴅᴇ́ᴏ\n"
        help_text += "➻ ` /merge ` : ғᴜsɪᴏɴɴᴇʀ ᴅᴇs ᴠɪᴅᴇ́ᴏs\n"
        help_text += "➻ ` /split ` : ᴅᴇ́ᴄᴏᴜᴘᴇʀ ᴜɴᴇ ᴠɪᴅᴇ́ᴏ\n"
        help_text += "➻ ` /subs ` : ᴍᴀɴᴀɢᴇᴍᴇɴᴛ sᴏᴜs-ᴛɪᴛʀᴇs\n"
        help_text += "➻ ` /chapters ` : ᴇ́ᴅɪᴛɪᴏɴ ᴅᴇs ᴄʜᴀᴘɪᴛʀᴇs\n"
        help_text += "➻ ` /convert ` : ᴄᴏɴᴠᴇʀsɪᴏɴ ғᴏʀᴍᴀᴛ\n"
        help_text += "➻ ` /leech ` : ᴛᴇ́ʟᴇ́ᴄʜᴀʀɢᴇᴍᴇɴᴛ ᴜʀʟ\n"
        help_text += "➻ ` /encode_uri ` : ᴍᴀɴɪᴘᴜʟᴀᴛɪᴏɴ ᴜʀʟ\n\n"
        help_text += "ᴘᴏᴜʀ ᴘʟᴜs ᴅ'ɪɴғᴏs : /about"

        kb = InlineKeyboardMarkup(
            [[InlineKeyboardButton("📢 ᴍɪsᴇs ᴀ ᴊᴏᴜʀs", url="https://t.me/hyoshcoder")]]
        )

        tkb = concat_kbs([kb, close_kb])

        await send_media(
            client=client,
            media_type="photo",
            chat_id=message.chat.id,
            media=MEDIA_MAP["help"],
            caption=help_text,
            reply_markup=tkb,
            parse_mode=ParseMode.MARKDOWN,
            reply_to=message.id,
        )

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # COMMANDE ABOUT
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    elif cmd == "about":
        await send_media(
            client=client,
            media_type="photo",
            chat_id=message.chat.id,
            media=MEDIA_MAP["about"],
            caption=BotMessage.ALL_FUNCTIONS,
            parse_mode=ParseMode.MARKDOWN,
            reply_to=message.id,
            reply_markup=close_kb,
        )

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # COMMANDES DE TRAITEMENT VIDÉO
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    elif cmd in [
        "encode",
        "compress",
        "merge",
        "split",
        "subs",
        "chapters",
        "convert",
        "leech",
        "encode_uri",
    ]:
        command_messages = {
            "encode": BotMessage.ENCODER,
            "compress": BotMessage.COMPRESSEUR,
            "merge": BotMessage.MERGE_SPLIT,
            "split": BotMessage.MERGE_SPLIT,
            "subs": BotMessage.SUBTITLES,
            "chapters": BotMessage.CHAPTERS,
            "convert": BotMessage.CONVERTER,
            "leech": BotMessage.URL_PROCESSOR,
            "encode_uri": BotMessage.ENCODE_URI,
        }

        media_key = cmd if cmd in MEDIA_MAP else "default"

        await send_media(
            client=client,
            media_type="photo",
            chat_id=message.chat.id,
            media=MEDIA_MAP.get(media_key, MEDIA_MAP["default"]),
            caption=command_messages[cmd],
            parse_mode=ParseMode.MARKDOWN,
            reply_to=message.id,
            reply_markup=close_kb,
        )

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # COMMANDES ADMINISTRATIVES (Admin/Sudo seulement)
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    elif cmd == "logs" and (
        admin_filter(None, None, message) or sudo_filter(None, None, message)
    ):
        try:
            with open("logs/log.log", "r") as log_file:
                lines = log_file.readlines()[-10:]
                log_content = "".join(lines)
                caption = f"📝 **ᴅᴇʀɴɪᴇʀs ʟᴏɢs**\n```\n{log_content}\n```"

                await send_media(
                    client=client,
                    media_type="photo",
                    chat_id=message.chat.id,
                    media=MEDIA_MAP["status"],
                    caption=caption,
                    parse_mode=ParseMode.MARKDOWN,
                    reply_to=message.id,
                    reply_markup=close_kb,
                )
        except Exception as e:
            await send_msg(
                client=client,
                cid=message.chat.id,
                text=f"❌ ᴇʀʀᴇᴜʀ : {str(e)}",
                parse=ParseMode.MARKDOWN,
                reply_markup=close_kb,
            )

    elif cmd == "restart" and sudo_filter(None, None, message):
        await send_media(
            client=client,
            media_type="photo",
            chat_id=message.chat.id,
            media=MEDIA_MAP["status"],
            caption="🔄 ʀᴇᴅᴇ́ᴍᴀʀʀᴀɢᴇ ᴅᴜ ʙᴏᴛ...",
            parse_mode=ParseMode.MARKDOWN,
            reply_to=message.id,
            reply_markup=close_kb,
        )
        await shutdown_clients()
        import subprocess

        subprocess.Popen([sys.executable, "-m", "isocode"])
        import os

        os._exit(0)

    elif cmd == "shutdown" and sudo_filter(None, None, message):
        await send_media(
            client=client,
            media_type="photo",
            chat_id=message.chat.id,
            media=MEDIA_MAP["status"],
            caption="⏹️ ᴇxᴛɪɴᴄᴛɪᴏɴ ᴅᴜ ʙᴏᴛ...\n\n⚠️ **ʟᴇ ʙᴏᴛ sᴇʀᴀ ᴄᴏᴍᴘʟᴇ̀ᴛᴇᴍᴇɴᴛ ʜᴏʀs ʟɪɢɴᴇ !**\nᴜɴ ʀᴇᴅᴇ́ᴍᴀʀʀᴀɢᴇ ᴍᴀɴᴜᴇʟ sᴇʀᴀ ʀᴇǫᴜɪs.",
            parse_mode=ParseMode.MARKDOWN,
            reply_to=message.id,
            reply_markup=close_kb,
        )

        await shutdown_clients()

        import os

        os._exit(0)

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # COMMANDES UTILITAIRES
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    elif cmd == "ping":
        start_time = time.time()
        msg = await send_media(
            client=client,
            media_type="photo",
            chat_id=message.chat.id,
            media=MEDIA_MAP["status"],
            caption="🏓 ᴘᴏɴɢ...",
            parse_mode=ParseMode.MARKDOWN,
            reply_to=message.id,
            reply_markup=close_kb,
        )
        end_time = time.time()
        latency = round((end_time - start_time) * 1000, 2)

        if msg:
            await edit_media_caption(
                client=client,
                chat_id=message.chat.id,
                message_id=msg.id,
                caption=f"🏓 ᴘᴏɴɢ !\n⏱ ʟᴀᴛᴇɴᴄᴇ : `{latency}ms`",
                parse_mode=ParseMode.MARKDOWN,
                markup=close_kb,
            )

    elif cmd == "status":
        status_text = "📊 **sᴛᴀᴛᴜs ᴅᴜ ʙᴏᴛ**\n\n"
        status_text += f"• ᴠᴇʀsɪᴏɴ : `{settings.ISOCODE_VERSION}`\n"
        status_text += f"• ᴜᴘᴛɪᴍᴇ : `{get_uptime()}`\n"

        try:
            status_text += f"• ᴄʜᴀʀɢᴇ : `{psutil.cpu_percent()}%`\n"
            status_text += f"• ʀᴀᴍ : `{psutil.virtual_memory().percent}%`"
        except Exception as e:
            logger.error(f"Erreur psutil: {e}")
            status_text += "• ᴍᴇ́ᴛʀɪϙᴜᴇs sʏsᴛᴇ̀ᴍᴇ : ɪɴᴅɪsᴘᴏɴɪʙʟᴇ"

        await send_media(
            client=client,
            media_type="photo",
            chat_id=message.chat.id,
            media=MEDIA_MAP["status"],
            caption=status_text,
            parse_mode=ParseMode.MARKDOWN,
            reply_to=message.id,
            reply_markup=close_kb,
        )

    elif cmd == "info":
        user = message.from_user
        info_text = "👤 **ɪɴғᴏ ᴜᴛɪʟɪsᴀᴛᴇᴜʀ**\n\n"
        info_text += f"• ɪᴅ : `{user.id}`\n"
        info_text += f"• ɴᴏᴍ : `{user.first_name}`\n"
        if user.last_name:
            info_text += f"• ᴘʀᴇɴᴏᴍ : `{user.last_name}`\n"
        if user.username:
            info_text += f"• ᴜsᴇʀɴᴀᴍᴇ : @{user.username}\n"
        info_text += (
            f"• ʟᴀɴɢᴜᴇ : `{user.language_code if user.language_code else 'Inconnu'}`\n"
        )

        # Vérifier le statut admin/sudo
        status = "ᴜᴛɪʟɪsᴀᴛᴇᴜʀ"
        if user.id in settings.SUDO_USERS:
            status = "sᴜᴘᴇʀ ᴀᴅᴍɪɴ (sᴜᴅᴏ)"
        elif user.id in settings.SUDO_USERS:
            status = "ᴀᴅᴍɪɴ"

        info_text += f"• sᴛᴀᴛᴜᴛ : {status}"

        await send_media(
            client=client,
            media_type="photo",
            chat_id=message.chat.id,
            media=MEDIA_MAP["status"],
            caption=info_text,
            parse_mode=ParseMode.MARKDOWN,
            reply_to=message.id,
            reply_markup=close_kb,
        )

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # GESTION DES ADMINS (Sudo seulement)
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    elif cmd == "sudo_add" and sudo_filter(None, None, message):
        new_admin = None
        comment = "Aucun commentaire"

        if message.reply_to_message:
            new_admin = message.reply_to_message.from_user.id

            args = message.command[1:]
            if args:
                try:
                    _ = int(args[0])
                    new_admin = int(args[0])
                    comment = " ".join(args[1:]) if len(args) > 1 else comment
                except ValueError:
                    comment = " ".join(args)
            else:
                comment = "Aucun commentaire"

        elif len(message.command) > 1:
            try:
                new_admin = int(message.command[1])
                comment = (
                    " ".join(message.command[2:])
                    if len(message.command) > 2
                    else comment
                )
            except ValueError:
                response = "❌ ɪᴅ ɪɴᴠᴀʟɪᴅᴇ ᴏᴜ ᴄᴏᴍᴍᴀɴᴅᴇ ɴᴏɴ ʀéᴘᴏɴᴅᴜ ᴀ̀ ᴜɴ ᴍᴇꜱꜱᴀɢᴇ"
                await send_media(
                    client=client,
                    media_type="photo",
                    chat_id=message.chat.id,
                    media=MEDIA_MAP["status"],
                    caption=response,
                    parse_mode=ParseMode.MARKDOWN,
                    reply_to=message.id,
                    reply_markup=close_kb,
                )
                return
        else:
            response = "❌ ᴜsᴀɢᴇ : /sudo_add <user_id> ᴏᴜ ᴇɴ ʀéᴘᴏɴꜱᴇ à ᴜɴ ᴍᴇꜱꜱᴀɢᴇ"
            await send_media(
                client=client,
                media_type="photo",
                chat_id=message.chat.id,
                media=MEDIA_MAP["status"],
                caption=response,
                parse_mode=ParseMode.MARKDOWN,
                reply_to=message.id,
                reply_markup=close_kb,
            )
            return

        if new_admin not in settings.SUDO_USERS:
            settings.SUDO_USERS.append(new_admin)
            await set_admin_status(new_admin, True)
            response = f"✅ ᴜᴛɪʟɪsᴀᴛᴇᴜʀ `{new_admin}` ᴀᴊᴏᴜᴛᴇ́ ᴀᴜx ᴀᴅᴍɪɴs"
            try:
                await send_media(
                    client=client,
                    media_type="photo",
                    chat_id=new_admin,
                    media=MEDIA_MAP["status"],
                    caption=(
                        f"👑 ᴠᴏᴜs ᴀᴠᴇᴢ éᴛé ᴀᴊᴏᴜᴛé ᴄᴏᴍᴍᴇ sᴜᴅᴏ ᴜᴛɪʟɪsᴀᴛᴇᴜʀ\n"
                        f"💬 ᴄᴏᴍᴍᴇɴᴛᴀɪʀᴇ : {stylize_value(comment)}"
                    ),
                    parse_mode=ParseMode.HTML,
                )

            except Exception as e:
                print(f"Impossible de notifier l'utilisateur {new_admin}: {e}")
        else:
            response = "ℹ️ ᴜᴛɪʟɪsᴀᴛᴇᴜʀ ᴅᴇ́ᴊᴀ ᴀᴅᴍɪɴ"

        await send_media(
            client=client,
            media_type="photo",
            chat_id=message.chat.id,
            media=MEDIA_MAP["status"],
            caption=response,
            parse_mode=ParseMode.MARKDOWN,
            reply_to=message.id,
            reply_markup=close_kb,
        )

        log_text = (
            "<b>#ɴᴏᴜᴠᴇʟᴀᴅᴍɪɴ</b>\n"
            f"👤 <b>ᴀᴊᴏᴜᴛé ᴘᴀʀ꞉</b> <code>{message.from_user.id}</code>\n"
            f"👤 <b>ɴᴏᴜᴠᴇᴀᴜ ᴀᴅᴍɪɴ:</b> <code>{new_admin}</code>\n"
            f"🕒 <b>ᴅᴀᴛᴇ:</b> {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}\n"
            f"💬 <b>ᴄᴏᴍᴍᴇɴᴛᴀɪʀᴇ:</b> {stylize_value(comment)}"
        )

        await send_log(
            client=client,
            text=log_text,
            level="INFO",
            notify=True,
            parse=ParseMode.HTML,
        )

    elif cmd == "sudo_remove" and sudo_filter(None, None, message):
        replied = message.reply_to_message
        comment = extract_comment(message)

        if replied:
            target_user = replied.from_user
        elif len(message.command) > 1:
            try:
                user_id = int(message.command[1])
                target_user = await client.get_users(user_id)
            except Exception:
                return await send_media(
                    client,
                    message.chat.id,
                    "photo",
                    MEDIA_MAP["error"],
                    "❌ ɪᴅ ɪɴᴠᴀʟɪᴅᴇ",
                    reply_to=message.id,
                    reply_markup=close_kb,
                )
        else:
            return await send_media(
                client,
                message.chat.id,
                "photo",
                MEDIA_MAP["error"],
                "❌ ᴜsᴀɢᴇ : `/sudo_remove <user_id>` ou en répondant à un utilisateur",
                parse_mode=ParseMode.MARKDOWN,
                reply_to=message.id,
                reply_markup=close_kb,
            )

        if target_user.id not in settings.SUDO_USERS:
            return await send_media(
                client,
                message.chat.id,
                "photo",
                MEDIA_MAP["warning"],
                f"ℹ️ {target_user.mention} ɴ'ᴇsᴛ ᴘᴀs ᴀᴅᴍɪɴ.",
                reply_to=message.id,
                reply_markup=close_kb,
            )

        settings.SUDO_USERS.remove(target_user.id)
        await set_admin_status(target_user.id, False)

        await send_media(
            client,
            target_user.id,
            "photo",
            MEDIA_MAP["status"],
            "❌ ᴠᴏᴜs ᴀᴠᴇᴢ éᴛé ʀᴇᴛɪʀé ᴅᴇs ᴀᴅᴍɪɴs",
            parse_mode=ParseMode.MARKDOWN,
        )

        await send_media(
            client,
            message.chat.id,
            "photo",
            MEDIA_MAP["status"],
            f"✅ {target_user.mention} ʀᴇᴛɪʀᴇ́ ᴅᴇs ᴀᴅᴍɪɴs\n💬 ᴄᴏᴍᴍᴇɴᴛᴀɪʀᴇ : {stylize_value(comment)}",
            parse_mode=ParseMode.MARKDOWN,
            reply_to=message.id,
            reply_markup=close_kb,
        )

        await send_log(
            client,
            f"🗑️ #sᴜᴅᴏ_ʀᴇᴍᴏᴠᴇ\n"
            f"👤 Utilisateur : {target_user.mention} (`{target_user.id}`)\n"
            f"👮 Retiré par : {message.from_user.mention} (`{message.from_user.id}`)\n"
            f"💬 Commentaire : {stylize_value(comment)}",
            level="INFO",
            notify=True,
            parse=ParseMode.HTML,
        )

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # GESTION DES CHATS AUTORISÉS (Sudo seulement)
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    elif cmd == "auth_chat" and sudo_filter(None, None, message):
        logger.info(f"command reusi")
        chat_id = None
        comment = "Aucun commentaire"

        # Vérifier si la commande est utilisée dans un groupe
        if message.chat.type != enums.ChatType.PRIVATE:
            chat_id = message.chat.id
            comment = " ".join(message.command[1:]) if len(message.command) > 1 else comment
        elif message.reply_to_message and message.reply_to_message.forward_from_chat:
            chat_id = message.reply_to_message.forward_from_chat.id
            comment = " ".join(message.command[1:]) if len(message.command) > 1 else comment
        elif len(message.command) > 1:
            try:
                chat_id = int(message.command[1])
                comment = " ".join(message.command[2:]) if len(message.command) > 2 else comment
            except ValueError:
                response = "❌ ID de chat invalide ou format incorrect"
                await send_media(
                    client=client,
                    media_type="photo",
                    chat_id=message.chat.id,
                    media=MEDIA_MAP["error"],
                    caption=response,
                    parse_mode=ParseMode.MARKDOWN,
                    reply_to=message.id,
                    reply_markup=close_kb,
                )
                return
        else:
            response = "❌ Usage:\n- Dans un groupe: /auth_chat [commentaire]\n- En réponse à un message de groupe\n- En privé: /auth_chat <chat_id> [commentaire]"
            await send_media(
                client=client,
                media_type="photo",
                chat_id=message.chat.id,
                media=MEDIA_MAP["error"],
                caption=response,
                parse_mode=ParseMode.MARKDOWN,
                reply_to=message.id,
                reply_markup=close_kb,
            )
            return

        if chat_id in settings.AUTHORIZED_CHATS:
            await set_auth_chat(chat_id)
            response = f"ℹ️ Le chat `{chat_id}` est déjà autorisé"
        else:
            settings.AUTHORIZED_CHATS.append(chat_id)
            response = f"✅ Chat `{chat_id}` ajouté aux autorisés\n💬 Commentaire: {stylize_value(comment)}"

        await send_media(
            client=client,
            media_type="photo",
            chat_id=message.chat.id,
            media=MEDIA_MAP["status"],
            caption=response,
            parse_mode=ParseMode.MARKDOWN,
            reply_to=message.id,
            reply_markup=close_kb,
        )

        # Log de l'action
        log_text = (
            "<b>#NOUVEAU_CHAT_AUTORISÉ</b>\n"
            f"👤 <b>Ajouté par:</b> <code>{message.from_user.id}</code>\n"
            f"💬 <b>Chat ID:</b> <code>{chat_id}</code>\n"
            f"🕒 <b>Date:</b> {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}\n"
            f"📝 <b>Commentaire:</b> {stylize_value(comment)}"
        )
        await send_log(client, log_text, "INFO", None, True, ParseMode.HTML)

    elif cmd == "remove_chat" and sudo_filter(None, None, message):
        chat_id = None
        comment = "Aucun commentaire"

        if message.chat.type != enums.ChatType.PRIVATE:
            chat_id = message.chat.id
            comment = " ".join(message.command[1:]) if len(message.command) > 1 else comment
        elif len(message.command) > 1:
            try:
                chat_id = int(message.command[1])
                comment = " ".join(message.command[2:]) if len(message.command) > 2 else comment
            except ValueError:
                response = "❌ ID de chat invalide"
                await send_media(
                    client=client,
                    media_type="photo",
                    chat_id=message.chat.id,
                    media=MEDIA_MAP["error"],
                    caption=response,
                    parse_mode=ParseMode.MARKDOWN,
                    reply_to=message.id,
                    reply_markup=close_kb,
                )
                return
        else:
            response = "❌ Usage:\n- Dans un groupe: /remove_chat [commentaire]\n- En privé: /remove_chat <chat_id> [commentaire]"
            await send_media(
                client=client,
                media_type="photo",
                chat_id=message.chat.id,
                media=MEDIA_MAP["error"],
                caption=response,
                parse_mode=ParseMode.MARKDOWN,
                reply_to=message.id,
                reply_markup=close_kb,
            )
            return

        if chat_id not in settings.AUTHORIZED_CHATS:
            response = f"ℹ️ Le chat `{chat_id}` n'est pas dans la liste autorisée"
        else:
            settings.AUTHORIZED_CHATS.remove(chat_id)
            response = f"✅ Chat `{chat_id}` retiré des autorisés\n💬 Commentaire: {stylize_value(comment)}"

        await send_media(
            client=client,
            media_type="photo",
            chat_id=message.chat.id,
            media=MEDIA_MAP["status"],
            caption=response,
            parse_mode=ParseMode.MARKDOWN,
            reply_to=message.id,
            reply_markup=close_kb,
        )

        # Log de l'action
        log_text = (
            "<b>#CHAT_RETIRÉ</b>\n"
            f"👤 <b>Retiré par:</b> <code>{message.from_user.id}</code>\n"
            f"💬 <b>Chat ID:</b> <code>{chat_id}</code>\n"
            f"🕒 <b>Date:</b> {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}\n"
            f"📝 <b>Commentaire:</b> {stylize_value(comment)}"
        )
        await send_log(client, log_text, "INFO",None, True, ParseMode.HTML)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# FONCTIONS UTILITAIRES
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def get_uptime() -> str:
    """ʀᴇᴛᴏᴜʀɴᴇ ʟ'ᴜᴘᴛɪᴍᴇ ᴅᴜ ʙᴏᴛ"""
    uptime_seconds = int(time.time() - settings.START_TIME)
    hours, remainder = divmod(uptime_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    days, hours = divmod(hours, 24)
    return f"{days}ᴊ {hours}ʜ {minutes}ᴍ {seconds}s"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# HANDLERS SPÉCIFIQUES POUR LES FILTRES
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
@Client.on_message(filters.command("admin_stats") & sudo)
async def admin_stats_handler(client: Client, message: Message):
    """Statistiques réservées aux super-admins"""
    stats_text = "👑 **sᴛᴀᴛɪsᴛɪϙᴜᴇs ᴀᴅᴍɪɴ**\n\n"
    stats_text += f"• ᴜᴛɪʟɪsᴀᴛᴇᴜʀs ᴛᴏᴛᴀᴜx : {await total_users_count()}\n"
    stats_text += f"• ᴀᴅᴍɪɴs : {len(settings.SUDO_USERS)}\n"
    stats_text += f"• sᴜᴅᴏ : {len(settings.SUDO_USERS)}"

    await send_media(
        client=client,
        media_type="photo",
        chat_id=message.chat.id,
        media=MEDIA_MAP["status"],
        caption=stats_text,
        parse_mode=ParseMode.MARKDOWN,
        reply_to=message.id,
        reply_markup=close_kb,
    )


@Client.on_message(filters.command("user_help") & user)
async def user_help_handler(client: Client, message: Message):
    """Aide spécifique pour les utilisateurs enregistrés"""
    help_text = "🙋 **ᴀɪᴅᴇ ᴜᴛɪʟɪsᴀᴛᴇᴜʀ**\n\n"
    help_text += "➻ /encode : ᴇɴᴄᴏᴅᴇʀ ᴜɴᴇ ᴠɪᴅᴇ́ᴏ\n"
    help_text += "➻ /settings : ᴍᴏᴅɪғɪᴇʀ ᴍᴇs ᴘʀᴇ́ғᴇ́ʀᴇɴᴄᴇs\n"
    help_text += "➻ /status : ᴠᴏɪʀ ʟ'ᴇ́ᴛᴀᴛ ᴅᴜ ʙᴏᴛ\n"
    help_text += "➻ /info : ᴍᴇs ɪɴғᴏʀᴍᴀᴛɪᴏɴs\n\n"
    help_text += "ᴘᴏᴜʀ ᴜɴ sᴜᴘᴘᴏʀᴛ ᴛᴇᴄʜɴɪϙᴜᴇ : @hyoshassistantbot"

    await send_media(
        client=client,
        media_type="photo",
        chat_id=message.chat.id,
        media=MEDIA_MAP["help"],
        caption=help_text,
        parse_mode=ParseMode.MARKDOWN,
        reply_to=message.id,
        reply_markup=close_kb,
    )


def extract_comment(message) -> str:
    """
    Récupère le commentaire dans une commande Telegram.
    Exemple : /sudo_remove 12345 ceci est un commentaire
    Retourne : "ceci est un commentaire"
    """
    parts = message.text.split()
    if len(parts) > 2:
        return " ".join(parts[2:])
    return "Aucun commentaire"
