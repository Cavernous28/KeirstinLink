"""Stub HTTP/WebSocket bridge for KeirstinLink.

Future home of a lightweight bridge protocol for remote Hermes instances.
For now it mirrors the FastAPI health/callback endpoints used by master.py.
"""
from __future__ import annotations

from fastapi import FastAPI

from .master import app as master_app

app = master_app
