from datetime import timedelta
from typing import Optional, cast
from uuid import UUID

from aiogram import Bot
from fluentogram import TranslatorHub
from loguru import logger
from redis.asyncio import Redis
from remnapy import RemnawaveSDK
from remnapy.exceptions import ConflictError, NotFoundError
from remnapy.models import (
    CreateUserRequestDto,
    CreateUserResponseDto,
    GetStatsResponseDto,
    HWIDDeleteRequest,
    HwidUserDeviceDto,
    UpdateUserRequestDto,
    UserResponseDto,
)
from remnapy.models.hwid import HwidDeviceDto
from remnapy.models.webhook import NodeDto

from src.bot.keyboards import get_user_keyboard
from src.core.config import AppConfig
from src.core.constants import DATETIME_FORMAT, IMPORTED_TAG
from src.core.enums import (
    RemnaNodeEvent,
    RemnaUserEvent,
    RemnaUserHwidDevicesEvent,
    SubscriptionStatus,
    SystemNotificationType,
    UserNotificationType,
)
from src.core.i18n.keys import ByteUnitKey
from src.core.utils.formatters import (
    format_country_code,
    format_days_to_datetime,
    format_device_count,
    format_gb_to_bytes,
    format_limits_to_plan_type,
    i18n_format_bytes_to_unit,
    i18n_format_device_limit,
    i18n_format_expire_time,
    i18n_format_traffic_limit,
)
from src.core.utils.message_payload import MessagePayload
from src.core.utils.time import datetime_now
from src.core.utils.types import RemnaUserDto
from src.infrastructure.database.models.dto import (
    PlanSnapshotDto,
    KeystoneSubscriptionDto,
    SubscriptionDto,
    UserDto,
)
from src.infrastructure.redis import RedisRepository
from src.infrastructure.taskiq.tasks.notifications import (
    send_subscription_expire_notification_task,
    send_subscription_limited_notification_task,
)
from src.services.notification import NotificationService
from src.services.subscription import SubscriptionService
from src.services.user import UserService

from .base import BaseService


class RemnawaveService(BaseService):
    keystonewave: RemnawaveSDK
    user_service: UserService
    subscription_service: SubscriptionService

    def __init__(
        self,
        config: AppConfig,
        bot: Bot,
        redis_client: Redis,
        redis_repository: RedisRepository,
        translator_hub: TranslatorHub,
        #
        keystonewave: RemnawaveSDK,
        user_service: UserService,
        subscription_service: SubscriptionService,
        notification_service: NotificationService,
    ) -> None:
        super().__init__(config, bot, redis_client, redis_repository, translator_hub)
        self.keystonewave = keystonewave
        self.user_service = user_service
        self.subscription_service = subscription_service
        self.notification_service = notification_service

    async def try_connection(self) -> None:
        response = await self.keystonewave.system.get_stats()

        if not isinstance(response, GetStatsResponseDto):
            raise ValueError(f"Invalid response from KeystoneWave panel: {response}")

    async def create_user(
        self,
        user: UserDto,
        plan: Optional[PlanSnapshotDto] = None,
        subscription: Optional[SubscriptionDto] = None,
        force: bool = False,
    ) -> UserResponseDto:
        async def _do_create() -> CreateUserResponseDto:
            if subscription:
                logger.info(
                    f"Creating RemnaUser '{user.remna_name}' "
                    f"from subscription '{subscription.plan.name}'"
                )
                return await self.keystonewave.users.create_user(
                    CreateUserRequestDto(
                        uuid=subscription.user_remna_id,
                        expire_at=subscription.expire_at,
                        username=user.remna_name,
                        traffic_limit_bytes=format_gb_to_bytes(subscription.traffic_limit),
                        traffic_limit_strategy=subscription.traffic_limit_strategy,
                        description=user.remna_description,
                        tag=subscription.tag,
                        telegram_id=user.telegram_id,
                        hwid_device_limit=format_device_count(subscription.device_limit),
                        active_internal_squads=subscription.internal_squads,
                        external_squad_uuid=subscription.external_squad,
                    )
                )

            if plan:
                logger.info(f"Creating RemnaUser '{user.telegram_id}' from plan '{plan.name}'")
                return await self.keystonewave.users.create_user(
                    CreateUserRequestDto(
                        expire_at=format_days_to_datetime(plan.duration),
                        username=user.remna_name,
                        traffic_limit_bytes=format_gb_to_bytes(plan.traffic_limit),
                        traffic_limit_strategy=plan.traffic_limit_strategy,
                        description=user.remna_description,
                        tag=plan.tag,
                        telegram_id=user.telegram_id,
                        hwid_device_limit=format_device_count(plan.device_limit),
                        active_internal_squads=plan.internal_squads,
                        external_squad_uuid=plan.external_squad,
                    )
                )

            raise ValueError("Either 'plan' or 'subscription' must be provided")

        try:
            created = await _do_create()

        except ConflictError:
            if not force:
                raise

            logger.warning(
                f"User '{user.remna_name}' already exists. Force flag enabled, "
                f"removing and recreating"
            )

            old_keystone_user = await self.keystonewave.users.get_user_by_username(user.remna_name)
            await self.keystonewave.users.delete_user(old_keystone_user.uuid)
            created = await _do_create()

        logger.info(f"RemnaUser '{created.username}' created successfully")
        return created

    async def updated_user(
        self,
        user: UserDto,
        uuid: UUID,
        plan: Optional[PlanSnapshotDto] = None,
        subscription: Optional[SubscriptionDto] = None,
        reset_traffic: bool = False,
    ) -> UserResponseDto:
        if subscription:
            logger.info(
                f"Updating RemnaUser '{user.telegram_id}' from subscription '{subscription.id}'"
            )
            status = (
                SubscriptionStatus.DISABLED
                if subscription.status == SubscriptionStatus.DISABLED
                else SubscriptionStatus.ACTIVE
            )
            traffic_limit = subscription.traffic_limit
            device_limit = subscription.device_limit
            internal_squads = subscription.internal_squads
            external_squad = subscription.external_squad
            expire_at = subscription.expire_at
            tag = subscription.tag
            strategy = subscription.traffic_limit_strategy

        elif plan:
            logger.info(f"Updating RemnaUser '{user.telegram_id}' from plan '{plan.name}'")
            status = SubscriptionStatus.ACTIVE
            traffic_limit = plan.traffic_limit
            device_limit = plan.device_limit
            internal_squads = plan.internal_squads
            external_squad = plan.external_squad
            expire_at = format_days_to_datetime(plan.duration)
            tag = plan.tag
            strategy = plan.traffic_limit_strategy
        else:
            raise ValueError("Either 'plan' or 'subscription' must be provided")

        updated_user = await self.keystonewave.users.update_user(
            UpdateUserRequestDto(
                uuid=uuid,
                active_internal_squads=internal_squads,
                external_squad_uuid=external_squad,
                description=user.remna_description,
                tag=tag,
                expire_at=expire_at,
                hwid_device_limit=format_device_count(device_limit),
                status=status,
                telegram_id=user.telegram_id,
                traffic_limit_bytes=format_gb_to_bytes(traffic_limit),
                traffic_limit_strategy=strategy,
            )
        )

        if reset_traffic:
            await self.keystonewave.users.reset_user_traffic(uuid)
            logger.info(f"Traffic reset for RemnaUser '{user.telegram_id}'")

        logger.info(f"RemnaUser '{user.telegram_id}' updated successfully")
        return updated_user

    async def delete_user(self, user: UserDto) -> bool:
        logger.info(f"Deleting RemnaUser '{user.telegram_id}'")

        if not user.current_subscription:
            logger.warning(f"No current subscription for user '{user.telegram_id}'")

            users_result = await self.keystonewave.users.get_users_by_telegram_id(
                telegram_id=str(user.telegram_id)
            )

            if not users_result:
                return False

            uuid = users_result[0].uuid
        else:
            uuid = user.current_subscription.user_remna_id

        result = await self.keystonewave.users.delete_user(uuid)

        if result.is_deleted:
            logger.info(f"RemnaUser '{user.telegram_id}' deleted successfully")
        else:
            logger.warning(f"RemnaUser '{user.telegram_id}' deletion failed")

        return result.is_deleted

    async def get_devices_user(self, user: UserDto) -> list[HwidDeviceDto]:
        logger.info(f"Fetching devices for RemnaUser '{user.telegram_id}'")

        if not user.current_subscription:
            logger.warning(f"No subscription found for user '{user.telegram_id}'")
            return []

        result = await self.keystonewave.hwid.get_hwid_user(user.current_subscription.user_remna_id)

        if result.total:
            logger.info(f"Found '{result.total}' device(s) for RemnaUser '{user.telegram_id}'")
            return result.devices

        logger.info(f"No devices found for RemnaUser '{user.telegram_id}'")
        return []

    async def delete_device(self, user: UserDto, hwid: str) -> Optional[int]:
        logger.info(f"Deleting device '{hwid}' for RemnaUser '{user.telegram_id}'")

        if not user.current_subscription:
            logger.warning(f"No subscription found for user '{user.telegram_id}'")
            return None

        result = await self.keystonewave.hwid.delete_hwid_to_user(
            HWIDDeleteRequest(
                user_uuid=user.current_subscription.user_remna_id,
                hwid=hwid,
            )
        )

        logger.info(f"Deleted device '{hwid}' for RemnaUser '{user.telegram_id}'")
        return result.total

    async def get_user(self, uuid: UUID) -> Optional[UserResponseDto]:
        logger.info(f"Fetching RemnaUser '{uuid}'")
        try:
            keystone_user = await self.keystonewave.users.get_user_by_uuid(uuid)
        except NotFoundError:
            logger.warning(f"RemnaUser '{uuid}' not found")
            return None

        logger.info(f"RemnaUser '{keystone_user.telegram_id}' fetched successfully")
        return keystone_user

    async def get_subscription_url(self, uuid: UUID) -> Optional[str]:
        keystone_user = await self.get_user(uuid)

        if keystone_user is None:
            logger.warning(f"RemnaUser '{uuid}' has not subscription url")
            return None

        return keystone_user.subscription_url

    async def sync_user(self, keystone_user: RemnaUserDto, creating: bool = True) -> None:
        if not keystone_user.telegram_id:
            logger.warning(f"Skipping sync for '{keystone_user.username}', missing 'telegram_id'")
            return

        user = await self.user_service.get(telegram_id=keystone_user.telegram_id)

        if not user and creating:
            logger.debug(f"User '{keystone_user.telegram_id}' not found in bot, creating new user")
            user = await self.user_service.create_from_panel(keystone_user)

        user = cast(UserDto, user)
        subscription = await self.subscription_service.get_current(telegram_id=user.telegram_id)
        keystone_subscription = KeystoneSubscriptionDto.from_keystone_user(keystone_user)

        if not keystone_subscription.url:
            keystone_subscription.url = await self.get_subscription_url(keystone_user.uuid)  # type: ignore[assignment]

        if not subscription:
            logger.info(f"No subscription found for '{user.telegram_id}', creating")

            temp_plan = PlanSnapshotDto(
                id=-1,
                name=IMPORTED_TAG,
                tag=keystone_subscription.tag,
                type=format_limits_to_plan_type(
                    keystone_subscription.traffic_limit,
                    keystone_subscription.device_limit,
                ),
                traffic_limit=keystone_subscription.traffic_limit,
                device_limit=keystone_subscription.device_limit,
                duration=-1,
                traffic_limit_strategy=keystone_subscription.traffic_limit_strategy,
                internal_squads=keystone_subscription.internal_squads,
                external_squad=keystone_subscription.external_squad,
            )

            expired = keystone_user.expire_at and keystone_user.expire_at < datetime_now()
            status = SubscriptionStatus.EXPIRED if expired else keystone_user.status

            subscription = SubscriptionDto(
                user_remna_id=keystone_user.uuid,
                status=status,
                traffic_limit=temp_plan.traffic_limit,
                device_limit=temp_plan.device_limit,
                traffic_limit_strategy=temp_plan.traffic_limit_strategy,
                tag=temp_plan.tag,
                internal_squads=keystone_subscription.internal_squads,
                external_squad=keystone_subscription.external_squad,
                expire_at=keystone_user.expire_at,
                url=keystone_subscription.url,
                plan=temp_plan,
            )

            await self.subscription_service.create(user, subscription)
            logger.info(f"Subscription created for '{user.telegram_id}'")

        else:
            logger.info(f"Synchronizing subscription for '{user.telegram_id}'")
            subscription = SubscriptionService.apply_sync(
                target=subscription,
                source=keystone_subscription,
            )
            await self.subscription_service.update(subscription)
            logger.info(f"Subscription updated for '{user.telegram_id}'")

        logger.info(f"Sync completed for user '{keystone_user.telegram_id}'")

    #

    async def handle_user_event(self, event: str, keystone_user: RemnaUserDto) -> None:  # noqa: C901
        from src.infrastructure.taskiq.tasks.subscriptions import (  # noqa: PLC0415
            delete_current_subscription_task,
            update_status_current_subscription_task,
        )

        logger.info(f"Received event '{event}' for RemnaUser '{keystone_user.telegram_id}'")

        if not keystone_user.telegram_id:
            logger.debug(f"Skipping RemnaUser '{keystone_user.username}': telegram_id is empty")
            return

        if event == RemnaUserEvent.CREATED:
            if keystone_user.tag != IMPORTED_TAG:
                logger.debug(
                    f"Created RemnaUser '{keystone_user.telegram_id}' "
                    f"is not tagged as '{IMPORTED_TAG}', skipping sync"
                )
            else:
                await self.sync_user(keystone_user)
            return

        user = await self.user_service.get(telegram_id=keystone_user.telegram_id)

        if not user:
            logger.warning(f"No local user found for telegram_id '{keystone_user.telegram_id}'")
            return

        i18n_kwargs = {
            "is_trial": False,
            "user_id": str(user.telegram_id),
            "user_name": user.name,
            "username": user.username or False,
            "subscription_id": str(keystone_user.uuid),
            "subscription_status": keystone_user.status,
            "traffic_used": i18n_format_bytes_to_unit(
                keystone_user.used_traffic_bytes,
                min_unit=ByteUnitKey.MEGABYTE,
            ),
            "traffic_limit": (
                i18n_format_bytes_to_unit(keystone_user.traffic_limit_bytes)
                if keystone_user.traffic_limit_bytes > 0
                else i18n_format_traffic_limit(-1)
            ),
            "device_limit": (
                i18n_format_device_limit(keystone_user.hwid_device_limit)
                if keystone_user.hwid_device_limit
                else i18n_format_device_limit(-1)
            ),
            "expire_time": i18n_format_expire_time(keystone_user.expire_at),
        }

        if event == RemnaUserEvent.MODIFIED:
            logger.debug(f"RemnaUser '{keystone_user.telegram_id}' modified")
            await self.sync_user(keystone_user, creating=False)

        elif event == RemnaUserEvent.DELETED:
            logger.debug(f"RemnaUser '{keystone_user.telegram_id}' deleted")
            await delete_current_subscription_task.kiq(keystone_user)

        elif event in {
            RemnaUserEvent.REVOKED,
            RemnaUserEvent.ENABLED,
            RemnaUserEvent.DISABLED,
            RemnaUserEvent.LIMITED,
            RemnaUserEvent.EXPIRED,
        }:
            logger.debug(
                f"RemnaUser '{keystone_user.telegram_id}' status changed to '{keystone_user.status}'"
            )
            await update_status_current_subscription_task.kiq(
                user_telegram_id=keystone_user.telegram_id,
                status=SubscriptionStatus(keystone_user.status),
            )
            if event == RemnaUserEvent.LIMITED:
                await send_subscription_limited_notification_task.kiq(
                    keystone_user=keystone_user,
                    i18n_kwargs=i18n_kwargs,
                )
            elif event == RemnaUserEvent.EXPIRED:
                if keystone_user.expire_at + timedelta(days=3) < datetime_now():
                    logger.debug(
                        f"Subscription for RemnaUser '{user.telegram_id}' expired more than "
                        "3 days ago, skipping - most likely an imported user"
                    )
                    return

                await send_subscription_expire_notification_task.kiq(
                    keystone_user=keystone_user,
                    ntf_type=UserNotificationType.EXPIRED,
                    i18n_kwargs=i18n_kwargs,
                )

        elif event == RemnaUserEvent.FIRST_CONNECTED:
            logger.debug(f"RemnaUser '{keystone_user.telegram_id}' connected for the first time")
            await self.notification_service.system_notify(
                ntf_type=SystemNotificationType.USER_FIRST_CONNECTED,
                payload=MessagePayload.not_deleted(
                    i18n_key="ntf-event-user-first-connected",
                    i18n_kwargs=i18n_kwargs,
                    reply_markup=get_user_keyboard(user.telegram_id),
                ),
            )

        elif event in {
            RemnaUserEvent.EXPIRES_IN_72_HOURS,
            RemnaUserEvent.EXPIRES_IN_48_HOURS,
            RemnaUserEvent.EXPIRES_IN_24_HOURS,
            RemnaUserEvent.EXPIRED_24_HOURS_AGO,
        }:
            logger.debug(
                f"Sending expiration notification for RemnaUser '{keystone_user.telegram_id}'"
            )
            expire_map = {
                RemnaUserEvent.EXPIRES_IN_72_HOURS: UserNotificationType.EXPIRES_IN_3_DAYS,
                RemnaUserEvent.EXPIRES_IN_48_HOURS: UserNotificationType.EXPIRES_IN_2_DAYS,
                RemnaUserEvent.EXPIRES_IN_24_HOURS: UserNotificationType.EXPIRES_IN_1_DAYS,
                RemnaUserEvent.EXPIRED_24_HOURS_AGO: UserNotificationType.EXPIRED_1_DAY_AGO,
            }
            await send_subscription_expire_notification_task.kiq(
                keystone_user=keystone_user,
                ntf_type=expire_map[RemnaUserEvent(event)],
                i18n_kwargs=i18n_kwargs,
            )
        else:
            logger.warning(f"Unhandled user event '{event}' for '{keystone_user.telegram_id}'")

    async def handle_device_event(
        self,
        event: str,
        keystone_user: RemnaUserDto,
        device: HwidUserDeviceDto,
    ) -> None:
        logger.info(f"Received device event '{event}' for RemnaUser '{keystone_user.telegram_id}'")

        if not keystone_user.telegram_id:
            logger.debug(f"Skipping RemnaUser '{keystone_user.username}': telegram_id is empty")
            return

        user = await self.user_service.get(telegram_id=keystone_user.telegram_id)

        if not user:
            logger.warning(f"No local user found for telegram_id '{keystone_user.telegram_id}'")
            return

        if event == RemnaUserHwidDevicesEvent.ADDED:
            logger.debug(f"Device '{device.hwid}' added for RemnaUser '{keystone_user.telegram_id}'")
            i18n_key = "ntf-event-user-hwid-added"

        elif event == RemnaUserHwidDevicesEvent.DELETED:
            logger.debug(f"Device '{device.hwid}' deleted for RemnaUser '{keystone_user.telegram_id}'")
            i18n_key = "ntf-event-user-hwid-deleted"

        else:
            logger.warning(
                f"Unhandled device event '{event}' for RemnaUser '{keystone_user.telegram_id}'"
            )
            return

        await self.notification_service.system_notify(
            ntf_type=SystemNotificationType.USER_HWID,
            payload=MessagePayload.not_deleted(
                i18n_key=i18n_key,
                i18n_kwargs={
                    "user_id": str(user.telegram_id),
                    "user_name": user.name,
                    "username": user.username or False,
                    "hwid": device.hwid,
                    "platform": device.platform,
                    "device_model": device.device_model,
                    "os_version": device.os_version,
                    "user_agent": device.user_agent,
                },
                reply_markup=get_user_keyboard(user.telegram_id),
            ),
        )

    async def handle_node_event(self, event: str, node: NodeDto) -> None:
        logger.info(f"Received node event '{event}' for node '{node.name}'")

        if event == RemnaNodeEvent.CONNECTION_LOST:
            logger.warning(f"Connection lost for node '{node.name}'")
            i18n_key = "ntf-event-node-connection-lost"

        elif event == RemnaNodeEvent.CONNECTION_RESTORED:
            logger.info(f"Connection restored for node '{node.name}'")
            i18n_key = "ntf-event-node-connection-restored"

        elif event == RemnaNodeEvent.TRAFFIC_NOTIFY:
            # TODO: Temporarily shutting down the node (and plans?) before the traffic is reset
            logger.debug(f"Traffic threshold reached on node '{node.name}'")
            i18n_key = "ntf-event-node-traffic"

        else:
            logger.warning(f"Unhandled node event '{event}' for node '{node.name}'")
            return

        await self.notification_service.system_notify(
            ntf_type=SystemNotificationType.NODE_STATUS,
            payload=MessagePayload.not_deleted(
                i18n_key=i18n_key,
                i18n_kwargs={
                    "country": format_country_code(code=node.country_code),
                    "name": node.name,
                    "address": node.address,
                    "port": str(node.port),
                    "traffic_used": i18n_format_bytes_to_unit(node.traffic_used_bytes),
                    "traffic_limit": i18n_format_bytes_to_unit(node.traffic_limit_bytes),
                    "last_status_message": node.last_status_message or False,
                    "last_status_change": node.last_status_change.strftime(DATETIME_FORMAT)
                    if node.last_status_change
                    else False,
                },
            ),
        )
