import { Injectable, effect, signal } from '@angular/core';

@Injectable({ providedIn: 'root' })
export class ThemeService {
  theme = signal<'light' | 'dark'>('light');

  constructor() {
    const urlTheme = new URLSearchParams(window.location.search).get('theme');
    if (urlTheme === 'dark' || urlTheme === 'light') {
      this.theme.set(urlTheme);
      localStorage.setItem('theme', urlTheme);
      const url = new URL(window.location.href);
      url.searchParams.delete('theme');
      window.history.replaceState({}, '', url.toString());
    } else {
      const saved = localStorage.getItem('theme');
      if (saved === 'dark' || saved === 'light') {
        this.theme.set(saved);
      } else {
        this.applySystemTheme();
      }
    }

    window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
      if (!localStorage.getItem('theme')) this.applySystemTheme();
    });

    effect(() => {
      document.documentElement.setAttribute('data-theme', this.theme());
    });
  }

  toggleTheme(): void {
    this.theme.update((current) => {
      const next = current === 'light' ? 'dark' : 'light';
      localStorage.setItem('theme', next);
      return next;
    });
  }

  private applySystemTheme(): void {
    const prefersDark = window.matchMedia?.('(prefers-color-scheme: dark)').matches;
    this.theme.set(prefersDark ? 'dark' : 'light');
  }
}
