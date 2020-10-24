from pathlib import Path

from gd.converters import get_actual_difficulty
from gd.decorators import cache_by
from gd.enums import DemonDifficulty, LevelDifficulty, LevelType
from gd.platform import LINUX, MACOS, WINDOWS
from gd.typing import Type, TypeVar, Union

from gd.text_utils import make_repr

from gd.memory.data import (
    Buffer,
    Data,
    boolean,
    int8,
    uint8,
    int16,
    uint16,
    int32,
    uint32,
    int64,
    uint64,
    float32,
    float64,
    string,
    get_pointer_type,
    get_size_type,
)

from gd.memory.internal import (
    allocate_memory as system_allocate_memory,
    free_memory as system_free_memory,
    get_base_address as system_get_base_address,
    get_base_address_from_handle as system_get_base_address_from_handle,
    open_process as system_open_process,
    close_process as system_close_process,
    get_process_id_from_name as system_get_process_id_from_name,
    get_process_id_from_window_title as system_get_process_id_from_window_title,
    inject_dll as system_inject_dll,
    terminate_process as system_terminate_process,
    protect_process_memory as system_protect_process_memory,
    read_process_memory as system_read_process_memory,
    write_process_memory as system_write_process_memory,
    linux_allocate_memory,
    linux_free_memory,
    # linux_get_base_address,
    linux_get_base_address_from_handle,
    linux_open_process,
    linux_close_process,
    linux_get_process_id_from_name,
    # linux_get_process_id_from_window_title,
    linux_inject_dll,
    linux_terminate_process,
    linux_protect_process_memory,
    linux_read_process_memory,
    linux_write_process_memory,
    macos_allocate_memory,
    macos_free_memory,
    # macos_get_base_address,
    macos_get_base_address_from_handle,
    macos_open_process,
    macos_close_process,
    macos_get_process_id_from_name,
    # macos_get_process_id_from_window_title,
    macos_inject_dll,
    macos_terminate_process,
    macos_protect_process_memory,
    macos_read_process_memory,
    macos_write_process_memory,
    windows_allocate_memory,
    windows_free_memory,
    windows_get_base_address,
    # windows_get_base_address_from_handle,
    windows_open_process,
    windows_close_process,
    windows_get_process_id_from_name,
    windows_get_process_id_from_window_title,
    windows_inject_dll,
    windows_terminate_process,
    windows_protect_process_memory,
    windows_read_process_memory,
    windows_write_process_memory,
)
from gd.memory.offsets import offsets, linux_offsets, macos_offsets, windows_offsets

__all__ = (
    "Address",
    "GameManager",
    "PlayLayer",
    "EditorLayer",
    "LevelSettingsLayer",
    "GameLevel",
    "State",
    "SystemState",
    "LinuxState",
    "MacOSState",
    "WindowsState",
)

DEFAULT_WINDOW_TITLE = "Geometry Dash"

MACOS_STRING_SIZE_OFFSET = -0x18
WINDOWS_STRING_SIZE_OFFSET = 0x10

AddressT = TypeVar("AddressT", bound="Address")
AddressU = TypeVar("AddressU", bound="Address")

T = TypeVar("T")


class SystemState:
    def __init__(
        self,
        process_name: str,
        bits: int,
        window_title: str = DEFAULT_WINDOW_TITLE,
        load: bool = True,
    ) -> None:
        self.process_name = process_name
        self.window_title = window_title

        self.bits = bits

        self.pointer_type = get_pointer_type(bits)
        self.size_type = get_size_type(bits)

        self.process_id = 0
        self.process_handle = 0
        self.base_address = 0

        self.loaded = False

        if load:
            self.load()

    @property  # type: ignore
    @cache_by("bits")
    def byte_type(self) -> Data[int]:
        return int8

    @property  # type: ignore
    @cache_by("bits")
    def ubyte_type(self) -> Data[int]:
        return uint8

    @property  # type: ignore
    @cache_by("bits")
    def short_type(self) -> Data[int]:
        return int16

    @property  # type: ignore
    @cache_by("bits")
    def ushort_type(self) -> Data[int]:
        return uint16

    @property  # type: ignore
    @cache_by("bits")
    def int_type(self) -> Data[int]:
        if self.bits >= 32:
            return int32

        return int16

    @property  # type: ignore
    @cache_by("bits")
    def uint_type(self) -> Data[int]:
        if self.bits >= 32:
            return uint32

        return uint16

    @property  # type: ignore
    @cache_by("bits")
    def long_type(self) -> Data[int]:
        if self.bits >= 64:
            return int64

        return int32

    @property  # type: ignore
    @cache_by("bits")
    def ulong_type(self) -> Data[int]:
        if self.bits >= 64:
            return uint64

        return uint32

    @property  # type: ignore
    @cache_by("bits")
    def longlong_type(self) -> Data[int]:
        return int64

    @property  # type: ignore
    @cache_by("bits")
    def ulonglong_type(self) -> Data[int]:
        return uint64

    def __repr__(self) -> str:
        info = {
            "process_id": self.process_id,
            "process_handle": hex(self.process_handle),
            "base_address": hex(self.base_address),
            "pointer_type": self.pointer_type,
        }

        return make_repr(self, info)

    def unload(self) -> None:
        self.process_id = 0
        self.process_handle = 0
        self.base_address = 0

        self.loaded = False

    def is_loaded(self) -> bool:
        return self.loaded

    # REGION: TO BE IMPLEMENTED IN SUBCLASSES

    def load(self) -> None:
        try:
            self.process_id = system_get_process_id_from_name(self.process_name)

        except LookupError:
            self.process_id = system_get_process_id_from_window_title(self.window_title)

            if not self.process_id:
                raise

        self.process_handle = system_open_process(self.process_id)

        try:
            self.base_address = system_get_base_address_from_handle(self.process_handle)

        except NotImplementedError:
            pass

        self.base_address = system_get_base_address(self.process_id, self.process_name)

        self.loaded = True

    reload = load

    def allocate_memory(self, address: int, size: int) -> int:
        return system_allocate_memory(self.process_handle, address, size)

    def free_memory(self, address: int, size: int) -> None:
        return system_free_memory(self.process_handle, address, size)

    def protect_at(self, address: int, size: int) -> int:
        return system_protect_process_memory(self.process_handle, address, size)

    def read_at(self, address: int, size: int) -> bytes:
        return system_read_process_memory(self.process_handle, address, size)

    def write_at(self, address: int, data: bytes) -> int:
        return system_write_process_memory(self.process_handle, address, data)

    def inject_dll(self, path: Union[str, Path]) -> bool:
        return system_inject_dll(self.process_id, path)

    def close(self) -> None:
        return system_close_process(self.process_handle)

    def terminate(self) -> bool:
        return system_terminate_process(self.process_handle)

    def read_string(self, address: int) -> str:
        raise NotImplementedError("read_string(address) is not implemented in base state.")

    def write_string(self, value: str, address: int) -> int:
        raise NotImplementedError("write_string(value, address) is not implemented in base state.")

    # END REGION

    def read_buffer(self, size: int, address: int) -> Buffer:
        return Buffer(self.read_at(address, size))

    def write_buffer(self, buffer: Buffer, address: int) -> int:
        return self.write_at(address, buffer.unwrap())

    def read(self, type: Data[T], address: int) -> T:
        return type.from_bytes(self.read_at(address, type.size))

    def write(self, type: Data[T], value: T, address: int) -> int:
        return self.write_at(address, type.to_bytes(value))

    def read_pointer(self, address: int) -> int:
        return self.read(self.pointer_type, address)

    def write_pointer(self, value: int, address: int) -> int:
        return self.write(self.pointer_type, value, address)

    def read_size(self, address: int) -> int:
        return self.read(self.size_type, address)

    def write_size(self, value: int, address: int) -> int:
        return self.write(self.size_type, value, address)

    def read_bool(self, address: int) -> bool:
        return self.read(boolean, address)

    def write_bool(self, value: bool, address: int) -> int:
        return self.write(boolean, value, address)

    def read_int8(self, address: int) -> int:
        return self.read(int8, address)

    def write_int8(self, value: int, address: int) -> int:
        return self.write(int8, value, address)

    def read_uint8(self, address: int) -> int:
        return self.read(uint8, address)

    def write_uint8(self, value: int, address: int) -> int:
        return self.write(uint8, value, address)

    def read_int16(self, address: int) -> int:
        return self.read(int16, address)

    def write_int16(self, value: int, address: int) -> int:
        return self.write(int16, value, address)

    def read_uint16(self, address: int) -> int:
        return self.read(uint16, address)

    def write_uint16(self, value: int, address: int) -> int:
        return self.write(uint16, value, address)

    def read_int32(self, address: int) -> int:
        return self.read(int32, address)

    def write_int32(self, value: int, address: int) -> int:
        return self.write(int32, value, address)

    def read_uint32(self, address: int) -> int:
        return self.read(uint32, address)

    def write_uint32(self, value: int, address: int) -> int:
        return self.write(uint32, value, address)

    def read_int64(self, address: int) -> int:
        return self.read(int64, address)

    def write_int64(self, value: int, address: int) -> int:
        return self.write(int64, value, address)

    def read_uint64(self, address: int) -> int:
        return self.read(uint64, address)

    def write_uint64(self, value: int, address: int) -> int:
        return self.write(uint64, value, address)

    def read_byte(self, address: int) -> int:
        return self.read(self.byte_type, address)

    def write_byte(self, value: int, address: int) -> int:
        return self.write(self.byte_type, value, address)

    def read_ubyte(self, address: int) -> int:
        return self.read(self.ubyte_type, address)

    def write_ubyte(self, value: int, address: int) -> int:
        return self.write(self.ubyte_type, value, address)

    def read_short(self, address: int) -> int:
        return self.read(self.short_type, address)

    def write_short(self, value: int, address: int) -> int:
        return self.write(self.short_type, value, address)

    def read_ushort(self, address: int) -> int:
        return self.read(self.ushort_type, address)

    def write_ushort(self, value: int, address: int) -> int:
        return self.write(self.ushort_type, value, address)

    def read_int(self, address: int) -> int:
        return self.read(self.int_type, address)

    def write_int(self, value: int, address: int) -> int:
        return self.write(self.int_type, value, address)

    def read_uint(self, address: int) -> int:
        return self.read(self.uint_type, address)

    def write_uint(self, value: int, address: int) -> int:
        return self.write(self.uint_type, value, address)

    def read_long(self, address: int) -> int:
        return self.read(self.long_type, address)

    def write_long(self, value: int, address: int) -> int:
        return self.write(self.long_type, value, address)

    def read_ulong(self, address: int) -> int:
        return self.read(self.ulong_type, address)

    def write_ulong(self, value: int, address: int) -> int:
        return self.write(self.ulong_type, value, address)

    def read_longlong(self, address: int) -> int:
        return self.read(self.longlong_type, address)

    def write_longlong(self, value: int, address: int) -> int:
        return self.write(self.longlong_type, value, address)

    def read_ulonglong(self, address: int) -> int:
        return self.read(self.ulonglong_type, address)

    def write_ulonglong(self, value: int, address: int) -> int:
        return self.write(self.ulonglong_type, value, address)

    def read_float32(self, address: int) -> float:
        return self.read(float32, address)

    def write_float32(self, value: float, address: int) -> int:
        return self.write(float32, value, address)

    def read_float64(self, address: int) -> float:
        return self.read(float64, address)

    def write_float64(self, value: float, address: int) -> int:
        return self.write(float64, value, address)

    def get_address(self) -> "Address":
        return Address(self.base_address, self)

    address = property(get_address)

    def get_game_manager(self) -> "GameManager":
        address = self.get_address()
        return address.add_and_follow(address.offsets.game_manager).cast(GameManager)

    game_manager = property(get_game_manager)


class LinuxState(SystemState):
    def load(self) -> None:
        self.process_id = linux_get_process_id_from_name(self.process_name)

        self.process_handle = linux_open_process(self.process_id)

        self.base_address = linux_get_base_address_from_handle(self.process_handle)

        self.loaded = True

    def allocate_memory(self, address: int, size: int) -> int:
        return linux_allocate_memory(self.process_handle, address, size)

    def free_memory(self, address: int, size: int) -> None:
        return linux_free_memory(self.process_handle, address, size)

    def protect_at(self, address: int, size: int) -> int:
        return linux_protect_process_memory(self.process_handle, address, size)

    def raw_read_at(self, address: int, size: int) -> bytes:
        return linux_read_process_memory(self.process_handle, address, size)

    def raw_write_at(self, address: int, data: bytes) -> int:
        return linux_write_process_memory(self.process_handle, address, data)

    def inject_dll(self, path: Union[str, Path]) -> bool:
        return linux_inject_dll(self.process_id, path)

    def close(self) -> None:
        return linux_close_process(self.process_handle)

    def terminate(self) -> bool:
        return linux_terminate_process(self.process_handle)


class MacOSState(SystemState):
    def load(self) -> None:
        self.process_id = macos_get_process_id_from_name(self.process_name)

        self.process_handle = macos_open_process(self.process_id)

        self.base_address = macos_get_base_address_from_handle(self.process_handle)

        self.loaded = True

    def allocate_memory(self, address: int, size: int) -> int:
        return macos_allocate_memory(self.process_handle, address, size)

    def free_memory(self, address: int, size: int) -> None:
        return macos_free_memory(self.process_handle, address, size)

    def protect_at(self, address: int, size: int) -> int:
        return macos_protect_process_memory(self.process_handle, address, size)

    def raw_read_at(self, address: int, size: int) -> bytes:
        return macos_read_process_memory(self.process_handle, address, size)

    def raw_write_at(self, address: int, data: bytes) -> int:
        return macos_write_process_memory(self.process_handle, address, data)

    def inject_dll(self, path: Union[str, Path]) -> bool:
        return macos_inject_dll(self.process_id, path)

    def close(self) -> None:
        return macos_close_process(self.process_handle)

    def terminate(self) -> bool:
        return macos_terminate_process(self.process_handle)

    def read_string(self, address: int) -> str:
        address = self.read_pointer(address)  # in MacOS, string is pointing to actual structure

        size_address = address + MACOS_STRING_SIZE_OFFSET

        size = self.read_size(size_address)

        return string.from_bytes(self.read_at(address, size))

    def write_string(self, value: str, address: int) -> int:
        actual_address = address

        address = self.read_pointer(address)  # see above

        size_address = address + MACOS_STRING_SIZE_OFFSET

        previous_size = self.read_size(size_address)

        data = string.to_bytes(value)

        size = len(data) - 1  # account for null terminator

        if size > previous_size:
            address = self.allocate_memory(0, size)

            self.write_pointer(address, actual_address)

            size_address = address + MACOS_STRING_SIZE_OFFSET

        self.write_size(size, size_address)

        return self.write_at(address, data)


class WindowsState(SystemState):
    def load(self) -> None:
        try:
            self.process_id = windows_get_process_id_from_name(self.process_name)

        except LookupError:
            self.process_id = windows_get_process_id_from_window_title(self.window_title)

            if not self.process_id:
                raise

        self.process_handle = windows_open_process(self.process_id)

        self.base_address = windows_get_base_address(self.process_id, self.process_name)

        self.loaded = True

    reload = load

    def allocate_memory(self, address: int, size: int) -> int:
        return windows_allocate_memory(self.process_handle, address, size)

    def free_memory(self, address: int, size: int) -> None:
        return windows_free_memory(self.process_handle, address, size)

    def protect_at(self, address: int, size: int) -> int:
        return windows_protect_process_memory(self.process_handle, address, size)

    def raw_read_at(self, address: int, size: int) -> bytes:
        return windows_read_process_memory(self.process_handle, address, size)

    def raw_write_at(self, address: int, data: bytes) -> int:
        return windows_write_process_memory(self.process_handle, address, data)

    def inject_dll(self, path: Union[str, Path]) -> bool:
        return windows_inject_dll(self.process_id, path)

    def close(self) -> None:
        return windows_close_process(self.process_handle)

    def terminate(self) -> bool:
        return windows_terminate_process(self.process_handle)

    def read_string(self, address: int) -> str:
        size_address = address + WINDOWS_STRING_SIZE_OFFSET

        size = self.read_size(size_address)

        if size < WINDOWS_STRING_SIZE_OFFSET:
            try:
                return string.from_bytes(self.read_at(address, size))
            except UnicodeDecodeError:  # failed to read, let's try to interpret as a pointer
                pass

        address = self.read_size(address)

        return string.from_bytes(self.read_at(address, size))

    def write_string(self, value: str, address: int) -> int:
        size_address = address + WINDOWS_STRING_SIZE_OFFSET

        data = string.to_bytes(value)

        size = len(data) - 1  # account for null terminator

        self.write_size(size, size_address)

        if size > WINDOWS_STRING_SIZE_OFFSET:
            new_address = self.allocate_memory(0, size)

            self.write_pointer(new_address, address)

            address = new_address

        return self.write_at(address, data)


State: Type[SystemState]


if LINUX:
    State = LinuxState

elif MACOS:
    State = MacOSState

elif WINDOWS:
    State = WindowsState

else:
    State = SystemState


class Address:
    OFFSETS = {
        LinuxState: linux_offsets,
        MacOSState: macos_offsets,
        WindowsState: windows_offsets,
        SystemState: offsets,
    }

    def __init__(self, address: int, state: SystemState) -> None:
        self.address = address
        self.state = state
        self.offsets = self.OFFSETS[type(state)]

    def __repr__(self) -> str:
        info = {"address": hex(self.address), "state": self.state}

        return make_repr(self, info)

    def add(self: AddressT, value: int) -> AddressT:
        return self.__class__(self.address + value, self.state)

    def sub(self: AddressT, value: int) -> AddressT:
        return self.__class__(self.address - value, self.state)

    def cast(self: AddressT, cls: Type[AddressU]) -> AddressU:
        return cls(self.address, self.state)

    def follow_pointer(self: AddressT) -> AddressT:
        return self.__class__(self.read_pointer(), self.state)

    def follow_and_add(self: AddressT, value: int) -> AddressT:
        return self.follow_pointer().add(value)

    def follow_and_sub(self: AddressT, value: int) -> AddressT:
        return self.follow_pointer().sub(value)

    def add_and_follow(self: AddressT, value: int) -> AddressT:
        return self.add(value).follow_pointer()

    def sub_and_follow(self: AddressT, value: int) -> AddressT:
        return self.sub(value).follow_pointer()

    def protect_at(self, size: int) -> int:
        return self.state.protect_at(self.address, size)

    def read_at(self, size: int) -> bytes:
        return self.state.read_at(self.address, size)

    def write_at(self, data: bytes) -> int:
        return self.state.write_at(self.address, data)

    def read_buffer(self, size: int) -> Buffer:
        return self.state.read_buffer(size, self.address)

    def write_buffer(self, data: Buffer) -> int:
        return self.state.write_buffer(data, self.address)

    def read(self, type: Data[T]) -> T:
        return self.state.read(type, self.address)

    def write(self, type: Data[T], value: T) -> int:
        return self.state.write(type, value, self.address)

    def read_pointer(self) -> int:
        return self.state.read_pointer(self.address)

    def write_pointer(self, value: int) -> int:
        return self.state.write_pointer(value, self.address)

    def read_size(self) -> int:
        return self.state.read_size(self.address)

    def write_size(self, value: int) -> int:
        return self.state.write_size(value, self.address)

    def read_bool(self) -> bool:
        return self.state.read_bool(self.address)

    def write_bool(self, value: bool) -> int:
        return self.state.write_bool(value, self.address)

    def read_int8(self) -> int:
        return self.state.read_int8(self.address)

    def write_int8(self, value: int) -> int:
        return self.state.write_int8(value, self.address)

    def read_uint8(self) -> int:
        return self.state.read_uint8(self.address)

    def write_uint8(self, value: int) -> int:
        return self.state.write_uint8(value, self.address)

    def read_int16(self) -> int:
        return self.state.read_int16(self.address)

    def write_int16(self, value: int) -> int:
        return self.state.write_int16(value, self.address)

    def read_uint16(self) -> int:
        return self.state.read_uint16(self.address)

    def write_uint16(self, value: int) -> int:
        return self.state.write_uint16(value, self.address)

    def read_int32(self) -> int:
        return self.state.read_int32(self.address)

    def write_int32(self, value: int) -> int:
        return self.state.write_int32(value, self.address)

    def read_uint32(self) -> int:
        return self.state.read_uint32(self.address)

    def write_uint32(self, value: int) -> int:
        return self.state.write_uint32(value, self.address)

    def read_int64(self) -> int:
        return self.state.read_int64(self.address)

    def write_int64(self, value: int) -> int:
        return self.state.write_int64(value, self.address)

    def read_uint64(self) -> int:
        return self.state.read_uint64(self.address)

    def write_uint64(self, value: int) -> int:
        return self.state.write_uint64(value, self.address)

    def read_byte(self) -> int:
        return self.state.read_byte(self.address)

    def write_byte(self, value: int) -> int:
        return self.state.write_byte(value, self.address)

    def read_ubyte(self) -> int:
        return self.state.read_ubyte(self.address)

    def write_ubyte(self, value: int) -> int:
        return self.state.write_ubyte(value, self.address)

    def read_short(self) -> int:
        return self.state.read_short(self.address)

    def write_short(self, value: int) -> int:
        return self.state.write_short(value, self.address)

    def read_ushort(self) -> int:
        return self.state.read_ushort(self.address)

    def write_ushort(self, value: int) -> int:
        return self.state.write_ushort(value, self.address)

    def read_int(self) -> int:
        return self.state.read_int(self.address)

    def write_int(self, value: int) -> int:
        return self.state.write_int(value, self.address)

    def read_uint(self) -> int:
        return self.state.read_uint(self.address)

    def write_uint(self, value: int) -> int:
        return self.state.write_uint(value, self.address)

    def read_long(self) -> int:
        return self.state.read_long(self.address)

    def write_long(self, value: int) -> int:
        return self.state.write_long(value, self.address)

    def read_ulong(self) -> int:
        return self.state.read_ulong(self.address)

    def write_ulong(self, value: int) -> int:
        return self.state.write_ulong(value, self.address)

    def read_longlong(self) -> int:
        return self.state.read_longlong(self.address)

    def write_longlong(self, value: int) -> int:
        return self.state.write_longlong(value, self.address)

    def read_ulonglong(self) -> int:
        return self.state.read_ulonglong(self.address)

    def write_ulonglong(self, value: int) -> int:
        return self.state.write_ulonglong(value, self.address)

    def read_float32(self) -> float:
        return self.state.read_float32(self.address)

    def write_float32(self, value: float) -> int:
        return self.state.write_float32(value, self.address)

    def read_float64(self) -> float:
        return self.state.read_float64(self.address)

    def write_float64(self, value: float) -> int:
        return self.state.write_float64(value, self.address)

    def read_string(self) -> str:
        return self.state.read_string(self.address)

    def write_string(self, value: str) -> int:
        return self.state.write_string(value, self.address)


class GameManager(Address):
    def get_play_layer(self) -> "PlayLayer":
        return self.add_and_follow(self.offsets.play_layer).cast(PlayLayer)

    play_layer = property(get_play_layer)

    def get_editor_layer(self) -> "EditorLayer":
        return self.add_and_follow(self.offsets.editor_layer).cast(EditorLayer)

    editor_layer = property(get_editor_layer)


class BaseGameLayer(Address):
    def get_level_settings(self) -> "LevelSettingsLayer":
        return self.add_and_follow(self.offsets.level_settings).cast(LevelSettingsLayer)

    level_settings = property(get_level_settings)


class PlayLayer(BaseGameLayer):
    pass


class EditorLayer(BaseGameLayer):
    pass


class LevelSettingsLayer(Address):
    def get_level(self) -> "GameLevel":
        return self.add_and_follow(self.offsets.level).cast(GameLevel)

    level = property(get_level)


class GameLevel(Address):
    def get_id(self) -> int:
        return self.add(self.offsets.level_id).read_uint()

    def set_id(self, value: int) -> None:
        self.add(self.offsets.level_id).write_uint(value)

    id = property(get_id, set_id)

    def get_name(self) -> str:
        return self.add(self.offsets.level_name).read_string()

    def set_name(self, value: str) -> None:
        self.add(self.offsets.level_name).write_string(value)

    name = property(get_name, set_name)

    def get_creator_name(self) -> str:
        return self.add(self.offsets.level_creator_name).read_string()

    def set_creator_name(self, value: str) -> None:
        self.add(self.offsets.level_creator_name).write_string(value)

    creator_name = property(get_creator_name, set_creator_name)

    def get_difficulty_numerator(self) -> int:
        return self.add(self.offsets.level_difficulty_numerator).read_uint()

    def set_difficulty_numerator(self, value: int) -> None:
        self.add(self.offsets.level_difficulty_numerator).write_uint(value)

    difficulty_numerator = property(get_difficulty_numerator, set_difficulty_numerator)

    def get_difficulty_denominator(self) -> int:
        return self.add(self.offsets.level_difficulty_denominator).read_uint()

    def set_difficulty_denominator(self, value: int) -> None:
        self.add(self.offsets.level_difficulty_denominator).write_uint(value)

    difficulty_denominator = property(get_difficulty_denominator, set_difficulty_denominator)

    @property
    def level_difficulty(self) -> int:
        if self.difficulty_denominator:
            return self.difficulty_numerator // self.difficulty_denominator

        return 0

    def get_attempts(self) -> int:
        return self.add(self.offsets.level_attempts).read_uint()

    def set_attempts(self, value: int) -> None:
        self.add(self.offsets.level_attempts).write_uint(value)

    attempts = property(get_attempts, set_attempts)

    def get_jumps(self) -> int:
        return self.add(self.offsets.level_jumps).read_uint()

    def set_jumps(self, value: int) -> None:
        self.add(self.offsets.level_jumps).write_uint(value)

    jumps = property(get_jumps, set_jumps)

    def get_normal_percent(self) -> int:
        return self.add(self.offsets.level_normal_percent).read_uint()

    def set_normal_percent(self, value: int) -> None:
        self.add(self.offsets.level_normal_percent).write_uint(value)

    normal_percent = property(get_normal_percent, set_normal_percent)

    def get_practice_percent(self) -> int:
        return self.add(self.offsets.level_practice_percent).read_uint()

    def set_practice_percent(self, value: int) -> None:
        self.add(self.offsets.level_practice_percent).write_uint(value)

    practice_percent = property(get_practice_percent, set_practice_percent)

    def get_score(self) -> int:
        return self.add(self.offsets.level_score).read_int()

    def set_score(self, value: int) -> None:
        self.add(self.offsets.level_score).write_int(value)

    score = property(get_score, set_score)

    def is_featured(self) -> bool:
        return self.score > 0

    def was_unfeatured(self) -> bool:
        return self.score < 0

    def get_epic(self) -> bool:
        return self.add(self.offsets.level_epic).read_bool()

    def set_epic(self, value: bool) -> None:
        self.add(self.offsets.level_epic).write_bool(value)

    epic = property(get_epic, set_epic)

    def is_epic(self) -> bool:
        return self.epic

    def get_demon(self) -> bool:
        return self.add(self.offsets.level_demon).read_bool()

    def set_demon(self, value: bool) -> None:
        self.add(self.offsets.level_demon).write_bool(value)

    demon = property(get_demon, set_demon)

    def is_demon(self) -> bool:
        return self.demon

    def get_demon_difficulty(self) -> int:
        return self.add(self.offsets.level_demon_difficulty).read_uint()

    def set_demon_difficulty(self, value: int) -> None:
        self.add(self.offsets.level_demon_difficulty).write_uint(value)

    demon_difficulty = property(get_demon_difficulty, set_demon_difficulty)

    def get_stars(self) -> int:
        return self.add(self.offsets.level_stars).read_uint()

    def set_stars(self, value: int) -> None:
        self.add(self.offsets.level_stars).write_uint(value)

    stars = property(get_stars, set_stars)

    def is_rated(self) -> bool:
        return self.stars > 0

    def get_auto(self) -> bool:
        return self.add(self.offsets.level_auto).read_bool()

    def set_auto(self, value: bool) -> None:
        self.add(self.offsets.level_auto).write_bool(value)

    auto = property(get_auto, set_auto)

    def is_auto(self) -> bool:
        return self.auto

    def get_difficulty(self) -> Union[LevelDifficulty, DemonDifficulty]:
        return get_actual_difficulty(
            level_difficulty=self.level_difficulty,
            demon_difficulty=self.demon_difficulty,
            is_auto=self.is_auto(),
            is_demon=self.is_demon(),
        )

    def set_difficulty(self, difficulty: Union[LevelDifficulty, DemonDifficulty]) -> None:
        ...

    difficulty = property(get_difficulty, set_difficulty)

    def get_level_type_value(self) -> int:
        return self.add(self.offsets.level_level_type_value).read_uint()

    def set_level_type_value(self, value: int) -> None:
        self.add(self.offsets.level_level_type_value).write_uint(value)

    level_type_value = property(get_level_type_value, set_level_type_value)

    def get_level_type(self) -> LevelType:
        return LevelType.from_value(self.level_type_value, 0)

    def set_level_type(self, level_type: Union[int, str, LevelType]) -> None:
        self.level_type_value = LevelType.from_value(level_type).value

    level_type = property(get_level_type, set_level_type)
