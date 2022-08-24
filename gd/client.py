from __future__ import annotations

from builtins import setattr as set_attribute
from datetime import timedelta
from types import TracebackType as Traceback
from typing import (
    Any,
    AsyncIterator,
    Generator,
    Generic,
    Iterable,
    Iterator,
    Optional,
    Tuple,
    Type,
    TypeVar,
    Union,
    overload,
)

from attrs import define, field, frozen
from iters.async_iters import wrap_async_iter
from typing_extensions import ParamSpec
from yarl import URL

from gd.api.database import Database
from gd.api.recording import Recording

# from gd.api.recording import Recording
from gd.artist import Artist
from gd.async_utils import maybe_await, run, run_iterables
from gd.comments import Comment, LevelComment, UserComment
from gd.constants import (
    COMMENT_PAGE_SIZE,
    DEFAULT_AS_MOD,
    DEFAULT_CHEST_COUNT,
    DEFAULT_COINS,
    DEFAULT_COUNT,
    DEFAULT_ID,
    DEFAULT_LOW_DETAIL,
    DEFAULT_OBJECT_COUNT,
    DEFAULT_PAGE,
    DEFAULT_PAGES,
    DEFAULT_SPECIAL,
    DEFAULT_STARS,
    DEFAULT_USE_CLIENT,
    DEFAULT_VERSION,
    EMPTY,
    UNKNOWN,
    UNNAMED,
)
from gd.credentials import Credentials
from gd.decorators import check_client_login, check_login
from gd.encoding import Key, encode_robtop_string
from gd.enums import (
    AccountURLType,
    CommentState,
    CommentStrategy,
    DemonDifficulty,
    FriendRequestState,
    FriendRequestType,
    IconType,
    LeaderboardStrategy,
    LevelLeaderboardStrategy,
    LevelLength,
    MessageState,
    MessageType,
    RelationshipType,
    RewardType,
    SimpleRelationshipType,
    TimelyType,
    UnlistedType,
)
from gd.errors import ClientError, MissingAccess, NothingFound
from gd.events.controller import Controller
from gd.events.listeners import Listener
from gd.filters import Filters
from gd.friend_request import FriendRequest
from gd.http import HTTPClient
from gd.level import Level
from gd.level_packs import Gauntlet, MapPack
from gd.message import Message
from gd.models import LevelModel, SearchLevelsResponseModel
from gd.password import Password
from gd.relationship import Relationship
from gd.rewards import Chest, Quest
from gd.session import Session
from gd.song import Song
from gd.typing import (
    AnyCallable,
    AnyException,
    DynamicTuple,
    IntString,
    MaybeAwaitable,
    MaybeIterable,
    Predicate,
    URLString,
)
from gd.user import User

__all__ = ("Client",)

P = ParamSpec("P")
T = TypeVar("T")

F = TypeVar("F", bound=AnyCallable)


def switch_none(value: Optional[T], default: T) -> T:
    return default if value is None else value


def by_subject_and_user(subject: str, user: User) -> Predicate[Message]:
    def predicate(message: Message) -> bool:
        return message.subject == subject and message.user.id == user.id

    return predicate


def by_user(user: User) -> Predicate[FriendRequest]:
    def predicate(friend_request: FriendRequest) -> bool:
        return friend_request.user.id == user.id

    return predicate


CONTROLLER_ALREADY_CREATED = "controller was already created"
NO_DATABASE = "no database to save"

DEFAULT_LOAD_AFTER_POST = True

C = TypeVar("C", bound="Client")


@define()
class Client:
    session: Session = field()
    """The session of the client."""

    credentials: Credentials = field(factory=Credentials)
    """The credentials of the client."""

    database: Optional[Database] = field(default=None, repr=False)
    """The database of the client."""

    load_after_post: bool = field(default=DEFAULT_LOAD_AFTER_POST)
    """Whether to load items after posting them."""

    _listeners: DynamicTuple[Listener] = field(default=(), repr=False, init=False)
    _controller: Optional[Controller] = field(default=None, repr=False, init=False)

    def __init__(
        self,
        credentials: Optional[Credentials] = None,
        database: Optional[Database] = None,
        *,
        credentials_type: Type[Credentials] = Credentials,
        session_type: Type[Session] = Session,
        load_after_post: bool = DEFAULT_LOAD_AFTER_POST,
        **http_keywords: Any,
    ) -> None:
        if credentials is None:
            credentials = credentials_type()

        self.__attrs_init__(
            session=session_type(**http_keywords),
            credentials=credentials,
            database=database,
            load_after_post=load_after_post,
        )

    def apply_items(
        self: C,
        credentials: Optional[Credentials] = None,
        database: Optional[Database] = None,
        credentials_type: Type[Credentials] = Credentials,
    ) -> C:
        if credentials is None:
            self.credentials = credentials_type()

        else:
            self.credentials = credentials

        self.database = database

        return self

    def reset_items(self: C) -> C:
        return self.apply_items()

    def is_logged_in(self) -> bool:
        """Checks if the client is logged in.

        Returns:
            Whether the client is logged in.
        """
        return self.credentials.is_loaded()

    def run(self, maybe_awaitable: MaybeAwaitable[T]) -> T:
        return run(maybe_await(maybe_awaitable))

    @property
    def account_id(self) -> int:
        """The account ID of the client."""
        return self.credentials.account_id

    @property
    def id(self) -> int:
        """The user ID of the client."""
        return self.credentials.id

    @property
    def name(self) -> str:
        """The name of the client."""
        return self.credentials.name

    @property
    def password(self) -> str:
        """The password of the client."""
        return self.credentials.password

    @property
    def http(self) -> HTTPClient:
        """The [`HTTPClient`][gd.http.HTTPClient] used by the client."""
        return self.session.http

    @property
    def encoded_password(self) -> str:
        """The encoded password of the client."""
        return encode_robtop_string(self.password, Key.USER_PASSWORD)

    @property  # type: ignore
    @check_login
    def user(self) -> User:
        """The user representing the client."""
        return User(id=self.id, name=self.name, account_id=self.account_id).attach_client(self)

    async def ping(self) -> timedelta:
        """Pings the Geometry Dash server.

        Returns:
            The [`timedelta`][datetime.timedelta] representing the latency.
        """
        return await self.ping_url(self.http.url)

    async def ping_url(self, url: URLString) -> timedelta:
        """Pings the given `url`.

        Returns:
            The [`timedelta`][datetime.timedelta] representing the latency.
        """
        return await self.session.ping(url)

    async def logout(self) -> None:
        """Performs the logout."""
        self.reset_items()

    def login(self: C, name: str, password: str) -> LoginContextManager[C]:
        """Performs the login.

        This function returns a context manager that can be used for temporarily logging in:

        ```python
        async with client.login(name, password):
            assert client.is_logged_in()

        assert not client.is_logged_in()
        ```

        Returns:
            The [`LoginContextManager`][gd.client.LoginContextManager] for handling login process.
        """
        return LoginContextManager(self, name, password)

    async def try_login(self, name: str, password: str) -> None:
        model = await self.session.login(name, password)

        self.apply_items(Credentials(model.account_id, model.id, name, password))

    def unsafe_login(self: C, name: str, password: str) -> UnsafeLoginContextManager[C]:
        """Performs the *unsafe* login.

        *Unsafe* means that the credentials are not confirmed.

        This function returns a context manager that can be used for temporarily logging in:

        ```python
        async with client.unsafe_login(name, password):
            assert client.is_logged_in()

        assert not client.is_logged_in()
        ```

        Returns:
            The [`UnsafeLoginContextManager`][gd.client.UnsafeLoginContextManager]
                for handling login process.
        """
        return UnsafeLoginContextManager(self, name, password)

    async def try_unsafe_login(self, name: str, password: str) -> None:
        user = await self.search_user(name, simple=True)

        self.apply_items(Credentials(user.account_id, user.id, name, password))

    @check_login
    async def load(self) -> Database:
        """Loads the save from the cloud, saving it in the
        [`database`][gd.client.Client.database] attribute.

        Note:
            This function requires the client to be logged in.

        Returns:
            The database loaded.
        """
        database = await self.session.load(
            account_id=self.account_id, name=self.name, password=self.password
        )

        self.database = database

        return database

    @check_login
    async def save(self, database: Optional[Database] = None) -> None:
        """Saves the the `database` to the cloud, optionally fetching it from the
        [`database`][gd.client.Client.database] attribute.

        Note:
            This function requires the client to be logged in.
        """
        if database is None:
            database = self.database

            if database is None:
                raise MissingAccess(NO_DATABASE)

        await self.session.save(
            database, account_id=self.account_id, name=self.name, password=self.password
        )

    async def get_account_url(self, account_id: int, type: AccountURLType) -> URL:
        return await self.session.get_account_url(account_id=account_id, type=type)

    @check_login
    async def update_profile(
        self,
        stars: Optional[int] = None,
        diamonds: Optional[int] = None,
        secret_coins: Optional[int] = None,
        user_coins: Optional[int] = None,
        demons: Optional[int] = None,
        icon_type: Optional[IconType] = None,
        icon_id: Optional[int] = None,
        color_1_id: Optional[int] = None,
        color_2_id: Optional[int] = None,
        glow: Optional[bool] = None,
        cube_id: Optional[int] = None,
        ship_id: Optional[int] = None,
        ball_id: Optional[int] = None,
        ufo_id: Optional[int] = None,
        wave_id: Optional[int] = None,
        robot_id: Optional[int] = None,
        spider_id: Optional[int] = None,
        # swing_copter_id: Optional[int] = None,
        explosion_id: Optional[int] = None,
        special: int = DEFAULT_SPECIAL,
        *,
        set_as_user: Optional[User] = None,
    ) -> None:
        if set_as_user is None:
            user = await self.get_self()

        else:
            user = set_as_user

        await self.session.update_profile(
            stars=switch_none(stars, user.stars),
            diamonds=switch_none(diamonds, user.diamonds),
            secret_coins=switch_none(secret_coins, user.secret_coins),
            user_coins=switch_none(user_coins, user.user_coins),
            demons=switch_none(demons, user.demons),
            icon_type=switch_none(icon_type, user.icon_type),
            icon_id=switch_none(icon_id, user.icon_id),
            color_1_id=switch_none(color_1_id, user.color_1_id),
            color_2_id=switch_none(color_2_id, user.color_2_id),
            glow=switch_none(glow, user.glow),
            cube_id=switch_none(cube_id, user.cube_id),
            ship_id=switch_none(ship_id, user.ship_id),
            ball_id=switch_none(ball_id, user.ball_id),
            ufo_id=switch_none(ufo_id, user.ufo_id),
            wave_id=switch_none(wave_id, user.wave_id),
            robot_id=switch_none(robot_id, user.robot_id),
            spider_id=switch_none(spider_id, user.spider_id),
            # swing_copter_id=switch_none(swing_copter_id, user.swing_copter_id),
            explosion_id=switch_none(explosion_id, user.explosion_id),
            special=special,
            account_id=self.account_id,
            name=self.name,
            encoded_password=self.encoded_password,
        )

    @check_login
    async def update_settings(
        self,
        message_state: Optional[MessageState] = None,
        friend_request_state: Optional[FriendRequestState] = None,
        comment_state: Optional[CommentState] = None,
        youtube: Optional[str] = None,
        twitter: Optional[str] = None,
        twitch: Optional[str] = None,
        # discord: Optional[str] = None,
        *,
        set_as_user: Optional[User] = None,
    ) -> None:
        if set_as_user is None:
            user = await self.get_self(simple=True)

        else:
            user = set_as_user

        await self.session.update_settings(
            message_state=switch_none(message_state, user.message_state),
            friend_request_state=switch_none(friend_request_state, user.friend_request_state),
            comment_state=switch_none(comment_state, user.comment_state),
            youtube=switch_none(youtube, user.youtube),
            twitter=switch_none(twitter, user.twitter),
            twitch=switch_none(twitch, user.twitch),
            # discord=switch_none(discord, user.discord),
            account_id=self.account_id,
            encoded_password=self.encoded_password,
        )

    @check_login
    async def get_self(self, simple: bool = False) -> User:
        """Gets the user representing this client.

        This is a shorthand for:

        ```python
        await client.get_user(client.account_id, simple=simple)
        ```

        Arguments:
            simple: Whether to fetch simple information.

        Note:
            This function requires the client to be logged in.

        Returns:
            The [`User`][gd.user.User] representing the client.
        """
        return await self.get_user(self.account_id, simple=simple)

    async def get_user(
        self, account_id: int, simple: bool = False, friend_state: bool = False
    ) -> User:
        if friend_state:  # if we need to find friend state
            check_client_login(self)

            profile_model = await self.session.get_user_profile(  # request profile
                account_id=account_id,
                client_account_id=self.account_id,
                encoded_password=self.encoded_password,
            )

        else:  # otherwise, just request normally
            profile_model = await self.session.get_user_profile(account_id=account_id)

        if simple:  # if only the profile is needed, return right away
            return User.from_profile_model(profile_model).attach_client(self)

        search_model = await self.session.search_user(profile_model.id)  # search by ID

        return User.from_search_user_and_profile_models(search_model, profile_model).attach_client(
            self
        )

    async def search_user(
        self, query: IntString, simple: bool = False, friend_state: bool = False
    ) -> User:
        search_user_model = await self.session.search_user(query=query)  # search using query

        if simple:  # if only simple is required, return right away
            return User.from_search_user_model(search_user_model)

        if friend_state:  # if friend state is requested
            check_client_login(self)  # assert client is logged in

            profile_model = await self.session.get_user_profile(  # request profile
                search_user_model.account_id,
                client_account_id=self.account_id,
                encoded_password=self.encoded_password,
            )

        else:  # otherwise, request normally
            profile_model = await self.session.get_user_profile(account_id=search_user_model.account_id)

        return User.from_search_user_and_profile_models(
            search_user_model, profile_model
        ).attach_client(self)

    @wrap_async_iter
    async def search_users_on_page(
        self, query: IntString, page: int = DEFAULT_PAGE
    ) -> AsyncIterator[User]:
        search_users_response_model = await self.session.search_users_on_page(query=query, page=page)

        for search_user_model in search_users_response_model.users:
            yield User.from_search_user_model(search_user_model).attach_client(self)

    @wrap_async_iter
    def search_users(
        self,
        query: IntString,
        pages: Iterable[int] = DEFAULT_PAGES,
    ) -> AsyncIterator[User]:
        return run_iterables(
            (self.search_users_on_page(query=query, page=page).unwrap() for page in pages),
            ClientError,
        )

    @wrap_async_iter
    @check_login
    async def get_simple_relationships(self, type: SimpleRelationshipType) -> AsyncIterator[User]:
        try:
            response_model = await self.session.get_simple_relationships(
                type=type,
                account_id=self.account_id,
                encoded_password=self.encoded_password,
            )

        except NothingFound:
            return

        for model in response_model.users:
            yield User.from_relationship_user_model(model).attach_client(self)

    @wrap_async_iter
    @check_login
    def get_friends(self) -> AsyncIterator[User]:
        return self.get_simple_relationships(SimpleRelationshipType.FRIEND).unwrap()

    @wrap_async_iter
    @check_login
    def get_blocked(self) -> AsyncIterator[User]:
        return self.get_simple_relationships(SimpleRelationshipType.BLOCKED).unwrap()

    @wrap_async_iter
    @check_login
    async def get_relationships(self) -> AsyncIterator[Relationship]:
        async for friend in self.get_friends():
            yield friend.into_relationship(RelationshipType.FRIEND)

        async for blocked in self.get_blocked():
            yield blocked.into_relationship(RelationshipType.BLOCKED)

        async for friend_request in self.get_friend_requests(type=FriendRequestType.INCOMING):
            yield friend_request.into_relationship()

        async for friend_request in self.get_friend_requests(type=FriendRequestType.OUTGOING):
            yield friend_request.into_relationship()

    @wrap_async_iter
    async def get_leaderboard(
        self,
        strategy: LeaderboardStrategy = LeaderboardStrategy.DEFAULT,
        count: int = DEFAULT_COUNT,
    ) -> AsyncIterator[User]:
        response_model = await self.session.get_leaderboard(
            strategy=strategy,
            count=count,
            account_id=self.account_id,
            encoded_password=self.encoded_password,
        )

        for model in response_model.users:
            yield User.from_leaderboard_user_model(model).attach_client(self)

    def level_models_from_model(
        self, response_model: SearchLevelsResponseModel
    ) -> Iterator[Tuple[LevelModel, User, Song]]:
        songs = (Song.from_model(model).attach_client(self) for model in response_model.songs)
        creators = (User.from_creator_model(model).attach_client(self) for model in response_model.creators)

        id_to_song = {song.id: song for song in songs}
        id_to_creator = {creator.id: creator for creator in creators}

        for model in response_model.levels:
            song = id_to_song.get(model.custom_song_id)

            if song is None:
                song = Song.official(model.official_song_id, server_style=True).attach_client(self)

            creator = id_to_creator.get(model.creator_id)

            if creator is None:
                creator = User.default().attach_client(self)

            yield (model, creator, song)

    async def get_daily(self, use_client: bool = DEFAULT_USE_CLIENT) -> Level:
        return await self.get_timely(TimelyType.DAILY, use_client=use_client)

    async def get_weekly(self, use_client: bool = DEFAULT_USE_CLIENT) -> Level:
        return await self.get_timely(TimelyType.WEEKLY, use_client=use_client)

    # async def get_event(self, use_client: bool = DEFAULT_USE_CLIENT) -> Level:
    #     return await self.get_timely(TimelyType.EVENT, use_client=use_client)

    async def get_timely(self, type: TimelyType, use_client: bool = DEFAULT_USE_CLIENT) -> Level:
        timely_model = await self.session.get_timely_info(type)

        level = await self.get_level(type.into_timely_id().value)

        return level.update_with_timely_model(timely_model)

    async def get_level(self, level_id: int, get_data: bool = True, use_client: bool = False) -> Level:
        get_data = get_data or level_id < 0

        if get_data:
            if use_client:
                check_client_login(self)

                response_model = await self.session.get_level(
                    level_id, account_id=self.account_id, encoded_password=self.encoded_password
                )

            else:
                response_model = await self.session.get_level(level_id)

            model = response_model.level

            level_id = model.id

        level = await self.search_levels_on_page(level_id).next()

        if get_data:
            return Level.from_model(model, level.creator, level.song).attach_client(self)

        return level

    @wrap_async_iter
    async def search_levels_on_page(
        self,
        query: Optional[MaybeIterable[IntString]] = None,
        page: int = DEFAULT_PAGE,
        filters: Optional[Filters] = None,
        user: Optional[User] = None,
        gauntlet: Optional[int] = None,
    ) -> AsyncIterator[Level]:
        if user is None:
            user_id = None

        else:
            user_id = user.id

        try:
            response_model = await self.session.search_levels_on_page(
                query,
                page,
                filters,
                user_id,
                gauntlet,
                client_account_id=self.account_id,
                client_user_id=self.id,
                encoded_password=self.encoded_password,
            )

        except NothingFound:
            return

        for model, creator, song in self.level_models_from_model(response_model):
            yield Level.from_model(model, creator, song).attach_client(self)

    @wrap_async_iter
    def search_levels(
        self,
        query: Optional[Union[int, str]] = None,
        pages: Iterable[int] = DEFAULT_PAGES,
        filters: Optional[Filters] = None,
        user: Optional[User] = None,
        gauntlet: Optional[int] = None,
    ) -> AsyncIterator[Level]:
        return run_iterables(
            (
                self.search_levels_on_page(
                    query=query,
                    page=page,
                    filters=filters,
                    user=user,
                    gauntlet=gauntlet,
                ).unwrap()
                for page in pages
            ),
            ClientError,
        )

    @check_login
    async def update_level_description(self, level: Level, description: Optional[str]) -> None:
        await self.session.update_level_description(
            level_id=level.id,
            description=description,
            account_id=self.account_id,
            encoded_password=self.encoded_password,
        )

    async def upload_level(
        self,
        name: str = UNKNOWN,
        id: int = DEFAULT_ID,
        version: int = DEFAULT_VERSION,
        length: LevelLength = LevelLength.DEFAULT,
        official_song_id: int = DEFAULT_ID,
        description: str = EMPTY,
        song_id: int = DEFAULT_ID,
        original: int = DEFAULT_ID,
        two_player: bool = False,
        type: UnlistedType = UnlistedType.DEFAULT,
        object_count: int = DEFAULT_OBJECT_COUNT,
        coins: int = DEFAULT_COINS,
        stars: int = DEFAULT_STARS,
        low_detail: bool = DEFAULT_LOW_DETAIL,
        password: Optional[Password] = None,
        recording: Optional[Recording] = None,
        editor_time: Optional[timedelta] = None,
        copies_time: Optional[timedelta] = None,
        data: str = EMPTY,
    ) -> Level:
        level_id = await self.session.upload_level(
            name=name,
            id=id,
            version=version,
            length=length,
            official_song_id=official_song_id,
            description=description,
            song_id=song_id,
            original=original,
            two_player=two_player,
            object_count=object_count,
            coins=coins,
            stars=stars,
            type=type,
            low_detail=low_detail,
            password=password,
            recording=recording,
            editor_time=editor_time,
            copies_time=copies_time,
            data=data,
            account_id=self.account_id,
            account_name=self.name,
            encoded_password=self.encoded_password,
        )

        return await self.get_level(level_id)

    async def report_level(self, level: Level) -> None:
        await self.session.report_level(level.id)

    @check_login
    async def delete_level(self, level: Level) -> None:
        await self.session.delete_level(
            level.id, account_id=self.account_id, encoded_password=self.encoded_password
        )

    @check_login
    async def rate_level(self, level: Level, stars: int) -> None:
        await self.session.rate_level(
            level.id,
            stars,
            account_id=self.account_id,
            encoded_password=self.encoded_password,
        )

    @check_login
    async def rate_demon(
        self,
        level: Level,
        rating: DemonDifficulty,
        as_mod: bool = DEFAULT_AS_MOD,
    ) -> None:
        await self.session.rate_demon(
            level.id,
            rating,
            as_mod=as_mod,
            account_id=self.account_id,
            encoded_password=self.encoded_password,
        )

    @check_login
    async def suggest_level(self, level: Level, stars: int, feature: bool) -> None:
        return await self.session.suggest_level(
            level.id,
            stars,
            feature,
            account_id=self.account_id,
            encoded_password=self.encoded_password,
        )

    @wrap_async_iter
    @check_login
    async def get_level_leaderboard(
        self,
        level: Level,
        strategy: LevelLeaderboardStrategy = LevelLeaderboardStrategy.ALL,
    ) -> AsyncIterator[User]:
        response_model = await self.session.get_level_leaderboard(
            level_id=level.id,
            strategy=strategy,
            account_id=self.account_id,
            encoded_password=self.encoded_password,
        )

        for model in response_model.users:
            yield User.from_level_leaderboard_user_model(model).attach_client(self)

    @check_login
    async def block_user(self, user: User) -> None:
        await self.session.block_user(
            account_id=user.account_id,
            client_account_id=self.account_id,
            encoded_password=self.encoded_password,
        )

    @check_login
    async def unblock_user(self, user: User) -> None:
        await self.session.unblock_user(
            account_id=user.account_id,
            client_account_id=self.account_id,
            encoded_password=self.encoded_password,
        )

    @check_login
    async def unfriend_user(self, user: User) -> None:
        await self.session.unfriend_user(
            account_id=user.account_id,
            client_account_id=self.account_id,
            encoded_password=self.encoded_password,
        )

    @check_login
    async def send_message(
        self, user: User, subject: Optional[str] = None, content: Optional[str] = None
    ) -> Optional[Message]:
        await self.session.send_message(
            account_id=user.account_id,
            subject=subject,
            content=content,
            client_account_id=self.account_id,
            encoded_password=self.encoded_password,
        )

        if self.load_after_post:
            if subject is None:
                subject = EMPTY

            messages = self.get_messages_on_page(type=MessageType.OUTGOING)
            message = await messages.find(by_subject_and_user(subject, user))

            if message is None:
                return None

            message.content = content

            return message

        return None

    @check_login
    async def get_message(self, message_id: int, type: MessageType) -> Message:
        model = await self.session.get_message(
            message_id=message_id,
            type=type,
            account_id=self.account_id,
            encoded_password=self.encoded_password,
        )

        return Message.from_model(model).attach_client(self)

    @check_login
    async def delete_message(self, message: Message) -> None:
        await self.session.delete_message(
            message_id=message.id,
            type=message.type,
            account_id=self.account_id,
            encoded_password=self.encoded_password,
        )

    @wrap_async_iter
    @check_login
    async def get_messages_on_page(
        self, type: MessageType = MessageType.DEFAULT, page: int = DEFAULT_PAGE
    ) -> AsyncIterator[Message]:

        try:
            response_model = await self.session.get_messages_on_page(
                type=type,
                page=page,
                account_id=self.account_id,
                encoded_password=self.encoded_password,
            )

        except NothingFound:
            return

        for model in response_model.messages:
            yield Message.from_model(model).attach_client(self)

    @wrap_async_iter
    @check_login
    def get_messages(
        self,
        type: MessageType = MessageType.DEFAULT,
        pages: Iterable[int] = DEFAULT_PAGES,
    ) -> AsyncIterator[Message]:
        return run_iterables(
            (self.get_messages_on_page(type=type, page=page).unwrap() for page in pages),
            ClientError,
        )

    @check_login
    async def send_friend_request(
        self, user: User, message: Optional[str] = None
    ) -> Optional[FriendRequest]:
        await self.session.send_friend_request(
            account_id=user.account_id,
            message=message,
            client_account_id=self.account_id,
            encoded_password=self.encoded_password,
        )

        if self.load_after_post:
            friend_requests = self.get_friend_requests_on_page(type=FriendRequestType.OUTGOING)

            return await friend_requests.find(by_user(user))

        return None

    @check_login
    async def delete_friend_request(self, friend_request: FriendRequest) -> None:
        await self.session.delete_friend_request(
            account_id=friend_request.user.account_id,
            type=friend_request.type,
            client_account_id=self.account_id,
            encoded_password=self.encoded_password,
        )

    @check_login
    async def accept_friend_request(self, friend_request: FriendRequest) -> None:
        await self.session.accept_friend_request(
            account_id=friend_request.user.account_id,
            request_id=friend_request.id,
            type=friend_request.type,
            client_account_id=self.account_id,
            encoded_password=self.encoded_password,
        )

    @check_login
    async def read_friend_request(self, friend_request: FriendRequest) -> None:
        await self.session.read_friend_request(
            request_id=friend_request.id,
            account_id=self.account_id,
            encoded_password=self.encoded_password,
        )

    @wrap_async_iter
    @check_login
    async def get_friend_requests_on_page(
        self,
        type: FriendRequestType = FriendRequestType.DEFAULT,
        page: int = DEFAULT_PAGE,
    ) -> AsyncIterator[FriendRequest]:
        try:
            response_model = await self.session.get_friend_requests_on_page(
                type=type,
                page=page,
                account_id=self.account_id,
                encoded_password=self.encoded_password,
            )

        except NothingFound:
            return

        for model in response_model.friend_requests:
            yield FriendRequest.from_model(model, type).attach_client(self)

    @wrap_async_iter
    @check_login
    def get_friend_requests(
        self,
        type: FriendRequestType = FriendRequestType.DEFAULT,
        pages: Iterable[int] = DEFAULT_PAGES,
    ) -> AsyncIterator[FriendRequest]:
        return run_iterables(
            (self.get_friend_requests_on_page(type=type, page=page).unwrap() for page in pages),
            ClientError,
        )

    @check_login
    async def like_level(self, level: Level) -> None:
        await self.session.like_level(
            level.id,
            dislike=False,
            account_id=self.account_id,
            encoded_password=self.encoded_password,
        )

    @check_login
    async def dislike_level(self, level: Level) -> None:
        await self.session.like_level(
            level.id,
            dislike=True,
            account_id=self.account_id,
            encoded_password=self.encoded_password,
        )

    @check_login
    async def like_user_comment(self, comment: UserComment) -> None:
        await self.session.like_user_comment(
            comment.id,
            dislike=False,
            account_id=self.account_id,
            encoded_password=self.encoded_password,
        )

    @check_login
    async def dislike_user_comment(self, comment: UserComment) -> None:
        await self.session.like_user_comment(
            comment.id,
            dislike=True,
            account_id=self.account_id,
            encoded_password=self.encoded_password,
        )

    @check_login
    async def like_level_comment(self, comment: LevelComment) -> None:
        await self.session.like_level_comment(
            comment.id,
            comment.level.id,
            dislike=False,
            account_id=self.account_id,
            encoded_password=self.encoded_password,
        )

    @check_login
    async def dislike_level_comment(self, comment: LevelComment) -> None:
        await self.session.like_level_comment(
            comment.id,
            comment.level.id,
            dislike=True,
            account_id=self.account_id,
            encoded_password=self.encoded_password,
        )

    # post_comment
    # post_level_comment

    @check_login
    async def delete_comment(self, comment: UserComment) -> None:
        await self.session.delete_user_comment(
            comment_id=comment.id,
            account_id=self.account_id,
            encoded_password=self.encoded_password,
        )

    @check_login
    async def delete_level_comment(self, comment: LevelComment) -> None:
        await self.session.delete_level_comment(
            comment_id=comment.id,
            level_id=comment.level.id,
            account_id=self.account_id,
            encoded_password=self.encoded_password,
        )

    @wrap_async_iter
    async def get_user_comments_on_page(
        self,
        user: User,
        page: int = DEFAULT_PAGE,
    ) -> AsyncIterator[UserComment]:
        response_model = await self.session.get_user_comments_on_page(
            user_id=user.id,
            page=page,
        )

        for model in response_model.comments:
            yield Comment.from_model(model, client=self, user=user)

    @wrap_async_iter
    def get_user_comments(
        self,
        user: User,
        pages: Iterable[int] = DEFAULT_PAGES,
    ) -> AsyncIterator[UserComment]:
        return run_iterables(
            (
                self.get_user_comments_on_page(user=user, page=page).unwrap()
                for page in pages
            ),
            ClientError,
        )

    @wrap_async_iter
    async def get_user_level_comments_on_page(
        self,
        user: User,
        page: int = DEFAULT_PAGE,
        strategy: CommentStrategy = CommentStrategy.DEFAULT,
    ) -> AsyncIterator[LevelComment]:
        try:
            response_model = await self.session.get_user_level_comments_on_page(
                user_id=user.id,
                page=page,
                strategy=strategy,
            )

        except NothingFound:
            return

        for model in response_model.comments:
            yield Comment.from_model(model, client=self)

    @wrap_async_iter
    async def get_level_comments_on_page(
        self,
        level: Level,
        count: int = COMMENT_PAGE_SIZE,
        page: int = DEFAULT_PAGE,
        strategy: CommentStrategy = CommentStrategy.DEFAULT,
    ) -> AsyncIterator[LevelComment]:
        try:
            response_model = await self.session.get_level_comments_on_page(
                level_id=level.id,
                count=count,
                page=page,
                strategy=strategy,
            )

        except NothingFound:
            return

        for model in response_model.comments:
            yield Comment.from_model(model, client=self)

    @wrap_async_iter
    def get_level_comments(
        self,
        level: Level,
        count: int = COMMENT_PAGE_SIZE,
        pages: Iterable[int] = DEFAULT_PAGES,
        strategy: CommentStrategy = CommentStrategy.DEFAULT,
    ) -> AsyncIterator[LevelComment]:
        return run_iterables(
            (
                self.get_level_comments_on_page(
                    level=level, count=count, page=page, strategy=strategy
                ).unwrap()
                for page in pages
            ),
            ClientError,
        )

    @wrap_async_iter
    async def get_gauntlets(self) -> AsyncIterator[Gauntlet]:
        response_model = await self.session.get_gauntlets()

        for model in response_model.gauntlets:
            yield Gauntlet.from_model(model, client=self)

    @wrap_async_iter
    async def get_map_packs_on_page(self, page: int = DEFAULT_PAGE) -> AsyncIterator[MapPack]:
        response_model = await self.session.get_map_packs_on_page(page=page)

        for model in response_model.map_packs:
            yield MapPack.from_model(model, client=self)

    @wrap_async_iter
    def get_map_packs(self, pages: Iterable[int] = DEFAULT_PAGES) -> AsyncIterator[MapPack]:
        return run_iterables(
            (self.get_map_packs_on_page(page=page).unwrap() for page in pages),
            ClientError,
        )

    @wrap_async_iter
    @check_login
    async def get_quests(self) -> AsyncIterator[Quest]:
        response_model = await self.session.get_quests(
            account_id=self.account_id, encoded_password=self.encoded_password
        )

        model = response_model.inner

        for quest_model in (model.quest_1, model.quest_2, model.quest_3):

            yield Quest.from_model(quest_model, seconds=model.time_left, client=self)

    @wrap_async_iter
    @check_login
    async def get_chests(
        self,
        reward_type: RewardType = RewardType.DEFAULT,
        chest_1_count: int = DEFAULT_CHEST_COUNT,
        chest_2_count: int = DEFAULT_CHEST_COUNT,
    ) -> AsyncIterator[Chest]:
        response_model = await self.session.get_chests(
            reward_type=reward_type,
            chest_1_count=chest_1_count,
            chest_2_count=chest_2_count,
            account_id=self.account_id,
            encoded_password=self.encoded_password,
        )
        model = response_model.inner

        for (chest_model, time_left, count) in (
            (model.chest_1, model.chest_1_left, model.chest_1_count),
            (model.chest_2, model.chest_2_left, model.chest_2_count),
        ):
            yield Chest.from_model(chest_model, seconds=time_left, count=count, client=self)

    @wrap_async_iter
    async def get_featured_artists_on_page(self, page: int = DEFAULT_PAGE) -> AsyncIterator[Artist]:
        response_model = await self.session.get_featured_artists_on_page(page=page)

        for model in response_model.featured_artists:
            yield Song.from_model(model, custom=True, client=self)

    @wrap_async_iter
    def get_featured_artists(self, pages: Iterable[int] = DEFAULT_PAGES) -> AsyncIterator[Artist]:
        return run_iterables(
            (self.get_featured_artists_on_page(page=page).unwrap() for page in pages),
            ClientError,
        )

    async def get_song(self, song_id: int) -> Song:
        model = await self.session.get_song(song_id)

        return Song.from_model(model).attach_client(self)

    async def get_newgrounds_song(self, song_id: int) -> Song:
        model = await self.session.get_newgrounds_song(song_id)
        return Song.from_model(model, custom=True, client=self)

    @wrap_async_iter
    async def search_newgrounds_songs_on_page(
        self, query: str, page: int = DEFAULT_PAGE
    ) -> AsyncIterator[Song]:
        models = await self.session.search_newgrounds_songs_on_page(query=query, page=page)

        for model in models:
            yield Song.from_model(model, custom=True, client=self)

    @wrap_async_iter
    def search_newgrounds_songs(
        self, query: str, pages: Iterable[int] = DEFAULT_PAGES
    ) -> AsyncIterator[Song]:
        return run_iterables(
            (self.search_newgrounds_songs_on_page(query=query, page=page) for page in pages),
            ClientError,
        )

    @wrap_async_iter
    async def search_newgrounds_users_on_page(
        self, query: str, page: int = DEFAULT_PAGE
    ) -> AsyncIterator[Author]:
        data = await self.session.search_newgrounds_users_on_page(query=query, page=page)

        for part in data:
            yield Author.from_dict(part, client=self)  # type: ignore

    @wrap_async_iter
    def search_newgrounds_users(
        self, query: str, pages: Iterable[int] = DEFAULT_PAGES
    ) -> AsyncIterator[Artist]:
        return run_iterables(
            (self.search_newgrounds_users_on_page(query=query, page=page) for page in pages),
            ClientError,
        )

    @wrap_async_iter
    async def get_newgrounds_artist_songs_on_page(
        self, name: str, page: int = DEFAULT_PAGE
    ) -> AsyncIterator[Song]:
        models = await self.session.get_newgrounds_artist_songs_on_page(name=name, page=page)

        for model in models:
            yield Song.from_model(model).attach_client(self)

    @wrap_async_iter
    def get_newgrounds_artist_songs(
        self, name: str, pages: Iterable[int] = DEFAULT_PAGES
    ) -> AsyncIterator[Song]:
        return run_iterables(
            (self.get_newgrounds_artist_songs_on_page(name=name, page=page).unwrap() for page in pages),
            ClientError,
        )

    # events

    async def on_daily(self, level: Level) -> None:
        pass

    async def on_weekly(self, level: Level) -> None:
        pass

    async def on_rate(self, level: Level) -> None:
        pass

    async def on_level(self, level: Level) -> None:
        pass

    async def on_user_level(self, user: User, level: Level) -> None:
        pass

    async def on_message(self, message: Message) -> None:
        pass

    async def on_friend_request(self, friend_request: FriendRequest) -> None:
        pass

    async def on_level_comment(self, level: Level, comment: LevelComment) -> None:
        pass

    async def on_user_comment(self, user: User, comment: UserComment) -> None:
        pass

    # dispatchers

    async def dispatch_daily(self, level: Level) -> None:
        await self.on_daily(level)

    async def dispatch_weekly(self, level: Level) -> None:
        await self.on_weekly(level)

    async def dispatch_rate(self, level: Level) -> None:
        await self.on_rate(level)

    async def dispatch_level(self, level: Level) -> None:
        await self.on_level(level)

    async def dispatch_user_level(self, user: User, level: Level) -> None:
        await self.on_user_level(user, level)

    async def dispatch_message(self, message: Message) -> None:
        await self.on_message(message)

    async def dispatch_friend_request(self, friend_request: FriendRequest) -> None:
        await self.on_friend_request(friend_request)

    async def dispatch_level_comment(self, level: Level, comment: LevelComment) -> None:
        await self.on_level_comment(level, comment)

    async def dispatch_user_comment(self, user: User, comment: UserComment) -> None:
        await self.on_user_comment(user, comment)

    def event(self, function: F) -> F:
        """Registers an event handler.

        Example:
            ```python
            client = Client()

            DAILY = "new daily! {daily.name} by {daily.creator.name} (ID: {daily.id})

            @client.event
            async def on_daily(daily: Level) -> None:
                print(DAILY.format(daily=daily))
            ```

        Arguments:
            function: The function to register as an event handler.

        Returns:
            The function passed.
        """
        set_attribute(self, function.__name__, function)

        return function

    def add_listener(self, listener: Listener) -> None:
        self.check_controller()

        self._listeners = (*self._listeners, listener)

    def clear_listeners(self) -> None:
        self.check_controller()

        self._listeners = ()

    def remove_listener(self, listener: Listener) -> bool:
        self.check_controller()

        listeners = self._listeners

        length = len(listeners)

        self._listeners = listeners = tuple(
            present_listener for present_listener in listeners if present_listener is not listener
        )

        return len(listeners) < length

    def check_controller(self) -> None:
        if self._controller is not None:
            raise RuntimeError(CONTROLLER_ALREADY_CREATED)

    def create_controller(self) -> Controller:
        self.check_controller()

        self._controller = controller = Controller(self._listeners)

        return controller


E = TypeVar("E", bound=AnyException)


@frozen()
class LoginContextManager(Generic[C]):
    client: C
    name: str
    password: str

    async def login(self) -> None:
        await self.client.try_login(self.name, self.password)

    async def logout(self) -> None:
        await self.client.logout()

    def __await__(self) -> Generator[Any, None, None]:
        return self.login().__await__()

    async def __aenter__(self) -> C:
        await self.login()

        return self.client

    @overload
    async def __aexit__(self, error_type: None, error: None, traceback: None) -> None:
        ...

    @overload
    async def __aexit__(self, error_type: Type[E], error: E, traceback: Traceback) -> None:
        ...

    async def __aexit__(
        self, error_type: Optional[Type[E]], error: Optional[E], traceback: Optional[Traceback]
    ) -> None:
        await self.logout()


@frozen()
class UnsafeLoginContextManager(LoginContextManager[C]):
    async def login(self) -> None:
        await self.client.try_unsafe_login(self.name, self.password)
