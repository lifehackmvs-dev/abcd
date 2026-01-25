from aiogram_dialog import Dialog, StartMode, Window
from aiogram_dialog.widgets.kbd import Button, ListGroup, Row, Start, SwitchTo
from aiogram_dialog.widgets.text import Format
from magic_filter import F

from src.bot.keyboards import main_menu_button
from src.bot.routers.extra.test import show_dev_popup
from src.bot.states import (
    Dashboard,
    DashboardKeystoneTech,
    KeystoneTechGateways,
    KeystoneTechNotifications,
    KeystoneTechPlans,
    KeystoneTechReferral,
)
from src.bot.widgets import Banner, I18nFormat, IgnoreUpdate
from src.core.enums import BannerName

from .getters import admins_getter, remnashop_getter
from .handlers import on_logs_request, on_user_role_remove, on_user_select

keystonetech = Window(
    Banner(BannerName.DASHBOARD),
    I18nFormat("msg-keystonetech-main"),
    Row(
        SwitchTo(
            text=I18nFormat("btn-keystonetech-admins"),
            id="admins",
            state=DashboardKeystoneTech.ADMINS,
        ),
    ),
    Row(
        Start(
            text=I18nFormat("btn-keystonetech-gateways"),
            id="gateways",
            state=KeystoneTechGateways.MAIN,
        ),
    ),
    Row(
        Start(
            text=I18nFormat("btn-keystonetech-referral"),
            id="referral",
            state=KeystoneTechReferral.MAIN,
        ),
        Button(
            text=I18nFormat("btn-keystonetech-advertising"),
            id="advertising",
            # state=DashboardKeystoneTech.ADVERTISING,
            on_click=show_dev_popup,
        ),
    ),
    Row(
        Start(
            text=I18nFormat("btn-keystonetech-plans"),
            id="plans",
            state=KeystoneTechPlans.MAIN,
            mode=StartMode.RESET_STACK,
        ),
        Start(
            text=I18nFormat("btn-keystonetech-notifications"),
            id="notifications",
            state=KeystoneTechNotifications.MAIN,
        ),
    ),
    Row(
        Button(
            text=I18nFormat("btn-keystonetech-logs"),
            id="logs",
            on_click=on_logs_request,
        ),
        Button(
            text=I18nFormat("btn-keystonetech-audit"),
            id="audit",
            on_click=show_dev_popup,
        ),
    ),
    Row(
        Start(
            text=I18nFormat("btn-back"),
            id="back",
            state=Dashboard.MAIN,
            mode=StartMode.RESET_STACK,
        ),
        *main_menu_button,
    ),
    IgnoreUpdate(),
    state=DashboardKeystoneTech.MAIN,
    getter=remnashop_getter,
)

admins = Window(
    Banner(BannerName.DASHBOARD),
    I18nFormat("msg-admins-main"),
    ListGroup(
        Row(
            Button(
                text=Format("{item[user_id]} ({item[user_name]})"),
                id="select_user",
                on_click=on_user_select,
            ),
            Button(
                text=Format("❌"),
                id="remove_role",
                on_click=on_user_role_remove,
                when=F["item"]["deletable"],
            ),
        ),
        id="admins_list",
        item_id_getter=lambda item: item["user_id"],
        items="admins",
    ),
    Row(
        Start(
            text=I18nFormat("btn-back"),
            id="back",
            state=DashboardKeystoneTech.MAIN,
            mode=StartMode.RESET_STACK,
        ),
    ),
    IgnoreUpdate(),
    state=DashboardKeystoneTech.ADMINS,
    getter=admins_getter,
)

router = Dialog(
    keystonetech,
    admins,
)
