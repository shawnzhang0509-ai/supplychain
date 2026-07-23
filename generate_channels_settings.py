#!/usr/bin/env python3
"""Scan an output/data root folder and generate channels_settings.json for all SKU channel subfolders.

Usage:
  python generate_channels_settings.py
  python generate_channels_settings.py "D:\\工作\\供应链\\自动出数据 - 20260721\\output"
"""

import json
import os
import sys

DEFAULT_LEAD_TIME = 90
DEFAULT_LOGISTICS_TIME = 30
CHANNELS_SETTINGS_FILE = "channels_settings.json"


def list_channel_folders(data_dir):
    return sorted(
        name for name in os.listdir(data_dir)
        if os.path.isdir(os.path.join(data_dir, name)) and not name.startswith((".", "_"))
    )


def normalize_entry(entry, fallback):
    entry = entry or {}
    try:
        lead_time = int(entry.get("LeadTime", fallback["LeadTime"]))
    except (TypeError, ValueError):
        lead_time = fallback["LeadTime"]
    try:
        logistics_time = int(entry.get("LogisticsTime", fallback["LogisticsTime"]))
    except (TypeError, ValueError):
        logistics_time = fallback["LogisticsTime"]
    return {
        "LeadTime": lead_time,
        "LogisticsTime": logistics_time,
        "备注": str(entry.get("备注", fallback.get("备注", ""))),
    }


def load_existing(path):
    document = {
        "_说明": (
            "放在数据根目录(output)。channels 键名=SKU渠道子文件夹名(如918、996)。"
            "LeadTime=LT预估天数，LogisticsTime=物流预估天数。"
        ),
        "default": {
            "LeadTime": DEFAULT_LEAD_TIME,
            "LogisticsTime": DEFAULT_LOGISTICS_TIME,
            "备注": "未单独配置的渠道使用 default",
        },
        "channels": {},
    }
    if not os.path.exists(path):
        return document
    with open(path, "r", encoding="utf-8") as handle:
        loaded = json.load(handle)
    if isinstance(loaded.get("default"), dict):
        document["default"] = normalize_entry(loaded["default"], document["default"])
    if isinstance(loaded.get("channels"), dict):
        document["channels"] = {
            str(name): normalize_entry(entry, document["default"])
            for name, entry in loaded["channels"].items()
            if not str(name).startswith("_")
        }
    if loaded.get("_说明"):
        document["_说明"] = str(loaded["_说明"])
    return document


def build_channels_settings(data_dir):
    settings_path = os.path.join(data_dir, CHANNELS_SETTINGS_FILE)
    document = load_existing(settings_path)
    default = document["default"]
    channels = list_channel_folders(data_dir)
    document["channels"] = {
        channel: normalize_entry(document["channels"].get(channel), default)
        for channel in channels
    }
    with open(settings_path, "w", encoding="utf-8") as handle:
        json.dump(document, handle, ensure_ascii=False, indent=2)
    return settings_path, channels, document


def main():
    data_dir = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), "data")
    data_dir = os.path.abspath(data_dir)
    if not os.path.isdir(data_dir):
        print(f"目录不存在: {data_dir}")
        sys.exit(1)
    settings_path, channels, document = build_channels_settings(data_dir)
    print(f"已生成: {settings_path}")
    print(f"共 {len(channels)} 个渠道:")
    for channel in channels:
        entry = document["channels"][channel]
        print(f"  {channel}: LT {entry['LeadTime']} / 物流 {entry['LogisticsTime']}")


if __name__ == "__main__":
    main()
