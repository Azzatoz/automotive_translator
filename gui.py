#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Точка входа GUI. Реализация — в gui_pkg/. Зависимости: pip install -r requirements/gui.txt"""

from __future__ import annotations

import sys

from gui_pkg.app import main

if __name__ == "__main__":
    sys.exit(main())
