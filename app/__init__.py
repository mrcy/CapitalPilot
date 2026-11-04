"""CapitalPilot — سیستم هوشمند مدیریت سرمایه‌گذاری شخصی."""

__version__ = "1.0.0"

import decimal as _decimal

# دقت محاسبات Decimal برای تمام Threadها (محاسبات مالی با ۴۰ رقم معنادار)
_decimal.DefaultContext.prec = 40
_decimal.setcontext(_decimal.DefaultContext)
