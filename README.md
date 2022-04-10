usb2snes-uploader
=================

A simple file upload utility for the usb2snes sd2snes firmware.


Usage
-----

To upload a file to the usb2snes:

    > usb2snes-uploader.py Castle_Platformer.sfc /games/Castle_Platformer.sfc


To upload a file to the usb2snes inside the `/games` directory:

    > usb2snes-uploader.py Castle_Platformer.sfc -d /games


To upload a file to a usb2snes inside the `/games` directory and then boot it:

    > usb2snes-uploader.py -b Castle_Platformer.sfc -d /games



Requirements
============

 * an sd2snes or FXPAK with usb2snes compatible firmware
    * usb2snes firmware by Redguyyy ([Download Link](https://github.com/RedGuyyyy/sd2snes/releases/))
    * sd2snes/FXPAK [Firmware v1.11.0 beta 1](https://sd2snes.de/blog/archives/1157)
 * a usb2snes webserver ([QUsb2Snes](https://skarsnik.github.io/QUsb2snes/) is recommended)
 * python 3.7 or later
 * [python-websockets](https://github.com/aaugustin/websockets)
 * [python-aiofiles](https://github.com/Tinche/aiofiles)



Copyright
=========

Copyright (c) 2020, Marcus Rowe (undisbeliever)

Distributed under the MIT License (MIT), see [LICENSE](LICENSE) for details.

