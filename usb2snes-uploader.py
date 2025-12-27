#!/usr/bin/python3
# -*- coding: utf-8 -*-
# vim: set fenc=utf-8 ai ts=4 sw=4 sts=4 et:
#
# A simple usb2snes file uploading script.
#
# Distributed under the MIT License (MIT)
#
# Copyright (c) 2020, Marcus Rowe <undisbeliever@gmail.com>
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

import argparse
import contextlib
import json
import os.path
import posixpath
import re
from typing import Final, Generator, Optional, Tuple

import websocket  # type: ignore[import]


# Usb2Snes genealogy:
#  * Originally written in 2020 using `websockets` and `aiofiles` packages for
#    usb2snes-uploader.py
#  * Used in unnamed-snes-game for a resources-over-usb2snes subsystem in 2022
#  * Rewritten to use the non-async `websocket-client` package in 2023
#  * USB2SNES_VRAM_OFFSET added for smpspeed-usb2snes in 2025
#  * Merged usb2snes-uploader.py and smpspeed-usb2snes Usb2Snes classes in
#    December 2025
class Usb2Snes:
    BLOCK_SIZE: Final[int] = 1024

    DIR_PATH_TYPE: Final[str] = "0"

    USB2SNES_SRAM_OFFSET: Final[int] = 0xE00000
    USB2SNES_WRAM_OFFSET: Final[int] = 0xF50000
    USB2SNES_VRAM_OFFSET: Final[int] = 0xF70000

    def __init__(self, socket: websocket.WebSocket) -> None:
        self._socket: Final = socket
        self._device: Optional[str] = None

    def device_name(self) -> Optional[str]:
        return self._device

    def _assert_attached(self) -> None:
        if self._socket is None or self._socket.status is None:
            raise RuntimeError("Socket is closed")

        if self._device is None:
            raise RuntimeError("Not attached to device")

    def _request(self, opcode: str, *operands: str) -> None:
        self._assert_attached()
        self._socket.send(
            json.dumps(
                {
                    "Opcode": opcode,
                    "Space": "SNES",
                    "Flags": None,
                    "Operands": operands,
                }
            )
        )

    def _request_not_attached(self, opcode: str, *operands: str) -> None:
        if self._socket is None or self._socket.status is None:
            raise RuntimeError("Socket is closed")

        self._socket.send(
            json.dumps(
                {
                    "Opcode": opcode,
                    "Space": "SNES",
                    "Flags": None,
                    "Operands": operands,
                }
            )
        )

    def _response(self) -> list[str]:
        r = json.loads(self._socket.recv())
        r = r["Results"]

        if not isinstance(r, list):
            raise TypeError("Invalid response type, expected a list of strings.")

        if not all(isinstance(i, str) for i in r):
            raise TypeError("Invalid response type, expected a list of strings.")

        return r

    def _request_response(self, opcode: str, *operands: str) -> list[str]:
        self._request(opcode, *operands)
        return self._response()

    def find_and_attach_device(self) -> str:
        """
        Look through the DeviceList and connect to the first SD2SNES reported.

        Raises a RuntimeError if no SD2SNES device is found.
        """

        self._request_not_attached("DeviceList")
        device_list = self._response()

        device = None
        for d in device_list:
            if "SD2SNES" in d.upper():
                device = d
                break

        if device is None:
            raise RuntimeError(
                f"Could not find a usb2snes.\nDeviceList returned: {device_list}"
            )

        self._request_not_attached("Attach", device)

        self._device = device

        return device

    def get_playing_filename(self) -> str:
        r = self._request_response("Info")
        return r[2]

    def get_playing_basename(self) -> str:
        return posixpath.basename(self.get_playing_filename())

    def send_reset_command(self) -> None:
        # Reset command does not return a response
        self._request("Reset")

    def read_offset(self, offset: int, size: int) -> bytes:
        if size < 0:
            raise ValueError("Invalid size")

        self._request("GetAddress", hex(offset), hex(size))

        out = bytes()

        # This loop is required.
        # On my system, Work-RAM addresses are sent in 128 byte blocks.
        while len(out) < size:
            o = self._socket.recv()
            if not isinstance(o, bytes):
                raise RuntimeError(
                    f"Unknown response from QUsb2Snes, expected bytes got { type(out) }"
                )
            out += o

        if len(out) != size:
            raise RuntimeError(
                f"Size mismatch: got { len(out) } bytes, expected { size }"
            )

        return out

    def write_to_offset(self, offset: int, data: bytes) -> None:
        if not isinstance(data, bytes) and not isinstance(data, bytearray):
            raise ValueError(f"Expected bytes data, got { type(data) }")

        if offset >= self.USB2SNES_WRAM_OFFSET and offset < self.USB2SNES_SRAM_OFFSET:
            raise ValueError("Cannot write to Work-RAM")

        size: Final[int] = len(data)

        if size == 0:
            return

        self._request("PutAddress", hex(offset), hex(size))

        for chunk_start in range(0, size, self.BLOCK_SIZE):
            chunk_end = min(chunk_start + self.BLOCK_SIZE, size)

            self._socket.send_binary(data[chunk_start:chunk_end])

    def read_wram_addr(self, addr: int, size: int) -> bytes:
        wram_bank = addr >> 16

        if wram_bank == 0x7E or wram_bank == 0x7F:
            return self.read_offset((addr & 0x01FFFF) | self.USB2SNES_WRAM_OFFSET, size)
        elif wram_bank & 0x7F < 0x40:
            if addr & 0xFFFF >= 0x2000:
                return self.read_offset(
                    (addr & 0x1FFF) | self.USB2SNES_WRAM_OFFSET, size
                )

        raise ValueError("addr is not a Work-RAM address")

    def put_file(self, source_filename: str, dest_filename: str) -> None:
        """
        Transfer a file (source_filename) to the device with the usb2snes filename of dest_filename.
        """

        self._assert_attached()

        Usb2Snes._check_usb2snes_path(dest_filename)

        with open(source_filename, "rb") as fp:
            fp.seek(0, os.SEEK_END)
            file_size = fp.tell()

            fp.seek(0, os.SEEK_SET)

            self._request("PutFile", dest_filename, f"{file_size:x}")

            transferred = 0

            block = fp.read(Usb2Snes.BLOCK_SIZE)
            while block:
                self._socket.send_binary(block)
                transferred += len(block)

                block = fp.read(Usb2Snes.BLOCK_SIZE)

        if transferred != file_size:
            raise RuntimeError(
                f"transferred bytes ({transferred}) does not match file size ({file_size})"
            )

    def boot(self, usb2snes_path: str) -> None:
        """
        Boot a file on the device
        """
        self._request("Boot", usb2snes_path)

    def list(self, path: str) -> Tuple[list[str], list[str]]:
        """
        List all files and directories on the device at `path`.

        NOTE: If the path does not exist then QUsb2Snes will disconnect the socket.

        Returns: tuple : (directories list, files list)
        """

        dirs = list()
        files = list()
        for path_type, fn in self._list_iter(path):
            if path_type == Usb2Snes.DIR_PATH_TYPE:
                dirs.append(fn)
            else:
                files.append(fn)

        return dirs, files

    def check_file_exists(self, path: str) -> bool:
        """
        Returns true if `path` exists on the usb2snes and is a file.

        NOTE: If the parent of `path` does not exist then QUsb2Snes will disconnect the socket.
        """

        dirname, basename = posixpath.split(path)

        for path_type, fn in self._list_iter(dirname):
            if fn == basename:
                return path_type != Usb2Snes.DIR_PATH_TYPE

        return False

    def _list_iter(self, path: Optional[str]) -> Generator[Tuple[str, str], None, None]:
        if not path:
            path = "/"
        Usb2Snes._check_usb2snes_path(path)

        response = self._request_response("List", path)

        if len(response) % 2 != 0:
            raise RuntimeError(
                f"Invalid response from usb2snes: got {len(response)} entries, expected an even number of entries"
            )

        for i in range(0, len(response), 2):
            yield response[i], response[i + 1]

    @staticmethod
    def _check_usb2snes_path(path: str) -> None:
        if "\\" in path:
            raise RuntimeError("usb2snes path must not contain \\")

        if not path.startswith("/"):
            raise RuntimeError("usb2snes path must start with a /")

        if path.endswith("/") and path != "/":
            raise RuntimeError("usb2snes path must not end with /")


def main() -> None:
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "-a",
        "--address",
        required=False,
        default="ws://localhost:8080",
        help="Websocket address",
    )
    parser.add_argument(
        "-b", "--boot", action="store_true", help="Boot rom after uploading"
    )

    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "-f",
        "--force",
        action="store_true",
        help="Always upload rom, even if file exists",
    )
    group.add_argument(
        "-i", "--ignore", action="store_true", help="Ignore file already exists errors"
    )

    parser.add_argument("source_filename", help="File to upload")

    parser.add_argument(
        "-d", "--dir", required=False, help="Directory on usb2snes to store the rom"
    )
    parser.add_argument(
        "destination_filename", nargs="?", help="Filename of ROM on usb2snes"
    )

    args = parser.parse_args()

    basename = os.path.basename(args.source_filename)

    if args.dir:
        usb2snes_filename = posixpath.join(args.dir, basename)
    elif args.destination_filename:
        usb2snes_filename = args.destination_filename
    else:
        parser.error("Expected a --dir (-d) or destination_filename argument")

    with contextlib.closing(websocket.WebSocket()) as ws:
        ws.connect(args.address, origin="http://localhost")  # type: ignore

        usb2snes = Usb2Snes(ws)

        device = usb2snes.find_and_attach_device()

        file_exists = usb2snes.check_file_exists(usb2snes_filename)
        do_upload = not file_exists

        if file_exists:
            if args.force:
                do_upload = True
            elif args.ignore:
                do_upload = False
            else:
                raise RuntimeError(
                    f"file already exists on device: {usb2snes_filename}"
                )

            print(f"{usb2snes_filename} already exists on {device}")

        if do_upload:
            print(f"Uploading {basename} to {device}")
            usb2snes.put_file(args.source_filename, usb2snes_filename)

            # Annoying hack to force script to wait until file has finished uploading to device
            if usb2snes.check_file_exists(usb2snes_filename) == False:
                raise RuntimeError(f"file was not uploaded to device")

        if args.boot:
            print(f"Booting {usb2snes_filename}")
            usb2snes.boot(usb2snes_filename)


if __name__ == "__main__":
    main()
