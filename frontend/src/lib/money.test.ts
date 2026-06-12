import { describe, expect, it } from 'vitest';
import { formatMoney, parseAmountToCents } from './money';

const THIN_SPACE = String.fromCharCode(0x202f);
const NBSP = String.fromCharCode(0x00a0);
const MINUS = String.fromCharCode(0x2212);

describe('formatMoney', () => {
  it('formats whole and fractional cents with a comma decimal', () => {
    expect(formatMoney(1230)).toBe(`12,30${NBSP}€`);
    expect(formatMoney(5)).toBe(`0,05${NBSP}€`);
    expect(formatMoney(0)).toBe(`0,00${NBSP}€`);
  });

  it('groups thousands with a thin space', () => {
    expect(formatMoney(124730)).toBe(`1${THIN_SPACE}247,30${NBSP}€`);
    expect(formatMoney(123456789)).toBe(`1${THIN_SPACE}234${THIN_SPACE}567,89${NBSP}€`);
  });

  it('uses a true minus sign for negatives and + only when asked', () => {
    expect(formatMoney(-1230)).toBe(`${MINUS}12,30${NBSP}€`);
    expect(formatMoney(1230, { signed: true })).toBe(`+12,30${NBSP}€`);
    expect(formatMoney(0, { signed: true })).toBe(`+0,00${NBSP}€`);
  });
});

describe('parseAmountToCents', () => {
  it('accepts comma and dot decimals and grouped input', () => {
    expect(parseAmountToCents('12,50')).toBe(1250);
    expect(parseAmountToCents('12.50')).toBe(1250);
    expect(parseAmountToCents('1 200')).toBe(120000);
    expect(parseAmountToCents('8,40 €')).toBe(840);
    expect(parseAmountToCents('5')).toBe(500);
  });

  it('rejects empty, zero, negative, and non-numeric input', () => {
    expect(parseAmountToCents('')).toBeNull();
    expect(parseAmountToCents('0')).toBeNull();
    expect(parseAmountToCents('-5')).toBeNull();
    expect(parseAmountToCents('abc')).toBeNull();
  });
});
