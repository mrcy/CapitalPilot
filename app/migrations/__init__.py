"""مهاجرت ساختار دیتابیس (بدون وابستگی خارجی).

هر مهاجرت یک تابع شماره‌دار و idempotent است. پیش از اعمال مهاجرت روی دیتابیس موجود،
نسخهٔ پشتیبان فایل SQLite گرفته می‌شود. ستون‌های جدید مدل‌ها به‌صورت خودکار با ALTER TABLE
اضافه می‌شوند و داده‌های قبلی هرگز حذف نمی‌شود.
"""
from .runner import LATEST_VERSION, run_migrations

__all__ = ["run_migrations", "LATEST_VERSION"]
