"""Helper warna terminal (Windows + Linux) via colorama."""

from __future__ import annotations

import os

from colorama import Fore, Style, init as colorama_init

colorama_init(autoreset=True)

NO_COLOR = os.getenv("NO_COLOR", "").strip() != ""


def _c(text: str, color: str) -> str:
    if NO_COLOR:
        return text
    return f"{color}{text}{Style.RESET_ALL}"


def header(text: str) -> str:
    return _c(text, Fore.CYAN + Style.BRIGHT)


def title(text: str) -> str:
    return _c(text, Fore.MAGENTA + Style.BRIGHT)


def info(text: str) -> str:
    return _c(text, Fore.CYAN)


def address(text: str) -> str:
    return _c(text, Fore.BLUE)


def balance(text: str) -> str:
    return _c(text, Fore.GREEN + Style.BRIGHT)


def zero(text: str) -> str:
    return _c(text, Fore.LIGHTBLACK_EX)


def warn(text: str) -> str:
    return _c(text, Fore.YELLOW)


def error(text: str) -> str:
    return _c(text, Fore.RED + Style.BRIGHT)


def success(text: str) -> str:
    return _c(text, Fore.GREEN)


def dim(text: str) -> str:
    return _c(text, Fore.LIGHTBLACK_EX)


def chain_name(text: str) -> str:
    return _c(text, Fore.WHITE + Style.BRIGHT)


def total(text: str) -> str:
    return _c(text, Fore.MAGENTA + Style.BRIGHT)


def usd(text: str) -> str:
    return _c(text, Fore.GREEN)


def label(text: str) -> str:
    return _c(text, Fore.YELLOW)
