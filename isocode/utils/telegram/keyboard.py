from pyrogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    KeyboardButton,
    ForceReply,
)
from typing import Union, Dict, List, Tuple, Optional

def create_inline_kb(
    btns: Union[Dict[str, Union[str, Dict]], List[List[Tuple[str, str]]]],
    row_len: int = 3,
    back_btn: Optional[Tuple[str, str]] = None
) -> InlineKeyboardMarkup:
    """
    Create inline keyboard from multiple formats

    :param btns: Can be:
        - Dict: {text: data} or {text: {subtext: subdata}}
        - List: 2D list of [(text, data)]
    :param row_len: Buttons per row (for flat dict)
    :param back_btn: (text, data) for back button
    :return: InlineKeyboardMarkup

    Exemple:
    ```
    # Format dictionnaire simple
    kb = create_inline_kb(
        {"Option 1": "data1", "Option 2": "data2"}
    )

    # Format dictionnaire avec sous-menu
    kb = create_inline_kb({
        "Menu": {
            "Sub1": "subdata1",
            "Sub2": "subdata2"
        }
    })

    # Format liste 2D
    kb = create_inline_kb([
        [("Bouton 1", "data1"), ("Bouton 2", "data2")],
        [("Bouton 3", "data3")]
    ])

    # Avec bouton retour
    kb = create_inline_kb(
        {"Option": "data"},
        back_btn=("🔙 Retour", "back_data")
    )
    ```
    """
    kb = []

    if isinstance(btns, dict):
        for k, v in btns.items():
            if isinstance(v, str):
                kb.append([InlineKeyboardButton(k, callback_data=v)])
            elif isinstance(v, dict):
                row = [InlineKeyboardButton(sub_k, callback_data=sub_v) for sub_k, sub_v in v.items()]
                kb.append(row)

    elif isinstance(btns, list):
        for row in btns:
            kb.append([InlineKeyboardButton(t, callback_data=d) for t, d in row])

    if back_btn:
        t, d = back_btn
        kb.append([InlineKeyboardButton(t, callback_data=d)])

    return InlineKeyboardMarkup(kb)

def create_web_kb(
    links: Union[Dict[str, str], List[List[Tuple[str, str]]]],
    row_len: int = 2
) -> InlineKeyboardMarkup:
    """
    Create web inline keyboard

    :param links: {text: url} or 2D list of [(text, url)]
    :param row_len: Buttons per row
    :return: InlineKeyboardMarkup

    Exemple:
    ```
    # Format dictionnaire
    kb = create_web_kb(
        {"Google": "https://google.com", "GitHub": "https://github.com"}
    )

    # Format liste 2D
    kb = create_web_kb([
        [("OpenAI", "https://openai.com")],
        [("Pyrogram", "https://pyrogram.org"), ("Docs", "https://docs.pyrogram.org")]
    ])
    ```
    """
    kb = []

    if isinstance(links, dict):
        items = list(links.items())
        for i in range(0, len(items), row_len):
            row = items[i:i + row_len]
            kb.append([InlineKeyboardButton(t, url=u) for t, u in row])

    elif isinstance(links, list):
        for row in links:
            kb.append([InlineKeyboardButton(t, url=u) for t, u in row])

    return InlineKeyboardMarkup(kb)

def create_reply_kb(
    btns: Union[List[str], List[List[str]]],
    row_len: int = 2,
    resize: bool = True,
    one_time: bool = False,
    selective: bool = False
) -> ReplyKeyboardMarkup:
    """
    Create reply keyboard

    :param btns: Flat list [btn1, btn2] or 2D list [[btn1, btn2]]
    :param row_len: Buttons per row (flat list)
    :param resize: Auto-resize keyboard
    :param one_time: One-time keyboard
    :param selective: Show for specific users
    :return: ReplyKeyboardMarkup

    Exemple:
    ```
    # Liste plate
    kb = create_reply_kb(
        ["Option 1", "Option 2", "Option 3"],
        row_len=2
    )

    # Liste 2D
    kb = create_reply_kb([
        ["A", "B"],
        ["C", "D", "E"],
        ["F"]
    ])
    ```
    """
    kb = []

    if all(isinstance(b, str) for b in btns):
        for i in range(0, len(btns), row_len):
            row = btns[i:i + row_len]
            kb.append([KeyboardButton(b) for b in row])

    elif all(isinstance(r, list) for r in btns):
        kb = [[KeyboardButton(b) for b in r] for r in btns]

    return ReplyKeyboardMarkup(
        keyboard=kb,
        resize_keyboard=resize,
        one_time_keyboard=one_time,
        selective=selective
    )

def create_contact_kb(txt: str = "📱 Share Contact") -> ReplyKeyboardMarkup:
    """
    Create contact sharing button

    Exemple:
    ```
    kb = create_contact_kb("📞 Envoyer mon contact")
    ```
    """
    return ReplyKeyboardMarkup(
        [[KeyboardButton(txt, request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True
    )

def create_location_kb(txt: str = "📍 Share Location") -> ReplyKeyboardMarkup:
    """
    Create location sharing button

    Exemple:
    ```
    kb = create_location_kb("🗺️ Partager position")
    ```
    """
    return ReplyKeyboardMarkup(
        [[KeyboardButton(txt, request_location=True)]],
        resize_keyboard=True,
        one_time_keyboard=True
    )

def remove_kb(selective: bool = False) -> ReplyKeyboardRemove:
    """
    Remove reply keyboard

    Exemple:
    ```
    kb = remove_kb(selective=True)
    ```
    """
    return ReplyKeyboardRemove(selective=selective)

def create_pagination_kb(
    page: int,
    total: int,
    prefix: str,
    extras: Optional[List[Tuple[str, str]]] = None
) -> InlineKeyboardMarkup:
    """
    Create pagination buttons

    :param page: Current page
    :param total: Total pages
    :param prefix: Callback prefix
    :param extras: Extra buttons [(text, data)]
    :return: InlineKeyboardMarkup

    Exemple:
    ```
    kb = create_pagination_kb(
        page=2,
        total=5,
        prefix="pagination",
        extras=[("⭐ Favoris", "fav_data")]
    )
    ```
    """
    btns = []

    if page > 1:
        btns.append(InlineKeyboardButton("⬅️", callback_data=f"{prefix}|{page-1}"))

    btns.append(InlineKeyboardButton(f"{page}/{total}", callback_data=f"{prefix}|refresh"))

    if page < total:
        btns.append(InlineKeyboardButton("➡️", callback_data=f"{prefix}|{page+1}"))

    kb = [btns]

    if extras:
        kb.append([InlineKeyboardButton(t, callback_data=d) for t, d in extras])

    return InlineKeyboardMarkup(kb)

def create_toggle_kb(
    options: List[Tuple[str, str, bool]],
    row_len: int = 2,
    back_btn: Optional[Tuple[str, str]] = None
) -> InlineKeyboardMarkup:
    """
    Create toggle buttons with state indicator

    :param options: [(text, callback, is_active)]
    :param row_len: Buttons per row
    :param back_btn: (text, data) for back button
    :return: InlineKeyboardMarkup

    Exemple:
    ```
    kb = create_toggle_kb(
        options=[
            ("Notification", "notif_toggle", True),
            ("Dark Mode", "dark_mode_toggle", False)
        ],
        back_btn=("🔙 Retour", "main_menu")
    )
    ```
    """
    kb = []
    row = []

    for i, (t, c, active) in enumerate(options):
        btn = InlineKeyboardButton(f"{'✅ ' if active else '❌ '}{t}", callback_data=c)
        row.append(btn)

        if (i+1) % row_len == 0:
            kb.append(row)
            row = []

    if row:
        kb.append(row)

    if back_btn:
        t, d = back_btn
        kb.append([InlineKeyboardButton(t, callback_data=d)])

    return InlineKeyboardMarkup(kb)

def create_grid_kb(
    items: List[Tuple[str, str]],
    per_row: int = 3,
    back_btn: Optional[Tuple[str, str]] = None
) -> InlineKeyboardMarkup:
    """
    Create inline button grid

    :param items: [(text, callback_data)]
    :param per_row: Items per row
    :param back_btn: (text, data) for back button
    :return: InlineKeyboardMarkup

    Exemple:
    ```
    kb = create_grid_kb(
        items=[
            ("Item 1", "data1"),
            ("Item 2", "data2"),
            ("Item 3", "data3"),
            ("Item 4", "data4")
        ],
        per_row=2,
        back_btn=("🔙 Retour", "back_data")
    )
    ```
    """
    kb = []

    for i in range(0, len(items), per_row):
        row = items[i:i + per_row]
        kb.append([InlineKeyboardButton(t, callback_data=d) for t, d in row])

    if back_btn:
        t, d = back_btn
        kb.append([InlineKeyboardButton(t, callback_data=d)])

    return InlineKeyboardMarkup(kb)

def concat_kbs(kb_list: List[InlineKeyboardMarkup]) -> InlineKeyboardMarkup:
    """
    Concatenate a list of inline keyboards

    :param kb_list: List of InlineKeyboardMarkup objects
    :return: Combined InlineKeyboardMarkup

    Exemple:
    ```
    kb1 = InlineKeyboardMarkup([[InlineKeyboardButton("A", "data1")]])
    kb2 = InlineKeyboardMarkup([
        [InlineKeyboardButton("B", "data2"), InlineKeyboardButton("C", "data3")]
    ])
    combined_kb = concat_kbs([kb1, kb2])
    ```
    """
    combined = []
    for kb in kb_list:
        if kb and hasattr(kb, 'inline_keyboard'):
            combined.extend(kb.inline_keyboard)
    return InlineKeyboardMarkup(combined)

def create_force_reply_kb(
    text: str = "Please reply to this message",
    selective: bool = False
) -> ForceReply:
    """
    Create a force reply keyboard

    :param text: Placeholder text shown in input field
    :param selective: Show to specific users only
    :return: ForceReply object

    Exemple:
    ```
    kb = create_force_reply_kb(
        text="Entrez votre réponse ici...",
        selective=True
    )
    ```
    """
    return ForceReply(
        force_reply=True,
        input_field_placeholder=text,
        selective=selective
    )