from aiogram_dialog import Dialog, StartMode, Window
from aiogram_dialog.widgets.kbd import NumberedPager, Row, Start, StubScroll, SwitchTo

from src.bot.keyboards import main_menu_button
from src.bot.states import Dashboard, DashboardKeystoneWave
from src.bot.widgets import Banner, I18nFormat, IgnoreUpdate
from src.core.enums import BannerName

from .getters import (
    hosts_getter,
    inbounds_getter,
    nodes_getter,
    system_getter,
    users_getter,
)

keystonewave = Window(
    Banner(BannerName.DASHBOARD),
    I18nFormat("msg-keystonewave-main"),
    Row(
        SwitchTo(
            text=I18nFormat("btn-keystonewave-users"),
            id="users",
            state=DashboardKeystoneWave.USERS,
        ),
    ),
    Row(
        SwitchTo(
            text=I18nFormat("btn-keystonewave-hosts"),
            id="hosts",
            state=DashboardKeystoneWave.HOSTS,
        ),
        SwitchTo(
            text=I18nFormat("btn-keystonewave-nodes"),
            id="nodes",
            state=DashboardKeystoneWave.NODES,
        ),
        SwitchTo(
            text=I18nFormat("btn-keystonewave-inbounds"),
            id="inbounds",
            state=DashboardKeystoneWave.INBOUNDS,
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
    state=DashboardKeystoneWave.MAIN,
    getter=system_getter,
)

users = Window(
    Banner(BannerName.DASHBOARD),
    I18nFormat("msg-keystonewave-users"),
    Row(
        SwitchTo(
            text=I18nFormat("btn-back"),
            id="back",
            state=DashboardKeystoneWave.MAIN,
        ),
    ),
    IgnoreUpdate(),
    state=DashboardKeystoneWave.USERS,
    getter=users_getter,
)

hosts = Window(
    Banner(BannerName.DASHBOARD),
    I18nFormat("msg-keystonewave-hosts"),
    StubScroll(id="scroll_hosts", pages="pages"),
    NumberedPager(scroll="scroll_hosts"),
    Row(
        SwitchTo(
            text=I18nFormat("btn-back"),
            id="back",
            state=DashboardKeystoneWave.MAIN,
        ),
    ),
    IgnoreUpdate(),
    state=DashboardKeystoneWave.HOSTS,
    getter=hosts_getter,
    preview_data=hosts_getter,
)

nodes = Window(
    Banner(BannerName.DASHBOARD),
    I18nFormat("msg-keystonewave-nodes"),
    StubScroll(id="scroll_nodes", pages="pages"),
    NumberedPager(scroll="scroll_nodes"),
    Row(
        SwitchTo(
            text=I18nFormat("btn-back"),
            id="back",
            state=DashboardKeystoneWave.MAIN,
        ),
    ),
    IgnoreUpdate(),
    state=DashboardKeystoneWave.NODES,
    getter=nodes_getter,
    preview_data=nodes_getter,
)

inbounds = Window(
    Banner(BannerName.DASHBOARD),
    I18nFormat("msg-keystonewave-inbounds"),
    StubScroll(id="scroll_inbounds", pages="pages"),
    NumberedPager(scroll="scroll_inbounds"),
    Row(
        SwitchTo(
            text=I18nFormat("btn-back"),
            id="back",
            state=DashboardKeystoneWave.MAIN,
        ),
    ),
    IgnoreUpdate(),
    state=DashboardKeystoneWave.INBOUNDS,
    getter=inbounds_getter,
    preview_data=inbounds_getter,
)

router = Dialog(
    keystonewave,
    users,
    hosts,
    nodes,
    inbounds,
)
