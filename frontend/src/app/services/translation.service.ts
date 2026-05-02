import { Injectable, signal } from '@angular/core';
import en from '../../assets/i18n/en.json';
import hu from '../../assets/i18n/hu.json';

export type Lang = 'en' | 'hu';

const COOKIE_KEY = 'tpt_lang';
const DICTIONARIES: Record<Lang, Record<string, string>> = { en, hu };

function getCookie(name: string): string | null {
  const match = document.cookie.match(new RegExp('(?:^|; )' + name + '=([^;]*)'));
  return match ? decodeURIComponent(match[1]) : null;
}

function setCookie(name: string, value: string, days = 365): void {
  const exp = new Date(Date.now() + days * 864e5).toUTCString();
  document.cookie = `${name}=${encodeURIComponent(value)}; expires=${exp}; path=/; SameSite=Lax`;
}

function detectBrowserLang(): Lang {
  const nav = navigator.language || (navigator as any).userLanguage || '';
  return nav.toLowerCase().startsWith('hu') ? 'hu' : 'en';
}

@Injectable({ providedIn: 'root' })
export class TranslationService {
  readonly lang = signal<Lang>(this._initLang());

  private _initLang(): Lang {
    const cookie = getCookie(COOKIE_KEY) as Lang | null;
    if (cookie && (cookie === 'en' || cookie === 'hu')) return cookie;
    const detected = detectBrowserLang();
    setCookie(COOKIE_KEY, detected);
    return detected;
  }

  setLang(lang: Lang): void {
    this.lang.set(lang);
    setCookie(COOKIE_KEY, lang);
  }

  t(key: string): string {
    const dict = DICTIONARIES[this.lang()];
    return dict[key] ?? DICTIONARIES['en'][key] ?? key;
  }
}
