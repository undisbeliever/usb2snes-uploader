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


import websockets
import asyncio
import aiofiles
import aiofiles.os
import json
import re
import os.path
import posixpath
import argparse


class Usb2Snes:
    BLOCK_SIZE = 1024

    DIR_PATH_TYPE = '0'

    def __init__(self, socket):
        self._socket = socket
        self._device = None


    def _assert_attached(self):
        if self._socket is None or not self._socket.open or self._socket.closed:
            raise RuntimeError("Socket is closed")

        if self._device is None:
            raise RuntimeError("Not attached to device")


    async def _request(self, opcode, *operands):
        self._assert_attached()

        await self._socket.send(json.dumps({
                'Opcode': opcode,
                'Space': "SNES",
                'Flags': None,
                "Operands": operands,
        }))


    async def _request_not_attached(self, opcode, *operands):
        if self._socket is None or not self._socket.open or self._socket.closed:
            raise RuntimeError("Socket is closed")

        await self._socket.send(json.dumps({
                'Opcode': opcode,
                'Space': "SNES",
                'Flags': None,
                "Operands": operands,
        }))


    async def _response(self):
        r = json.loads(await self._socket.recv())
        return r['Results']


    async def _request_response(self, opcode, *operands):
        await self._request(opcode, *operands)
        return await self._response()


    async def find_and_attach_device(self):
        """
        Look through the DeviceList and connect to the first SD2SNES reported.
        """

        await self._request_not_attached('DeviceList')
        device_list = await self._response()

        device = None
        for d in device_list:
            if 'SD2SNES' in d.upper():
                device = d
                break

        if device is None:
            raise RuntimeError(f"Could not find a usb2snes.\nDeviceList returned: {device_list}")

        await self._request_not_attached("Attach", device)

        self._device = device

        return device


    async def put_file(self, source_filename, dest_filename):
        """
        Transfer a file (source_filename) to the device with the usb2snes filename of dest_filename.
        """

        self._assert_attached()

        Usb2Snes._check_usb2snes_path(dest_filename)

        file_size = (await aiofiles.os.stat(source_filename)).st_size

        async with aiofiles.open(source_filename, 'rb') as fp:
            await self._request('PutFile', dest_filename, f"{file_size:x}")

            transferred = 0

            block = await fp.read(Usb2Snes.BLOCK_SIZE)
            while block:
                await self._socket.send(block)
                transferred += len(block)

                block = await fp.read(Usb2Snes.BLOCK_SIZE)

        if transferred != file_size:
            raise RuntimeError(f"transferred bytes ({transferred}) does not match file size ({file_size})")


    async def boot(self, usb2snes_path):
        """
        Boot a file on the device
        """
        await self._request("Boot", usb2snes_path)


    async def list(self, path):
        """
        List all files and directories on the device at `path`.

        NOTE: If the path does not exist then QUsb2Snes will disconnect the socket.

        Returns: tuple : (directories list, files list)
        """
        response = await self._list(path)

        dirs = list()
        files = list()
        for path_type, fn in Usb2Snes._list_iter(response):
            if path_type == Usb2Snes.DIR_PATH_TYPE:
                dirs.append(fn)
            else:
                files.append(fn)

        return dirs, files


    async def check_file_exists(self, path):
        """
        Returns true if `path` exists on the usb2snes and is a file.

        NOTE: If the parent of `path` does not exist then QUsb2Snes will disconnect the socket.
        """

        dirname, basename = posixpath.split(path)

        response = await self._list(dirname)

        for path_type, fn in Usb2Snes._list_iter(response):
            if fn == basename:
                return path_type != Usb2Snes.DIR_PATH_TYPE

        return False


    async def _list(self, path):
        if not path:
            path = '/'

        Usb2Snes._check_usb2snes_path(path)

        return await self._request_response('List', path)


    @staticmethod
    def _list_iter(response):
        if len(response) % 2 != 0:
            raise RuntimeError(f"Invalid response from usb2snes: got {len(response)} entries, expected an even number of entries")

        for i in range(0, len(response), 2):
            yield response[i], response[i + 1]


    @staticmethod
    def _check_usb2snes_path(path):
        if '\\' in path:
            raise RuntimeError('usb2snes path must not contain \\')

        if not path.startswith('/'):
            raise RuntimeError('usb2snes path must start with a /')

        if path.endswith('/') and path != '/':
            raise RuntimeError('usb2snes path must not end with /')



async def main():
    parser = argparse.ArgumentParser()

    parser.add_argument('-a', '--address', required=False,
                        default='ws://localhost:8080',
                        help='Websocket address')
    parser.add_argument('-b', '--boot', action='store_true',
                        help='Boot rom after uploading')


    group = parser.add_mutually_exclusive_group()
    group.add_argument('-f', '--force', action='store_true',
                       help='Always upload rom, even if file exists')
    group.add_argument('-i', '--ignore', action='store_true',
                       help='Ignore file already exists errors')

    parser.add_argument('source_filename',
                        help='File to upload')

    parser.add_argument('-d', '--dir', required=False,
                            help='Directory on usb2snes to store the rom')
    parser.add_argument('destination_filename', nargs='?',
                            help='Filename of ROM on usb2snes')

    args = parser.parse_args()


    basename = os.path.basename(args.source_filename)

    if args.dir:
        usb2snes_filename = posixpath.join(args.dir, basename)
    elif args.destination_filename:
        usb2snes_filename = args.destination_filename
    else:
        parser.error("Expected a --dir (-d) or destination_filename argument")


    async with websockets.connect(args.address) as socket:
        usb2snes = Usb2Snes(socket)

        device = await usb2snes.find_and_attach_device()

        file_exists = await usb2snes.check_file_exists(usb2snes_filename)
        do_upload = not file_exists

        if file_exists:
            if args.force:
                do_upload = True
            elif args.ignore:
                do_upload = False
            else:
                raise RuntimeError(f"file already exists on device: {usb2snes_filename}")

            print(f"{usb2snes_filename} already exists on {device}")


        if do_upload:
            print(f"Uploading {basename} to {device}")
            await usb2snes.put_file(args.source_filename, usb2snes_filename)

            # Annoying hack to force script to wait until file has finished uploading to device
            if await usb2snes.check_file_exists(usb2snes_filename) == False:
                raise RuntimeError(f"file was not uploaded to device")

        if args.boot:
            print(f"Booting {usb2snes_filename}")
            await usb2snes.boot(usb2snes_filename)


if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(main())

