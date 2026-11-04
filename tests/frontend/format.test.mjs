// تست واحد توابع قالب‌بندی و تبدیل ورودی (بدون مرورگر)
import test from 'node:test';
import assert from 'node:assert/strict';
import { addDaysISO, dateInputToISO, enDigits, faDigits, fmtDate, isoToDateInput, money, num, parseDecimal, pct, signedPct } from '../../app/static/js/format.js';

const strip = (s) => s.replace(/[\u2066\u2069\u200e]/g, '');

test('parseDecimal: ارقام فارسی/عربی/لاتین و جداکننده‌های هزارگان', () => {
  assert.equal(parseDecimal('۱٬۲۳۴٫۵'), '1234.5');
  assert.equal(parseDecimal('1,234.50'), '1234.50');
  assert.equal(parseDecimal('١٢٣'), '123');
  assert.equal(parseDecimal('۵۰،۰۰۰،۰۰۰'), '50000000');
  assert.equal(parseDecimal('-۲٫۵'), '-2.5');
  assert.equal(parseDecimal('−7'), '-7');
  assert.equal(parseDecimal(''), null);
  assert.ok(Number.isNaN(parseDecimal('12abc')));
  assert.ok(Number.isNaN(parseDecimal('1.2.3')));
});

test('enDigits و faDigits برگشت‌پذیرند', () => {
  assert.equal(faDigits('2026-11-04'), '۲۰۲۶-۱۱-۰۴');
  assert.equal(enDigits(faDigits('0123456789')), '0123456789');
});

test('قالب‌بندی پول و درصد همیشه ارقام فارسی دارد (بدون رقم لاتین)', () => {
  for (const s of [num(1234567), money(1234567.891, 2), pct(12.345), signedPct(-3.2), fmtDate('2026-11-04'), num(0), money(0)]) {
    assert.doesNotMatch(s, /[0-9]/, s);
  }
  assert.equal(strip(num(1234567)), '۱٬۲۳۴٬۵۶۷');
  assert.equal(strip(pct(12.5, 1)), '۱۲٫۵٪');
  assert.equal(num(null), '—');
  assert.equal(money(undefined), '—');
});

test('تاریخ شمسی ↔ میلادی', () => {
  assert.equal(fmtDate('2026-11-04'), '۱۴۰۵/۰۸/۱۳');
  assert.equal(dateInputToISO('1405/08/13', 'jalali'), '2026-11-04');
  assert.equal(dateInputToISO('۱۴۰۵/۰۸/۱۳', 'jalali'), '2026-11-04');
  assert.equal(dateInputToISO('1405/13/01', 'jalali'), null);
  assert.equal(dateInputToISO('1404/12/30', 'jalali'), null); // ۱۴۰۴ کبیسه نیست
  assert.equal(dateInputToISO('1403/12/30', 'jalali'), '2025-03-20'); // ۱۴۰۳ کبیسه است
  assert.equal(isoToDateInput('2026-11-04', 'jalali'), '1405/08/13');
  assert.equal(dateInputToISO('2026-02-30', 'gregorian'), null);
  assert.equal(addDaysISO('2026-02-27', 3), '2026-03-02');
});
